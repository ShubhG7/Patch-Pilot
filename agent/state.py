from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class IssueContext(BaseModel):
    title: str = ""
    body: str = ""
    comments: list[dict[str, Any]] = Field(default_factory=list)
    labels: list[str] = Field(default_factory=list)
    repro_branch: str | None = None


class CheckResult(BaseModel):
    command: list[str]
    returncode: int
    stdout: str
    stderr: str


class AgentState(BaseModel):
    repo_full_name: str
    repo_owner: str
    repo_name: str
    issue_number: int

    issue: IssueContext = Field(default_factory=IssueContext)

    branch_name: str | None = None
    attempt: int = 1
    max_attempts: int = 3

    selected_files: list[str] = Field(default_factory=list)
    file_context: dict[str, str] = Field(default_factory=dict)

    plan_text: str | None = None
    diff_text: str | None = None

    lint_result: CheckResult | None = None
    test_result: CheckResult | None = None
    checks_passed: bool = False

    pr_url: str | None = None

    log_path: str = "patchpilot_logs.jsonl"
    run_summary: dict[str, Any] = Field(default_factory=dict)
    failure_reason: str | None = None

