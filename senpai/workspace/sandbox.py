"""The sandbox: every path the Workspace touches is validated here.

One rule — a path is only usable if, fully resolved (symlinks included), it stays
inside `config.WORKSPACE_ROOT`. This is the single choke point; capabilities never
open a path they didn't get back from `list_documents` / `safe_path`, so there is
no way to read `../../etc/passwd` or follow a symlink out of the root.
"""
from __future__ import annotations

from pathlib import Path

from senpai import config


class SandboxError(Exception):
    """A path escaped the workspace root, or the root is unusable."""


def workspace_root() -> Path:
    """The resolved sandbox root (re-read each call so tests can monkeypatch config)."""
    return Path(config.WORKSPACE_ROOT).resolve()


def safe_path(candidate: str | Path) -> Path:
    """Resolve `candidate` (absolute, or relative to the root) and guarantee it stays
    inside the sandbox. Raises SandboxError otherwise. Does NOT require existence."""
    root = workspace_root()
    p = Path(candidate)
    full = (p if p.is_absolute() else root / p).resolve()
    if full != root and root not in full.parents:
        raise SandboxError(f"path escapes workspace root: {candidate!r}")
    return full


def is_allowed(path: Path) -> bool:
    """A real, non-hidden, allowed-extension file within the size cap."""
    try:
        if not path.is_file() or path.name.startswith("."):
            return False
        if path.suffix.lower() not in config.WORKSPACE_EXTS:
            return False
        return path.stat().st_size <= config.WORKSPACE_MAX_BYTES
    except OSError:
        return False


def list_documents() -> list[Path]:
    """Every allowed document under the sandbox root (recursive). Empty list when the
    root does not exist — a missing workspace degrades, never raises."""
    root = workspace_root()
    if not root.is_dir():
        return []
    out: list[Path] = []
    for p in root.rglob("*"):
        # rglob can surface symlinked paths; re-validate each against the root.
        try:
            if is_allowed(p) and safe_path(p):
                out.append(p)
        except SandboxError:
            continue
    return out


def rel(path: Path) -> str:
    """Path relative to the root, for human-readable citations (`file://<rel>`)."""
    try:
        return str(path.resolve().relative_to(workspace_root()))
    except (ValueError, OSError):
        return path.name
