from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from pathlib import PurePosixPath

from agent.config import GuardrailsConfig


class GuardrailViolation(RuntimeError):
    pass


def _matches_any(path: str, globs: list[str]) -> bool:
    # pathlib.PurePath.match has surprising edge cases with "**" depending on pattern shape.
    # Use fnmatch against POSIX-style paths for predictable repo-glob behavior.
    p = PurePosixPath(path).as_posix()
    return any(fnmatch.fnmatchcase(p, g) for g in globs)


@dataclass(frozen=True)
class DiffStats:
    files: list[str]
    changed_lines: int


def parse_unified_diff(diff_text: str) -> DiffStats:
    files: list[str] = []
    changed = 0
    current_file: str | None = None
    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            # diff --git a/foo b/foo
            parts = line.split()
            if len(parts) >= 4 and parts[3].startswith("b/"):
                current_file = parts[3][2:]
                files.append(current_file)
        elif line.startswith("+++ "):
            # +++ b/foo OR +++ foo (some generators omit the prefix)
            path = line[len("+++ ") :].strip()
            if path == "/dev/null":
                current_file = None
                continue
            if path.startswith("b/"):
                path = path[2:]
            current_file = path
            if current_file and current_file not in files:
                files.append(current_file)
        elif line.startswith("--- "):
            # fallback: --- a/foo OR --- foo (if +++ is missing/odd)
            path = line[len("--- ") :].strip()
            if path == "/dev/null":
                continue
            if path.startswith("a/"):
                path = path[2:]
            if path and path not in files:
                files.append(path)
        elif (line.startswith("+") and not line.startswith("+++")) or (
            line.startswith("-") and not line.startswith("---")
        ):
            changed += 1
    # de-dupe stable order
    dedup: list[str] = []
    seen = set()
    for f in files:
        if f not in seen:
            seen.add(f)
            dedup.append(f)
    return DiffStats(files=dedup, changed_lines=changed)


@dataclass(frozen=True)
class Guardrails:
    cfg: GuardrailsConfig

    def validate_paths(self, paths: list[str]) -> None:
        for p in paths:
            if _matches_any(p, self.cfg.blocked_paths):
                raise GuardrailViolation(f"Blocked path modified: {p}")
            if not _matches_any(p, self.cfg.allowed_paths):
                raise GuardrailViolation(f"Path not in allow-list: {p}")

    def validate_diff(self, diff_text: str) -> DiffStats:
        if not diff_text.strip():
            raise GuardrailViolation("Empty diff")
        stats = parse_unified_diff(diff_text)
        if not stats.files:
            raise GuardrailViolation("Could not determine changed files from diff")
        if len(stats.files) > self.cfg.max_files_changed:
            raise GuardrailViolation(
                f"Too many files changed ({len(stats.files)} > {self.cfg.max_files_changed})"
            )
        if stats.changed_lines > self.cfg.max_diff_lines:
            raise GuardrailViolation(
                f"Diff too large ({stats.changed_lines} lines > {self.cfg.max_diff_lines})"
            )
        self.validate_paths(stats.files)
        return stats

