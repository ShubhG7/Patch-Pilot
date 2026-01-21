from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from langgraph.graph import END, StateGraph

from agent.config import load_agent_config, load_guardrails
from agent.guardrails.rules import Guardrails, GuardrailViolation
from agent.llm.provider import LLMError, LLMProvider
from agent.logging.json_logger import JsonLogger
from agent.state import AgentState, CheckResult, IssueContext
from agent.tools.github_api import GitHubAPI
from agent.tools.repo_tools import RepoTools
from agent.tools.runner import run_cmd
from agent.utils.slugify import slugify


def _parse_repro_branch(text: str) -> str | None:
    # Hyphen must be first/last in a character class (or escaped) to avoid "bad character range" errors.
    m = re.search(r"Repro Branch:\s*([A-Za-z0-9._/\\-]+)", text or "", flags=re.IGNORECASE)
    return m.group(1).strip() if m else None


def _strip_code_fences(s: str) -> str:
    s = s.strip()
    if s.startswith("```") and s.endswith("```"):
        inner = s.split("\n", 1)[1].rsplit("\n", 1)[0]
        return inner.strip()
    return s


def _unwrap_json_diff(text: str) -> str | None:
    """Extract and decode a JSON-wrapped diff like {"diff": "..."}.

    Models sometimes return the patch as JSON with escaped newlines; we need the decoded diff text.
    """
    t = _strip_code_fences(text).strip()
    if '"diff"' not in t:
        return None
    # Try parsing the largest JSON-ish object in the text.
    start = t.find("{")
    end = t.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = t[start : end + 1]
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict) and isinstance(obj.get("diff"), str) and obj["diff"].strip():
                # json.loads already decodes \n to actual newlines
                result = obj["diff"].strip()
                # Ensure we have actual newlines, not literal \n
                if "\\n" in result and "\n" not in result:
                    # Double-encoded? Try decoding again
                    result = result.replace("\\n", "\n")
                return result
        except Exception:  # noqa: BLE001
            pass
    # Fallback: regex-capture a JSON string literal for the diff field, then decode escapes.
    m = re.search(r'"diff"\s*:\s*"((?:\\.|[^"])*)"', t, re.DOTALL)
    if not m:
        return None
    captured = m.group(1)
    try:
        # Decode the JSON string (this handles \n -> newline)
        decoded = json.loads(f'"{captured}"')
        if isinstance(decoded, str):
            # Ensure newlines are actual newlines
            if "\\n" in decoded and "\n" not in decoded:
                decoded = decoded.replace("\\n", "\n")
            return decoded.strip() if decoded.strip() else None
    except Exception:  # noqa: BLE001
        return None
    return None


def _extract_diff(model_text: str) -> str:
    text = _strip_code_fences(model_text)
    unwrapped = _unwrap_json_diff(text)
    if unwrapped is not None:
        return unwrapped
    # Extract only the unified diff block (models sometimes append commentary after the patch).
    lines = text.splitlines()

    def is_diff_line(line: str) -> bool:
        return (
            line.startswith("diff --git ")
            or line.startswith("index ")
            or line.startswith("--- ")
            or line.startswith("+++ ")
            or line.startswith("@@")
            or line.startswith("+")
            or line.startswith("-")
            or line.startswith(" ")
            or line.startswith("\\ No newline at end of file")
        )

    # Find start of diff.
    start = None
    for i, line in enumerate(lines):
        if line.startswith("diff --git ") or line.startswith("--- "):
            start = i
            break
    if start is None:
        # Not a recognizable diff; return as-is but ensure trailing newline
        stripped = text.strip()
        return stripped + "\n" if stripped else ""

    # Collect until the start of a second file (new `--- a/` or `diff --git`) or non-diff text.
    out: list[str] = []
    seen_hunk = False
    for i, line in enumerate(lines[start:], start=start):
        # Stop if we hit a second file's header.
        if i > start and (line.startswith("diff --git ") or line.startswith("--- a/")):
            break
        if line.startswith("@@"):
            seen_hunk = True
        if is_diff_line(line):
            out.append(line)
            continue
        # Allow blank lines within the diff.
        if line.strip() == "":
            out.append(line)
            continue
        # If we've seen a hunk and hit non-diff text, we're done with this file.
        if seen_hunk:
            break
        # If we're still before hunks and hit non-diff text, treat as not-a-diff.
        stripped = text.strip()
        return stripped + "\n" if stripped else ""
    # git apply requires a trailing newline
    result = "\n".join(out).strip()
    if result:
        result += "\n"
    return result


