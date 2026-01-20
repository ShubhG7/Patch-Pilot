# PatchPilot Policy (Demo)

PatchPilot is a GitHub-embedded autonomous maintenance agent intended to fix issues **safely** and **predictably**.

## What PatchPilot will do

- Read the triggering GitHub issue (title/body/comments/labels).
- If the issue body contains `Repro Branch: <name>`, it will check out that branch before making changes.
- Propose a step-by-step plan and post it as a “PatchPilot Plan” issue comment.
- Create a work branch: `agent/issue-<num>-<slug>`.
- Generate a patch (unified diff) and apply it locally.
- Run repo-configured checks:
  - `ruff check .`
  - `pytest -q`
- If checks pass, commit + push the branch and open a Pull Request.
- If checks fail, attempt up to 2 repairs (3 total attempts including the initial try).

## What PatchPilot will NOT do

- Modify GitHub workflow files (anything under `.github/**`).
- Read/write secrets (`.env*`) or any paths blocked by guardrails.
- Change more than **10 files** or create diffs larger than **500 changed lines** in a single run.
- Push directly to `main`.

## Guardrails (enforced)

Machine-enforced guardrails live in:

- `agent_rules.yml`
- Loaded and enforced by `agent/guardrails/rules.py`

Allowed change targets:

- `src/**`
- `tests/**`
- `pyproject.toml`

Blocked targets:

- `.github/**`
- `**/.env*`
- `keys/**`
- `infra/**`

