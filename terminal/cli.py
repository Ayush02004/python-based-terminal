# terminal/cli.py
import shlex
from pathlib import Path
try:
    import readline
except Exception:
    readline = None

from .sandbox import SandboxManager, SandboxError
from .commands import CommandsExecutor
from .utils import configure_file_logging, log_info, expand_args_with_glob, to_sandbox_posix

COMMANDS_LIST = [
    "ls","cd","pwd","mkdir","rm","touch","cat","echo","cp","mv",
    "head","tail","stat","chmod","find","grep","monitor","ps",
    "help","exit","quit"
]

class TerminalCLI:
    def __init__(self, base_dir: str = "sandbox"):
        configure_file_logging()
        self.sandbox = SandboxManager(base_dir=base_dir)
        self.executor = CommandsExecutor(self.sandbox)
        if readline:
            self._configure_readline()

    def _configure_readline(self):
        readline.set_completer_delims(" \t\n")
        try:
            readline.parse_and_bind("tab: complete")
        except Exception:
            pass
        readline.set_completer(self._completer)

    def _completer(self, text, state):
        try:
            buf = readline.get_line_buffer()
        except Exception:
            buf = ""
        try:
            tokens = shlex.split(buf) if buf.strip() else []
        except Exception:
            tokens = buf.split()
        if len(tokens) <= 1:
            options = [c for c in COMMANDS_LIST if c.startswith(text)]
            options += self._path_completions(text)
        else:
            options = self._path_completions(text)
        options = sorted(set(options))
        return options[state] if state < len(options) else None

    def _path_completions(self, text):
        base = text or "."
        path = (self.sandbox.cwd / base) if not Path(base).is_absolute() else Path(base)
        parent = path.parent if path.exists() else path.parent
        candidates = []
        try:
            for p in parent.iterdir():
                if p.name.startswith(path.name):
                    rel = str(p.relative_to(self.sandbox.cwd))
                    if p.is_dir():
                        candidates.append(rel + "/")
                    else:
                        candidates.append(rel)
        except Exception:
            pass
        return candidates

    def _short_prompt(self) -> str:
        try:
            rel = self.sandbox.cwd.relative_to(self.sandbox.sandbox_root)
            return "/" if str(rel) == "." else "/" + rel.as_posix()
        except Exception:
            return self.sandbox.cwd.as_posix()

    def execute_line(self, line: str):
        if not line.strip():
            return
        log_info(f"CMD: {line} | cwd: {self.sandbox.cwd}")
        try:
            tokens = shlex.split(line)
        except Exception:
            print("Parse error: invalid quoting or tokenization")
            return
        cmd = tokens[0]
        raw_args = tokens[1:]
        # expand globs (returns absolute paths for matches)
        args = expand_args_with_glob(raw_args, self.sandbox.cwd, self.sandbox.sandbox_root)
        # dispatch to executor methods (safe mapping)
        mapping = {
            "ls": self.executor.ls,
            "pwd": self.executor.pwd,
            "cd": self.executor.cd,
            "mkdir": self.executor.mkdir,
            "rm": self.executor.rm,
            "touch": self.executor.touch,
            "cat": self.executor.cat,
            "echo": self.executor.echo,
            "cp": self.executor.cp,
            "mv": self.executor.mv,
            "head": self.executor.head,
            "tail": self.executor.tail,
            "stat": self.executor.stat,
            "chmod": self.executor.chmod,
            "find": self.executor.find,
            "grep": self.executor.grep,
            "monitor": self.executor.monitor,
            "ps": self.executor.monitor,
            "help": self.executor.help,
        }
        try:
            if cmd in ("exit", "quit"):
                raise EOFError
            func = mapping.get(cmd)
            if func:
                func(args)
            else:
                print(f"Unknown command: {cmd}. Type 'help'.")
        except SandboxError as se:
            print(se)

    def run(self):
        print("Sandboxed Python Terminal")
        print(f"Sandbox root: {self.sandbox.sandbox_root.as_posix()}")
        print("All operations restricted to sandbox. Type 'help'.")
        while True:
            try:
                prompt = f"sandbox:{self._short_prompt()}$ "
                if readline:
                    line = input(prompt)
                else:
                    line = input(prompt)
                try:
                    self.execute_line(line)
                except EOFError:
                    break
            except (KeyboardInterrupt, EOFError):
                print("\nExiting.")
                break
