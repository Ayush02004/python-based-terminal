#!/usr/bin/env python3
"""terminal.py — sandboxed terminal

Usage:
    python terminal.py

This starts a simple single-user CLI that operates only inside the `workspace` folder.
"""

import os
import sys
import shlex
import shutil
import logging
import datetime
from pathlib import Path

# readline availability (Unix). On Windows it may be missing — graceful fallback provided.
try:
    import readline
except Exception:
    readline = None

# psutil is optional — monitor command will inform user if it's not installed.
try:
    import psutil
except Exception:
    psutil = None

# Configuration
SANDBOX_DIR_NAME = "workspace"
LOGS_DIR = "logs"
LOG_FILE = os.path.join(LOGS_DIR, "commands.log")
PROMPT_TEMPLATE = "sandbox:{cwd}$ "

# Supported commands
COMMANDS = ["ls", "cd", "pwd", "mkdir", "rm", "monitor", "ps", "help", "exit", "quit"]


class SandboxError(Exception):
    pass


class Terminal:
    def __init__(self, base_dir: str = SANDBOX_DIR_NAME):
        self.repo_root = Path.cwd()
        self.sandbox_root = (self.repo_root / base_dir).resolve()
        self.cwd = self.sandbox_root  # session's current working directory (Path)
        self._ensure_sandbox_exists()
        self._configure_logging()
        if readline:
            self._configure_readline()

    def _ensure_sandbox_exists(self):
        self.sandbox_root.mkdir(parents=True, exist_ok=True)

    def _configure_logging(self):
        Path(LOGS_DIR).mkdir(exist_ok=True)
        logging.basicConfig(
            filename=LOG_FILE,
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(message)s",
        )
        logging.getLogger().addHandler(logging.StreamHandler(stream=sys.stderr))

    def _log(self, level: str, message: str):
        if level.lower() == "info":
            logging.info(message)
        elif level.lower() == "warning":
            logging.warning(message)
        elif level.lower() == "error":
            logging.error(message)
        else:
            logging.debug(message)

    def _configure_readline(self):
        # Basic completion: commands and file paths
        readline.set_completer_delims(" \t\n")
        try:
            readline.parse_and_bind("tab: complete")
        except Exception:
            # Some platforms require different bind; ignore if fails
            pass
        readline.set_completer(self._completer)

    def _completer(self, text, state):
        # Provide completion for first token (commands) and file paths for later tokens.
        try:
            buf = readline.get_line_buffer()
        except Exception:
            buf = ""
        tokens = shlex.split(buf) if buf.strip() else []
        # if we're at first token -> suggest commands
        if len(tokens) == 0 or (buf.endswith(" ") and not text):
            # starting new token: suggest commands + files
            options = [c for c in COMMANDS if c.startswith(text)]
            # add file completions
            options += self._path_completions(text)
        elif len(tokens) == 1:
            # still first token: command completion
            options = [c for c in COMMANDS if c.startswith(tokens[0])]
        else:
            # path completion for subsequent tokens
            options = self._path_completions(text)
        options = sorted(set(options))
        return options[state] if state < len(options) else None

    def _path_completions(self, text):
        # Return completions for file paths relative to current cwd
        try:
            base = text or "."
            path = (self.cwd / base) if not Path(base).is_absolute() else Path(base)
            parent = path.parent if path.exists() else path.parent
            candidates = []
            try:
                for p in parent.iterdir():
                    if p.name.startswith(path.name):
                        rel = str(p.relative_to(self.cwd)) if self.cwd in p.parents or p == self.cwd else str(p)
                        if p.is_dir():
                            candidates.append(rel + os.sep)
                        else:
                            candidates.append(rel)
            except Exception:
                # if parent doesn't exist, no completions
                pass
            return candidates
        except Exception:
            return []

    # ---------------- Security helpers ----------------
    def _resolve_read_path(self, target: str) -> Path:
        """Resolve a path for read operations. Accepts relative and absolute.
        Ensures the resolved path is inside the sandbox root.
        """
        p = Path(target)
        if not p.is_absolute():
            candidate = (self.cwd / p).resolve(strict=False)
        else:
            candidate = p.resolve(strict=False)
        try:
            # ensure candidate is within sandbox
            candidate.relative_to(self.sandbox_root)
        except Exception:
            raise SandboxError(f"Access denied: path escapes sandbox: {target}")
        return candidate

    def _resolve_write_path(self, target: str) -> Path:
        """Resolve a path for write/create operations.
        Ensures that the parent directory is inside the sandbox.
        """
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

    # ---------------- Command implementations ----------------
    def cmd_ls(self, args):
        """ls [path] — list directory contents."""
        path = args[0] if args else "."
        try:
            target = self._resolve_read_path(path)
        except SandboxError as e:
            self._log("warning", str(e))
            print(str(e))
            return
        if not target.exists():
            print(f"ls: cannot access '{path}': No such file or directory")
            return
        if target.is_file():
            print(target.name)
            return
        # it's a directory
        try:
            entries = sorted(target.iterdir(), key=lambda p: p.name.lower())
            for e in entries:
                suffix = "/" if e.is_dir() else ""
                print(e.name + suffix)
        except PermissionError:
            print(f"ls: cannot open directory '{path}': Permission denied")

    def cmd_pwd(self, args):
        """pwd — print current working directory (sandbox-relative)."""
        try:
            rel = self.cwd.relative_to(self.sandbox_root)
            print("/" + str(rel) if str(rel) != "." else "/")
        except Exception:
            # fallback absolute (shouldn't happen)
            print(str(self.cwd))

    def cmd_cd(self, args):
        """cd [path] — change session directory (within sandbox)."""
        if not args:
            # default to sandbox root
            target_path = self.sandbox_root
        else:
            target_arg = args[0]
            try:
                candidate = self._resolve_read_path(target_arg)
            except SandboxError as e:
                self._log("warning", str(e))
                print(str(e))
                return
            target_path = candidate
        if not target_path.exists() or not target_path.is_dir():
            print(f"cd: no such directory: {target_path}")
            return
        # set session cwd
        self.cwd = target_path
        # print nothing on success

    def cmd_mkdir(self, args):
        """mkdir <dir> — create directory (parents not created unless -p used)."""
        if not args:
            print("mkdir: missing operand")
            return
        flags = [a for a in args if a.startswith("-")]
        nonflags = [a for a in args if not a.startswith("-")]
        path = nonflags[0] if nonflags else None
        if not path:
            print("mkdir: missing operand")
            return
        # support -p to create parents
        recursive = "-p" in flags
        try:
            target = self._resolve_write_path(path)
        except SandboxError as e:
            self._log("warning", str(e))
            print(str(e))
            return
        try:
            if recursive:
                Path(target).mkdir(parents=True, exist_ok=True)
            else:
                Path(target).mkdir(exist_ok=False)
        except FileExistsError:
            print(f"mkdir: cannot create directory '{path}': File exists")
        except PermissionError:
            print(f"mkdir: cannot create directory '{path}': Permission denied")
        except Exception as e:
            print(f"mkdir: error creating '{path}': {e}")

    def cmd_rm(self, args):
        """rm [-r] <path> — remove file or directory (dir requires -r)."""
        if not args:
            print("rm: missing operand")
            return
        flags = [a for a in args if a.startswith("-")]
        nonflags = [a for a in args if not a.startswith("-")]
        path = nonflags[0] if nonflags else None
        if not path:
            print("rm: missing operand")
            return
        try:
            target = self._resolve_read_path(path)
        except SandboxError as e:
            self._log("warning", str(e))
            print(str(e))
            return
        if not target.exists():
            print(f"rm: cannot remove '{path}': No such file or directory")
            return
        try:
            if target.is_file():
                target.unlink()
            elif target.is_dir():
                if "-r" in flags or "-rf" in flags or "-fr" in flags:
                    shutil.rmtree(target)
                else:
                    print(f"rm: cannot remove '{path}': Is a directory (use -r)")
            else:
                # fallback
                target.unlink()
        except PermissionError:
            print(f"rm: cannot remove '{path}': Permission denied")
        except Exception as e:
            print(f"rm: error removing '{path}': {e}")

    def cmd_monitor(self, args):
        """monitor / ps — show basic CPU/memory and top processes (requires psutil)."""
        if psutil is None:
            print("monitor: psutil not installed. Install it with: pip install psutil")
            return
        # CPU & memory
        cpu = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()
        print(f"CPU: {cpu:.1f}%  |  Memory: {mem.percent:.1f}% ({mem.used // (1024**2)}MB / {mem.total // (1024**2)}MB)")
        # Top processes by CPU (top 5)
        procs = []
        for p in psutil.process_iter(attrs=["pid", "name", "cpu_percent", "memory_percent"]):
            info = p.info
            procs.append(info)
        procs = sorted(procs, key=lambda x: x.get("cpu_percent", 0), reverse=True)[:8]
        print(f"\nTop processes (by CPU%):")
        print("{:<6} {:<25} {:>6} {:>7}".format("PID", "NAME", "CPU%", "MEM%"))
        for i in procs:
            print("{:<6} {:<25} {:>6.1f} {:>7.2f}".format(i["pid"], (i["name"] or "")[:24], i.get("cpu_percent", 0.0), i.get("memory_percent", 0.0)))

    def cmd_help(self, args):
        print("Supported commands:")
        print("  ls [path]          - list files and directories")
        print("  cd [path]          - change directory (sandbox only)")
        print("  pwd                - print current sandbox-relative directory")
        print("  mkdir [-p] <dir>   - make directory (use -p to create parents)")
        print("  rm [-r] <path>     - remove file or directory (directory needs -r)")
        print("  monitor | ps       - show CPU/memory and top processes (psutil optional)")
        print("  help               - show this help")
        print("  exit / quit        - exit the terminal")

    # ---------------- Core loop ----------------
    def execute(self, line: str):
        line = line.strip()
        if not line:
            return
        # log
        self._log("info", f"CMD: {line} | cwd: {self.cwd}")
        try:
            tokens = shlex.split(line)
        except Exception:
            print("Parse error: invalid quoting or tokenization")
            return
        cmd = tokens[0]
        args = tokens[1:]
        if cmd == "ls":
            self.cmd_ls(args)
        elif cmd == "pwd":
            self.cmd_pwd(args)
        elif cmd == "cd":
            self.cmd_cd(args)
        elif cmd == "mkdir":
            self.cmd_mkdir(args)
        elif cmd == "rm":
            self.cmd_rm(args)
        elif cmd in ("monitor", "ps"):
            self.cmd_monitor(args)
        elif cmd in ("help", "?"):
            self.cmd_help(args)
        elif cmd in ("exit", "quit"):
            print("Exiting.")
            raise EOFError
        else:
            print(f"Unknown command: {cmd}. Type 'help' for a list of supported commands.")

    def run(self):
        # Welcome banner
        print("Sandboxed Python Terminal")
        print(f"Sandbox root: {self.sandbox_root}")
        print("All operations are restricted to the sandbox root.")
        print("Type 'help' for commands.")
        while True:
            try:
                prompt = PROMPT_TEMPLATE.format(cwd=str(self._short_cwd()))
                if readline:
                    line = input(prompt)
                else:
                    # fallback
                    line = input(prompt)
                try:
                    self.execute(line)
                except SandboxError as se:
                    self._log("warning", str(se))
                    print(str(se))
                except EOFError:
                    break
                except Exception as e:
                    self._log("error", f"Unhandled error: {e}")
                    print(f"Error: {e}")
            except (KeyboardInterrupt, EOFError):
                print("\nExiting.")
                break

    def _short_cwd(self):
        """Return a short representation of cwd relative to sandbox root (for the prompt)."""
        try:
            rel = self.cwd.relative_to(self.sandbox_root)
            return "/" if str(rel) == "." else f"/{rel}"
        except Exception:
            return str(self.cwd)


def main():
    term = Terminal()
    term.run()


if __name__ == "__main__":
    main()