def _looks_like_unified_diff(diff_text: str) -> bool:
    if not diff_text.strip():
        return False
    has_file_hdr = any(
        line.startswith("diff --git ") for line in diff_text.splitlines()
    ) or ("--- " in diff_text and "+++ " in diff_text)
    has_hunk = "@@" in diff_text
    return has_file_hdr and has_hunk


def _validate_hunk_prefixes(diff_text: str) -> tuple[bool, str]:
    """Validate that every line in hunks starts with ` `, `+`, or `-`.
    
    Returns (is_valid, error_message).
    """
    lines = diff_text.splitlines()
    in_hunk = False
    for i, line in enumerate(lines, 1):
        if line.startswith("@@"):
            in_hunk = True
            continue
        if in_hunk:
            if line.startswith("--- ") or line.startswith("+++ ") or line.startswith("diff --git "):
                in_hunk = False
                continue
            if line.strip() == "":
                continue  # Blank lines are OK
            if not (line.startswith(" ") or line.startswith("+") or line.startswith("-")):
                return False, f"Line {i} in hunk missing required prefix (must start with space, `+`, or `-`): {line[:60]}"
    return True, ""


def _shorten(s: str, n: int = 1200) -> str:
    s = s or ""
    return s if len(s) <= n else (s[:n] + "\n...<truncated>...\n")


