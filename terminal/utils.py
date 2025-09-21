# terminal/utils.py
import logging
import glob
from pathlib import Path
from typing import List

LOGS_DIR = "logs"
LOG_FILE = f"{LOGS_DIR}/commands.log"

def configure_file_logging():
    Path(LOGS_DIR).mkdir(exist_ok=True)
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    # remove existing handlers
    for h in list(logger.handlers):
        logger.removeHandler(h)
    fh = logging.FileHandler(LOG_FILE)
    fh.setLevel(logging.INFO)
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(fh)

def log_info(msg: str):
    logging.getLogger().info(msg)

def expand_args_with_glob(args: List[str], cwd: Path, sandbox_root: Path) -> List[str]:
    """Expand shell-style globs (relative to session cwd). If a pattern matches files,
    return the matched absolute resolved paths. If no match when tried against cwd,
    also try matching relative to sandbox_root. If still no match, keep the original token.
    """
    expanded = []
    for a in args:
        if any(ch in a for ch in ("*", "?", "[")):
            # Try pattern relative to cwd first
            pattern1 = a if Path(a).is_absolute() else str(cwd / a)
            matches = glob.glob(pattern1, recursive=True)
            # If no matches found, try relative to sandbox root
            if not matches:
                pattern2 = a if Path(a).is_absolute() else str(sandbox_root / a)
                matches = glob.glob(pattern2, recursive=True)
            if matches:
                matches = sorted(matches)
                expanded.extend([str(Path(m).resolve()) for m in matches])
            else:
                expanded.append(a)
        else:
            expanded.append(a)
    return expanded


def to_sandbox_posix(p: Path, sandbox_root: Path) -> str:
    """Return POSIX-style path relative to sandbox_root (no leading slash),
    or absolute POSIX if not inside sandbox."""
    try:
        return p.relative_to(sandbox_root).as_posix()
    except Exception:
        return p.as_posix()
