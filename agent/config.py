from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class AgentCommands:
    lint: list[str]
    test: list[str]
    format: list[str] | None = None


@dataclass(frozen=True)
class AgentConfig:
    commands: AgentCommands
    context: dict[str, Any]


@dataclass(frozen=True)
class GuardrailsConfig:
    allowed_paths: list[str]
    blocked_paths: list[str]
    max_files_changed: int
    max_diff_lines: int
    max_attempts: int


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(str(path))
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Expected mapping YAML in {path}")
    return data


def load_agent_config(repo_root: Path) -> AgentConfig:
    data = _load_yaml(repo_root / "agent_config.yml")
    cmds = data.get("commands", {}) or {}
    commands = AgentCommands(
        lint=list(cmds.get("lint", [])),
        test=list(cmds.get("test", [])),
        format=list(cmds["format"]) if "format" in cmds and cmds["format"] else None,
    )
    context = data.get("context", {}) or {}
    return AgentConfig(commands=commands, context=context)


def load_guardrails(repo_root: Path) -> GuardrailsConfig:
    data = _load_yaml(repo_root / "agent_rules.yml")
    g = data.get("guardrails", {}) or {}
    return GuardrailsConfig(
        allowed_paths=list(g.get("allowed_paths", [])),
        blocked_paths=list(g.get("blocked_paths", [])),
        max_files_changed=int(g.get("max_files_changed", 10)),
        max_diff_lines=int(g.get("max_diff_lines", 500)),
        max_attempts=int(g.get("max_attempts", 3)),
    )

