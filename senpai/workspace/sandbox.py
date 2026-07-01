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
    import os
    root = workspace_root()
    if not root.is_dir():
        return []
    
    out: list[Path] = []
    # `generated` is our own machine output (config.GENERATED_DIR): excluding it stops
    # a just-generated deck/doc from feeding back as "grounding" into the next one.
    ignore_dirs = {".git", "node_modules", ".venv", "venv", ".next", "__pycache__",
                   "dist", "generated"}
    
    for dirpath, dirnames, filenames in os.walk(root):
        # Prune ignored directories in-place so os.walk doesn't descend into them
        dirnames[:] = [d for d in dirnames if d not in ignore_dirs and not d.startswith(".")]
        
        dp = Path(dirpath)
        for f in filenames:
            p = dp / f
            try:
                if is_allowed(p) and safe_path(p):
                    out.append(p)
            except SandboxError:
                continue
    return out


def move_within(src: str | Path, dst_rel: str | Path) -> str:
    """Move a file to `dst_rel` (relative to the root), both sandbox-checked. Never
    overwrites (raises SandboxError on collision), never leaves the root, creates the
    destination folder. Returns the new path relative to the root. This is the only
    move primitive — organize/tidy go through it, so a reorganize can't clobber a file
    or escape the workspace."""
    import shutil
    s = safe_path(src)
    if not s.is_file():
        raise SandboxError(f"source is not a file: {src!r}")
    d = safe_path(dst_rel)
    if d.exists():
        raise SandboxError(f"destination already exists: {dst_rel!r}")
    d.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(s), str(d))
    return rel(d)


def rel(path: Path) -> str:
    """Path relative to the root, for human-readable citations (`file://<rel>`)."""
    try:
        resolved = path.resolve()
        root = workspace_root()
        if root in resolved.parents or root == resolved:
            return str(resolved.relative_to(root))
        return str(resolved)  # Use absolute path for external files
    except (ValueError, OSError):
        return path.name
