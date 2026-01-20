# PatchPilot (Demo Repo)

PatchPilot is a **GitHub-embedded autonomous maintenance agent**. When an issue is labeled **`agent:fix`**, a GitHub Actions workflow runs a LangGraph-powered Python agent that:

- reads the issue + comments
- posts a “PatchPilot Plan” comment
- checks out an optional repro branch (from the issue body)
- creates a work branch (`agent/issue-<num>-<slug>`)
- generates + applies a unified diff within guardrails
- runs `ruff check .` and `pytest -q`
- retries up to 2 repairs on failure (3 attempts total)
- pushes a branch, opens a PR, and comments back with the PR link
- writes **JSONL** logs and uploads them as an Actions artifact

## Repo layout

- **Agent core (portable)**: `agent/`
- **Repo policy/config**: `AGENT_POLICY.md`, `agent_rules.yml`, `agent_config.yml`
- **Demo sandbox app**: `src/demo_app/`
- **Tests**: `tests/`
- **Workflow**: `.github/workflows/patchpilot.yml`

## Setup

1) Add a repository secret:

- **`LLM_API_KEY`**: your Gemini API key

2) (Optional) For local runs, copy `env.example` to your local env manager and export:

- `LLM_API_KEY`
- `GITHUB_TOKEN` (a PAT for local testing; Actions uses its own `GITHUB_TOKEN`)

## How to trigger PatchPilot

1) Create a GitHub Issue describing the bug/fix.
2) (Optional but recommended) include a repro branch line:

`Repro Branch: seed/issue-1`

3) Add the label **`agent:fix`** to the issue.

PatchPilot will comment a plan, then open a PR if checks pass.

## Demo walkthrough (seed issues)

This repo includes three deterministic “repro branches” you can reference from issue bodies.

- **Issue 1 (easy)**: failing test due to a simple bug  
  - **Repro Branch:** `seed/issue-1`
- **Issue 2 (medium)**: logic mismatch requiring a code change (+ a test tweak)  
  - **Repro Branch:** `seed/issue-2`
- **Issue 3 (hard)**: small refactor across 2 files (still within guardrails)  
  - **Repro Branch:** `seed/issue-3`

To run locally on a seed branch:

```bash
git checkout seed/issue-1
pip install -e ".[dev]"
ruff check .
pytest -q
```

## How PatchPilot works (high-level)

PatchPilot is **repo-agnostic**: the agent core does not depend on the demo app. Repo-specific behavior is driven by:

- `agent_config.yml`: commands to run (lint/test/format), context limits
- `agent_rules.yml`: machine-enforced guardrails (allowed/blocked paths, diff limits, attempts)
- `AGENT_POLICY.md`: human-readable policy

LangGraph node flow (implemented in `agent/graph.py`):

- `ingest_issue`
- `checkout_repro_branch`
- `select_context`
- `plan` (posts a plan comment)
- `propose_patch` (LLM outputs unified diff)
- `apply_patch`
- `run_checks` (ruff/pytest)
- `repair_or_finish` (loop up to max attempts)
- `guardrails_validate`
- `create_pr` (commit/push/open PR)
- `finalize` (final issue comment, logs)

## Porting PatchPilot to another repo

Copy these into the target repo:

- `agent/`
- `.github/workflows/patchpilot.yml`
- `agent_rules.yml`
- `agent_config.yml`
- `AGENT_POLICY.md`

Then update only the config files to match your repo’s commands and safety rules.

