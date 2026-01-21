from __future__ import annotations

import contextlib
import re
from dataclasses import dataclass
from pathlib import Path

from agent.tools.runner import RunResult, run_cmd


@dataclass(frozen=True)
class RepoTools:
    repo_root: Path

    def read_text(self, rel_path: str, *, max_bytes: int = 6000) -> str:
        p = self.repo_root / rel_path
        data = p.read_bytes()
        if len(data) > max_bytes:
            data = data[:max_bytes] + b"\n...<truncated>...\n"
        return data.decode("utf-8", errors="replace")

    def write_text(self, rel_path: str, content: str) -> None:
        p = self.repo_root / rel_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")

    def search(self, root_rel: str, query: str, *, limit: int = 25) -> list[str]:
        """Very small repo search: returns up to `limit` relative file paths with a match."""
        root = (self.repo_root / root_rel).resolve()
        hits: list[str] = []
        if not root.exists():
            return hits
        q = query.strip()
        if not q:
            return hits
        for p in root.rglob("*.py"):
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if q in text:
                hits.append(str(p.relative_to(self.repo_root)))
                if len(hits) >= limit:
                    break
        return hits

    def search_regex(self, root_rel: str, pattern: str, *, limit: int = 25) -> list[str]:
        root = (self.repo_root / root_rel).resolve()
        hits: list[str] = []
        if not root.exists():
            return hits
        rx = re.compile(pattern, flags=re.IGNORECASE)
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            if p.suffix not in {".py", ".toml", ".md", ".yml", ".yaml"}:
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if rx.search(text):
                hits.append(str(p.relative_to(self.repo_root)))
                if len(hits) >= limit:
                    break
        return hits

    def git_apply_check(self, diff_text: str) -> RunResult:
        """Validate a diff with git apply --check (does not modify working tree).
        
        Uses -C1 to be tolerant of line number mismatches (models often get these wrong).
        """
        patch_path = self.repo_root / ".patchpilot.check"
        patch_path.write_text(diff_text, encoding="utf-8")
        try:
            return run_cmd(["git", "apply", "--check", "-C1", str(patch_path)], cwd=self.repo_root)
        finally:
            with contextlib.suppress(OSError):
                patch_path.unlink(missing_ok=True)

    def git_apply(self, diff_text: str) -> RunResult:
        """Apply a diff to the working tree.
        
        Uses -C1 to be tolerant of line number mismatches (models often get these wrong).
        """
        patch_path = self.repo_root / ".patchpilot.patch"
        patch_path.write_text(diff_text, encoding="utf-8")
        try:
            check = run_cmd(["git", "apply", "--check", "-C1", str(patch_path)], cwd=self.repo_root)
            if check.returncode != 0:
                return check
            return run_cmd(["git", "apply", "-C1", str(patch_path)], cwd=self.repo_root)
        finally:
            with contextlib.suppress(OSError):
                patch_path.unlink(missing_ok=True)

    def git_diff(self) -> str:
        r = run_cmd(["git", "diff"], cwd=self.repo_root)
        return r.stdout

    def git_changed_files(self) -> list[str]:
        r = run_cmd(["git", "diff", "--name-only"], cwd=self.repo_root)
        return [line.strip() for line in r.stdout.splitlines() if line.strip()]

    def git_reset_hard(self) -> RunResult:
        return run_cmd(["git", "reset", "--hard"], cwd=self.repo_root)

    def git_clean(self) -> RunResult:
        return run_cmd(["git", "clean", "-fd"], cwd=self.repo_root)

