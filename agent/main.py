from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
from pathlib import Path

from agent.graph import build_graph
from agent.llm.gemini_provider import from_env as gemini_from_env
from agent.llm.provider import LLMError
from agent.logging.json_logger import JsonLogger
from agent.state import AgentState
from agent.tools.github_api import GitHubAPI, GitHubAPIError


def _parse_repo(repo: str) -> tuple[str, str]:
    if "/" not in repo:
        raise ValueError("repo must be owner/name")
    owner, name = repo.split("/", 1)
    return owner, name


def _issue_from_event(path: str) -> int:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    issue = data.get("issue") or {}
    num = issue.get("number")
    if not isinstance(num, int):
        raise ValueError("Could not determine issue.number from event payload")
    return num


def _maybe_label_from_event(path: str) -> str | None:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    label = data.get("label") or {}
    name = label.get("name")
    return name if isinstance(name, str) else None


def _require_env(name: str) -> str:
    v = os.environ.get(name, "").strip()
    if not v:
        raise ValueError(f"Missing env var: {name}")
    return v


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="patchpilot")
    parser.add_argument("--repo", help="owner/name. If omitted, uses GITHUB_REPOSITORY.")
    parser.add_argument("--issue", type=int, help="Issue number. If omitted, uses GITHUB_EVENT_PATH.")
    parser.add_argument("--log-path", default="patchpilot_logs.jsonl")
    args = parser.parse_args(argv)

    repo_full = (args.repo or os.environ.get("GITHUB_REPOSITORY", "")).strip()
    if not repo_full:
        print("Missing --repo or GITHUB_REPOSITORY", file=sys.stderr)
        return 2
    owner, name = _parse_repo(repo_full)

    issue_num = args.issue
    event_path = os.environ.get("GITHUB_EVENT_PATH", "").strip()
    if issue_num is None:
        if not event_path:
            print("Missing --issue or GITHUB_EVENT_PATH", file=sys.stderr)
            return 2
        issue_num = _issue_from_event(event_path)

    log_path = Path(args.log_path)
    logger = JsonLogger(path=log_path)
    logger.log("bootstrap", "Starting PatchPilot", repo=repo_full, issue=issue_num)

    # Minimal safety: double-check trigger label (workflow already guards this).
    if event_path:
        label = _maybe_label_from_event(event_path)
        if label and label != "agent:fix":
            logger.log("bootstrap", "Skipping: not agent:fix label", level="warn", label=label)
            return 0

    try:
        gh = GitHubAPI(repo_full_name=repo_full, token=_require_env("GITHUB_TOKEN"))
    except (GitHubAPIError, ValueError) as e:
        logger.log("bootstrap", f"GitHub auth setup failed: {e}", level="error")
        return 2

    try:
        llm = gemini_from_env()
    except LLMError as e:
        # Comment and exit: this is a repo setup issue (missing secret).
        logger.log("bootstrap", f"LLM setup failed: {e}", level="error")
        with contextlib.suppress(Exception):
            gh.post_issue_comment(
                issue_num,
                (
                    "### PatchPilot Failed\n\n"
                    "Missing `LLM_API_KEY` in Actions secrets (required to run PatchPilot).\n\n"
                    "Add it as a repository secret and re-apply the `agent:fix` label."
                ),
            )
        return 2

    repo_root = Path.cwd()
    state = AgentState(
        repo_full_name=repo_full,
        repo_owner=owner,
        repo_name=name,
        issue_number=issue_num,
        log_path=str(log_path),
    ).model_dump()

    graph = build_graph(repo_root=repo_root, gh=gh, llm=llm, logger=logger)
    try:
        _ = graph.invoke(state)
    except Exception as e:  # noqa: BLE001
        logger.log("fatal", f"Unhandled exception: {e}", level="error")
        with contextlib.suppress(Exception):
            gh.post_issue_comment(
                issue_num,
                (
                    "### PatchPilot Failed\n\n"
                    "Unhandled exception while running the agent. See workflow artifact `patchpilot_logs.jsonl`."
                ),
            )
        return 1

    logger.log("bootstrap", "PatchPilot complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

