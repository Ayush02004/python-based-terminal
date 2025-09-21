# terminal/sandbox.py
from pathlib import Path

class SandboxError(Exception):
    pass

class SandboxManager:
    """Manage sandbox root and safe path resolution."""

    def __init__(self, base_dir: str = "workspace"):
        self.repo_root = Path.cwd()
        self.sandbox_root = (self.repo_root / base_dir).resolve()
        self._ensure_sandbox_exists()
        # session cwd starts at sandbox root
        self.cwd = self.sandbox_root

    def _ensure_sandbox_exists(self):
        self.sandbox_root.mkdir(parents=True, exist_ok=True)

    def set_cwd(self, new_cwd: Path):
        """Set the session cwd (assumes new_cwd was validated)."""
        self.cwd = new_cwd

    def resolve_read(self, target: str) -> Path:
        """Resolve path for read operations; must be inside sandbox."""
        p = Path(target)
        if not p.is_absolute():
            candidate = (self.cwd / p).resolve(strict=False)
        else:
            candidate = p.resolve(strict=False)
        try:
            candidate.relative_to(self.sandbox_root)
        except Exception:
            raise SandboxError(f"Access denied: path escapes sandbox: {target}")
        return candidate

    def resolve_write(self, target: str) -> Path:
        """Resolve path for write/create; parent directory must be inside sandbox."""
        p = Path(target)
        if not p.is_absolute():
            candidate = (self.cwd / p)
        else:
            candidate = p
        parent = candidate.parent.resolve(strict=False)
        try:
            parent.relative_to(self.sandbox_root)
        except Exception:
            raise SandboxError(f"Access denied: path escapes sandbox (parent): {target}")
        return (self.cwd / target) if not p.is_absolute() else candidate