def build_graph(
    *,
    repo_root: Path,
    gh: GitHubAPI,
    llm: LLMProvider,
    logger: JsonLogger,
) -> Any:
    cfg = load_agent_config(repo_root)
    rules_cfg = load_guardrails(repo_root)
    guard = Guardrails(cfg=rules_cfg)
    repo = RepoTools(repo_root=repo_root)

    def ingest_issue(state: dict[str, Any]) -> dict[str, Any]:
        s = AgentState(**state)
        logger.log("ingest_issue", "Loading issue and comments", issue=s.issue_number)
        issue = gh.get_issue(s.issue_number)
        comments = gh.list_issue_comments(s.issue_number)
        labels = [lbl.get("name", "") for lbl in (issue.get("labels") or []) if isinstance(lbl, dict)]
        ctx = IssueContext(
            title=issue.get("title", "") or "",
            body=issue.get("body", "") or "",
            comments=comments,
            labels=labels,
        )
        ctx.repro_branch = _parse_repro_branch(ctx.body)
        s.issue = ctx
        s.max_attempts = rules_cfg.max_attempts
        return s.model_dump()

    def checkout_repro_branch(state: dict[str, Any]) -> dict[str, Any]:
        s = AgentState(**state)
        if not s.issue.repro_branch:
            logger.log("checkout_repro_branch", "No repro branch specified; staying on current branch")
            return s.model_dump()
        logger.log(
            "checkout_repro_branch",
            "Checking out repro branch",
            repro_branch=s.issue.repro_branch,
        )
        r = run_cmd(["git", "checkout", s.issue.repro_branch], cwd=repo_root)
        if r.returncode != 0:
            s.failure_reason = f"Failed to checkout repro branch {s.issue.repro_branch}:\n{_shorten(r.stderr)}"
        return s.model_dump()

    def select_context(state: dict[str, Any]) -> dict[str, Any]:
        s = AgentState(**state)
        if s.failure_reason:
            return s.model_dump()
        max_files = int(cfg.context.get("max_files_to_inspect", 8))
        max_bytes = int(cfg.context.get("max_file_bytes", 6000))
        text = f"{s.issue.title}\n\n{s.issue.body}"
        tokens = sorted({t.lower() for t in re.findall(r"[A-Za-z_]{4,}", text)})
        hits: list[str] = []
        for t in tokens[:20]:
            hits.extend(repo.search("src", t, limit=5))
            hits.extend(repo.search("tests", t, limit=5))
            if len(hits) >= max_files * 2:
                break
        # Always consider pyproject + top tests as fallback.
        candidates = ["pyproject.toml"] + hits
        # De-dupe
        seen: set[str] = set()
        selected: list[str] = []
        for p in candidates:
            if p in seen:
                continue
            seen.add(p)
            if (repo_root / p).exists():
                selected.append(p)
            if len(selected) >= max_files:
                break
        s.selected_files = selected
        s.file_context = {p: repo.read_text(p, max_bytes=max_bytes) for p in selected}
        logger.log("select_context", "Selected context files", files=selected)
        return s.model_dump()

    def plan(state: dict[str, Any]) -> dict[str, Any]:
        s = AgentState(**state)
        if s.failure_reason:
            return s.model_dump()
        prompt = (
            "You are PatchPilot, an autonomous maintenance agent.\n"
            "Write a short, step-by-step plan to fix the GitHub issue.\n"
            "Constraints:\n"
            f"- Allowed paths: {rules_cfg.allowed_paths}\n"
            f"- Blocked paths: {rules_cfg.blocked_paths}\n"
            f"- Max files changed: {rules_cfg.max_files_changed}\n"
            f"- Max diff lines: {rules_cfg.max_diff_lines}\n"
            "\n"
            f"ISSUE TITLE:\n{s.issue.title}\n\n"
            f"ISSUE BODY:\n{s.issue.body}\n\n"
            "CONTEXT FILES:\n"
        )
        for p, content in s.file_context.items():
            prompt += f"\n---\nFILE: {p}\n{_shorten(content, 2500)}\n"
        logger.log("plan", "Generating plan via LLM", attempt=s.attempt)
        try:
            resp = llm.generate_text(prompt)
            s.plan_text = resp.text.strip()
        except LLMError as e:
            s.failure_reason = f"LLM plan generation failed: {e}"
            return s.model_dump()
        body = "### PatchPilot Plan\n\n" + s.plan_text
        gh.post_issue_comment(s.issue_number, body)
        logger.log("plan", "Posted plan comment")
        return s.model_dump()

    def propose_patch(state: dict[str, Any]) -> dict[str, Any]:
        s = AgentState(**state)
        if s.failure_reason:
            return s.model_dump()
        repair_context = ""
        if s.attempt > 1:
            repair_context = (
                "\nREPAIR CONTEXT (previous attempt failed):\n"
                f"CRITICAL: previous_failure_reason={s.failure_reason or 'n/a'}\n"
            )
            if s.failure_reason and ("corrupt patch" in s.failure_reason.lower() or "truncated" in s.failure_reason.lower()):
                repair_context += (
                    "\nYour previous diff was REJECTED. Common mistakes:\n"
                    "1. JSON wrapping - DO NOT wrap in JSON. Output raw diff only.\n"
                    "2. Missing line prefixes - EVERY hunk line must start with space/+/-.\n"
                    "3. Truncated diff - include the COMPLETE hunk with all changed lines.\n"
                )
                # Show the model exactly what it produced (so it can see the mistake).
                if s.diff_text:
                    corrupt_preview = "\n".join(s.diff_text.splitlines()[:60])
                    repair_context += (
                        f"\nHere is what you produced - this was REJECTED:\n"
                        f"```\n{corrupt_preview}\n```\n"
                    )
            if s.lint_result:
                repair_context += (
                    f"\nruff rc={s.lint_result.returncode}\n"
                    f"ruff out:\n{_shorten(s.lint_result.stdout, 1500)}\n"
                    f"ruff err:\n{_shorten(s.lint_result.stderr, 1500)}\n"
                )
            if s.test_result:
                repair_context += (
                    f"\npytest rc={s.test_result.returncode}\n"
                    f"pytest out:\n{_shorten(s.test_result.stdout, 1500)}\n"
                    f"pytest err:\n{_shorten(s.test_result.stderr, 1500)}\n"
                )
        prompt = (
            "You are PatchPilot. Produce a unified diff to fix the issue.\n"
            "\n"
            "CRITICAL RULES:\n"
            "1. Output ONLY a raw unified diff. NO JSON. NO commentary.\n"
            "2. Context lines (starting with space) must EXACTLY match the file content below.\n"
            "3. Every hunk line must start with: space (context), + (add), or - (remove).\n"
            "4. Do NOT invent or modify context - copy it exactly from the file.\n"
            "\n"
            "Guardrails:\n"
            f"  - allowed_paths={rules_cfg.allowed_paths}\n"
            f"  - blocked_paths={rules_cfg.blocked_paths}\n"
            "\n"
            "IMPORTANT: Read the CONTEXT FILES below carefully. Your diff context lines\n"
            "must EXACTLY match the actual file content (copy them precisely).\n"
            "\n"
            f"ISSUE TITLE:\n{s.issue.title}\n\n"
            f"ISSUE BODY:\n{s.issue.body}\n\n"
            f"PLAN:\n{s.plan_text or ''}\n\n"
            "CONTEXT FILES:\n"
        )
        for p, content in s.file_context.items():
            prompt += f"\n---\nFILE: {p}\n{_shorten(content, 2500)}\n"
        prompt += repair_context
        logger.log("propose_patch", "Generating patch via LLM", attempt=s.attempt)
        try:
            resp = llm.generate_text(prompt)
            s.diff_text = _extract_diff(resp.text)
            if not _looks_like_unified_diff(s.diff_text or ""):
                # Mark as retryable failure; repair_or_finish will loop.
                s.failure_reason = "Model did not return a valid unified diff with file headers."
        except LLMError as e:
            s.failure_reason = f"LLM patch generation failed: {e}"
        return s.model_dump()

    def apply_patch(state: dict[str, Any]) -> dict[str, Any]:
        s = AgentState(**state)
        if s.failure_reason:
            return s.model_dump()
        # Compute branch name, but only create it after we know the diff is valid.
        if not s.branch_name:
            s.branch_name = f"agent/issue-{s.issue_number}-{slugify(s.issue.title)}"

        diff = s.diff_text or ""
        # Belt-and-suspenders: unwrap JSON diff if it leaked through (shouldn't happen if _extract_diff worked).
        if diff.lstrip().startswith("{"):
            unwrapped = _unwrap_json_diff(diff)
            if unwrapped:
                diff = unwrapped
                s.diff_text = unwrapped
        # Also handle case where diff has literal \n instead of newlines (double-encoded or malformed JSON).
        if "\\n" in diff and diff.count("\n") < diff.count("\\n"):
            # Replace literal \n with actual newlines
            diff = diff.replace("\\n", "\n")
            s.diff_text = diff
        try:
            guard.validate_diff(diff)
        except GuardrailViolation as e:
            repo.git_reset_hard()
            repo.git_clean()
            s.failure_reason = f"Guardrail violation (diff): {e}"
            logger.log("apply_patch", "Guardrail blocked diff", level="warn", reason=str(e))
            # Add a small preview to make failures diagnosable from logs without downloading artifacts.
            preview = "\n".join((diff or "").splitlines()[:40])
            logger.log(
                "apply_patch",
                "Diff preview (first 40 lines)",
                level="warn",
                preview=_shorten(preview, 2000),
            )
            return s.model_dump()
        # Validate hunk prefixes BEFORE git apply --check (catches format errors early).
        is_valid, prefix_error = _validate_hunk_prefixes(diff)
        if not is_valid:
            s.failure_reason = f"Diff format error: {prefix_error}"
            logger.log("apply_patch", "Hunk prefix validation failed", level="warn", error=prefix_error)
            logger.log(
                "apply_patch",
                "Full corrupt diff (for debugging)",
                level="warn",
                full_diff=_shorten(diff or "", 5000),
            )
            return s.model_dump()
        # Validate with git apply --check BEFORE creating branch (catches corrupt patches early).
        logger.log("apply_patch", "Validating diff with git apply --check")
        check_result = repo.git_apply_check(diff)
        if check_result.returncode != 0:
            s.failure_reason = (
                f"Diff failed git apply --check (corrupt patch):\n{_shorten(check_result.stderr or check_result.stdout)}"
            )
            logger.log(
                "apply_patch",
                "git apply --check failed",
                level="warn",
                stderr=_shorten(check_result.stderr or "", 500),
            )
            # Log FULL diff for debugging (what did the model actually produce?).
            logger.log(
                "apply_patch",
                "Full corrupt diff (for debugging)",
                level="warn",
                full_diff=_shorten(diff or "", 5000),
            )
            return s.model_dump()
        # Branch name (create once, before applying patch, per workflow steps).
        logger.log("apply_patch", "Creating work branch", branch=s.branch_name)
        r = run_cmd(["git", "checkout", "-b", s.branch_name], cwd=repo_root)
        if r.returncode != 0:
            # If the branch already exists from a prior attempt/run, just reuse it.
            if "already exists" in (r.stderr or ""):
                r2 = run_cmd(["git", "checkout", s.branch_name], cwd=repo_root)
                if r2.returncode != 0:
                    s.failure_reason = f"Failed to checkout existing branch {s.branch_name}:\n{_shorten(r2.stderr)}"
                    return s.model_dump()
            else:
                s.failure_reason = f"Failed to create branch {s.branch_name}:\n{_shorten(r.stderr)}"
                return s.model_dump()
        logger.log("apply_patch", "Applying diff with git apply")
        r = repo.git_apply(diff)
        if r.returncode != 0:
            s.failure_reason = f"Failed to apply patch:\n{_shorten(r.stderr)}"
        return s.model_dump()

    def run_checks(state: dict[str, Any]) -> dict[str, Any]:
        s = AgentState(**state)
        if s.failure_reason:
            return s.model_dump()
        logger.log("run_checks", "Running lint", command=cfg.commands.lint)
        lint = run_cmd(cfg.commands.lint, cwd=repo_root, timeout_s=600)
        s.lint_result = CheckResult(
            command=lint.command,
            returncode=lint.returncode,
            stdout=lint.stdout,
            stderr=lint.stderr,
        )
        if lint.returncode != 0:
            s.checks_passed = False
            logger.log("run_checks", "Lint failed", level="warn", returncode=lint.returncode)
            return s.model_dump()
        logger.log("run_checks", "Running tests", command=cfg.commands.test)
        test = run_cmd(cfg.commands.test, cwd=repo_root, timeout_s=900)
        s.test_result = CheckResult(
            command=test.command,
            returncode=test.returncode,
            stdout=test.stdout,
            stderr=test.stderr,
        )
        s.checks_passed = test.returncode == 0
        logger.log(
            "run_checks",
            "Checks complete",
            checks_passed=s.checks_passed,
            pytest_rc=test.returncode,
        )
        return s.model_dump()

    def repair_or_finish(state: dict[str, Any]) -> dict[str, Any]:
        s = AgentState(**state)
        if s.failure_reason:
            # Some failures are retryable (bad diff / patch apply / guardrail diff parse).
            retryable_prefixes = (
                "Guardrail violation (diff):",
                "Failed to apply patch:",
                "Diff failed git apply --check",
                "LLM patch generation failed:",
                "Model did not return a valid unified diff",
            )
            if s.attempt < s.max_attempts and any(
                s.failure_reason.startswith(p) for p in retryable_prefixes
            ):
                logger.log(
                    "repair_or_finish",
                    "Retrying after patch-generation/apply failure",
                    level="warn",
                    attempt=s.attempt,
                    failure_reason=s.failure_reason,
                )
                repo.git_reset_hard()
                repo.git_clean()
                s.failure_reason = None
                s.checks_passed = False
                s.attempt += 1
                return s.model_dump()
            return s.model_dump()
        if s.checks_passed:
            return s.model_dump()
        if s.attempt >= s.max_attempts:
            s.failure_reason = "Checks failed after max attempts."
            return s.model_dump()
        # Reset working tree and try again.
        logger.log("repair_or_finish", "Repair iteration: resetting worktree", attempt=s.attempt)
        repo.git_reset_hard()
        repo.git_clean()
        # Stay on the same branch; patch will be applied again.
        s.attempt += 1
        return s.model_dump()

    def guardrails_validate(state: dict[str, Any]) -> dict[str, Any]:
        s = AgentState(**state)
        if s.failure_reason:
            return s.model_dump()
        # Validate the *actual* staged changes (includes added files).
        run_cmd(["git", "add", "-A"], cwd=repo_root)
        diff = run_cmd(["git", "diff", "--cached"], cwd=repo_root).stdout
        try:
            stats = guard.validate_diff(diff)
        except GuardrailViolation as e:
            repo.git_reset_hard()
            repo.git_clean()
            s.failure_reason = f"Guardrail violation (worktree): {e}"
            return s.model_dump()
        s.run_summary["files_changed"] = stats.files
        s.run_summary["changed_lines"] = stats.changed_lines
        logger.log("guardrails_validate", "Guardrails validated", **s.run_summary)
        return s.model_dump()

    def create_pr(state: dict[str, Any]) -> dict[str, Any]:
        s = AgentState(**state)
        if s.failure_reason:
            return s.model_dump()
        # Commit
        logger.log("create_pr", "Committing changes")
        run_cmd(["git", "add", "-A"], cwd=repo_root)
        msg = f"PatchPilot: fix #{s.issue_number}"
        c = run_cmd(["git", "commit", "-m", msg], cwd=repo_root)
        if c.returncode != 0:
            s.failure_reason = f"Git commit failed:\n{_shorten(c.stderr)}"
            return s.model_dump()
        # Push
        logger.log("create_pr", "Pushing branch", branch=s.branch_name)
        p = run_cmd(["git", "push", "-u", "origin", s.branch_name or ""], cwd=repo_root)
        if p.returncode != 0:
            s.failure_reason = f"Git push failed:\n{_shorten(p.stderr)}"
            return s.model_dump()
        # PR
        repo_info = gh.get_repo()
        base = repo_info.get("default_branch", "main") or "main"
        pr_title = f"Fix: {s.issue.title}"
        pr_body = (
            f"Fixes #{s.issue_number}\n\n"
            "### PatchPilot Run Summary\n"
            f"- Attempts: {s.attempt}/{s.max_attempts}\n"
            f"- Files changed: {len(s.run_summary.get('files_changed', []))}\n"
            f"- Diff lines: {s.run_summary.get('changed_lines', 0)}\n"
        )
        logger.log("create_pr", "Opening PR via GitHub API", base=base)
        pr = gh.create_pull_request(
            title=pr_title,
            head=s.branch_name or "",
            base=base,
            body=pr_body,
        )
        s.pr_url = pr.get("html_url")
        gh.post_issue_comment(
            s.issue_number,
            (
                "### PatchPilot Complete\n\n"
                f"Opened PR: {s.pr_url}\n\n"
                "Run summary:\n"
                f"- Attempts: {s.attempt}/{s.max_attempts}\n"
                f"- Files changed: {len(s.run_summary.get('files_changed', []))}\n"
                f"- Diff lines: {s.run_summary.get('changed_lines', 0)}\n"
            ),
        )
        return s.model_dump()

    def finalize(state: dict[str, Any]) -> dict[str, Any]:
        s = AgentState(**state)
        if not s.pr_url and not s.checks_passed and not s.failure_reason:
            s.failure_reason = "Aborted before creating a PR (no successful patch/checks)."
        logger.log(
            "finalize",
            "Finalizing run",
            checks_passed=s.checks_passed,
            pr_url=s.pr_url,
            failure_reason=s.failure_reason,
        )
        if s.failure_reason and not s.pr_url:
            gh.post_issue_comment(
                s.issue_number,
                (
                    "### PatchPilot Failed\n\n"
                    f"Reason: {s.failure_reason}\n\n"
                    "A JSONL log artifact was uploaded by the workflow (see Actions run artifacts)."
                ),
            )
        return s.model_dump()

    def route_after_checks(state: dict[str, Any]) -> str:
        s = AgentState(**state)
        if s.failure_reason:
            return "finalize"
        if s.checks_passed:
            return "guardrails_validate"
        return "propose_patch"

    graph = StateGraph(dict)
    graph.add_node("ingest_issue", ingest_issue)
    graph.add_node("checkout_repro_branch", checkout_repro_branch)
    graph.add_node("select_context", select_context)
    graph.add_node("plan", plan)
    graph.add_node("propose_patch", propose_patch)
    graph.add_node("apply_patch", apply_patch)
    graph.add_node("run_checks", run_checks)
    graph.add_node("repair_or_finish", repair_or_finish)
    graph.add_node("guardrails_validate", guardrails_validate)
    graph.add_node("create_pr", create_pr)
    graph.add_node("finalize", finalize)

    graph.set_entry_point("ingest_issue")
    graph.add_edge("ingest_issue", "checkout_repro_branch")
    graph.add_edge("checkout_repro_branch", "select_context")
    graph.add_edge("select_context", "plan")
    graph.add_edge("plan", "propose_patch")
    graph.add_edge("propose_patch", "apply_patch")
    graph.add_edge("apply_patch", "run_checks")
    graph.add_edge("run_checks", "repair_or_finish")
    graph.add_conditional_edges("repair_or_finish", route_after_checks)
    graph.add_edge("guardrails_validate", "create_pr")
    graph.add_edge("create_pr", "finalize")
    graph.add_edge("finalize", END)

    return graph.compile()

