"""Minimal .env loader (stdlib). Real environment variables win over the file."""
import os
from pathlib import Path


def load_env(path: str | Path = Path(__file__).resolve().parents[1] / ".env") -> None:
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))