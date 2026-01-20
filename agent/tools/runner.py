from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RunResult:
    command: list[str]
    returncode: int
    stdout: str
    stderr: str


def run_cmd(command: list[str], *, cwd: Path | None = None, timeout_s: int | None = None) -> RunResult:
    proc = subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        text=True,
        capture_output=True,
        timeout=timeout_s,
        check=False,
    )
    return RunResult(
        command=command,
        returncode=proc.returncode,
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
    )

