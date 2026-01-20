from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _ts() -> str:
    # ISO-ish timestamp without extra deps
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@dataclass
class JsonLogger:
    path: Path

    def log(self, step: str, message: str, *, level: str = "info", **meta: Any) -> None:
        event = {
            "ts": _ts(),
            "level": level,
            "step": step,
            "message": message,
            "meta": meta,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")

