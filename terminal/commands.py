# terminal/commands.py
import os
import shutil
from pathlib import Path
from stat import filemode
from datetime import datetime
import re
try:
    import psutil
except Exception:
    psutil = None

from .sandbox import SandboxError, SandboxManager
from .utils import to_sandbox_posix

class CommandsExecutor:
    """Implements filesystem and monitoring commands using SandboxManager."""

    def __init__(self, sandbox: SandboxManager):
        self.sandbox = sandbox

    # ---------- Basic FS ops ----------
    def ls(self, args):
        path = args[0] if args else "."
        target = self.sandbox.resolve_read(path)
        if not target.exists():
            print(f"ls: cannot access '{path}': No such file or directory")
            return
        if target.is_file():
            print(target.name)
            return
        entries = sorted(target.iterdir(), key=lambda p: p.name.lower())
        for e in entries:
            suffix = "/" if e.is_dir() else ""
            print(e.name + suffix)

    def pwd(self, args):
        rel = self.sandbox.cwd.relative_to(self.sandbox.sandbox_root)
        print("/" if str(rel) == "." else "/" + rel.as_posix())

    def cd(self, args):
        if not args:
            target = self.sandbox.sandbox_root
        else:
            target = self.sandbox.resolve_read(args[0])
        if not target.exists() or not target.is_dir():
            print(f"cd: no such directory: {to_sandbox_posix(target, self.sandbox.sandbox_root)}")
            return
        self.sandbox.set_cwd(target)

    def mkdir(self, args):
        if not args:
            print("mkdir: missing operand")
            return
        flags = [a for a in args if a.startswith("-")]
        nonflags = [a for a in args if not a.startswith("-")]
        path = nonflags[0]
        recursive = "-p" in flags
        target = self.sandbox.resolve_write(path)
        try:
            if recursive:
                Path(target).mkdir(parents=True, exist_ok=True)
            else:
                Path(target).mkdir(exist_ok=False)
        except FileExistsError:
            print(f"mkdir: cannot create directory '{path}': File exists")
        except PermissionError:
            print(f"mkdir: cannot create directory '{path}': Permission denied")

    def rm(self, args):
        if not args:
            print("rm: missing operand")
            return
        flags = [a for a in args if a.startswith("-")]
        path = [a for a in args if not a.startswith("-")][0]
        target = self.sandbox.resolve_read(path)
        if not target.exists():
            print(f"rm: cannot remove '{to_sandbox_posix(target, self.sandbox.sandbox_root)}': No such file or directory")
            return
        if target.is_file():
            target.unlink()
        elif target.is_dir():
            if any(f in flags for f in ("-r", "-rf", "-fr")):
                shutil.rmtree(target)
            else:
                print(f"rm: cannot remove '{to_sandbox_posix(target, self.sandbox.sandbox_root)}': Is a directory (use -r)")

    def touch(self, args):
        if not args:
            print("touch: missing file operand")
            return
        for a in args:
            try:
                target = self.sandbox.resolve_write(a)
                p = Path(target)
                if p.exists():
                    os.utime(p, None)
                else:
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.touch()
            except SandboxError as e:
                print(e)

    def cat(self, args):
        if not args:
            print("cat: missing file operand")
            return
        for a in args:
            try:
                target = self.sandbox.resolve_read(a)
                if not target.exists() or not target.is_file():
                    print(f"cat: {to_sandbox_posix(target, self.sandbox.sandbox_root)}: No such file")
                    continue
                size = target.stat().st_size
                if size > 100 * 1024:
                    print(f"cat: {to_sandbox_posix(target, self.sandbox.sandbox_root)}: File too large to display ({size} bytes)")
                    continue
                print(target.read_text(errors="replace"))
            except SandboxError as e:
                print(e)

    def echo(self, args):
        if not args:
            print()
            return
        if ">" in args or ">>" in args:
            if ">>" in args:
                idx = args.index(">>")
                append = True
            else:
                idx = args.index(">")
                append = False
            text = " ".join(args[:idx])
            filename = args[idx+1] if len(args) > idx+1 else None
            if not filename:
                print("echo: no file specified for redirection")
                return
            target = self.sandbox.resolve_write(filename)
            mode = "a" if append else "w"
            with open(target, mode, encoding="utf-8") as f:
                f.write(text + "\n")
        else:
            print(" ".join(args))

    # ---------- Copy / Move ----------
    def cp(self, args):
        if len(args) < 2:
            print("cp: missing operand")
            return
        srcs = args[:-1]
        dest = args[-1]
        dest_target = self.sandbox.resolve_write(dest)
        dest_p = Path(dest_target)
        if len(srcs) > 1:
            if not dest_p.exists() or not dest_p.is_dir():
                print(f"cp: target '{to_sandbox_posix(dest_p, self.sandbox.sandbox_root)}' is not a directory")
                return
            for s in srcs:
                s_path = self.sandbox.resolve_read(s)
                if s_path.is_file():
                    shutil.copy2(s_path, dest_p / s_path.name)
        else:
            s_path = self.sandbox.resolve_read(srcs[0])
            if s_path.is_dir():
                print(f"cp: -r not specified; omitting directory '{to_sandbox_posix(s_path, self.sandbox.sandbox_root)}'")
                return
            if dest_p.exists() and dest_p.is_dir():
                shutil.copy2(s_path, dest_p / s_path.name)
            else:
                shutil.copy2(s_path, dest_p)

    def mv(self, args):
        if len(args) < 2:
            print("mv: missing operand")
            return
        srcs = args[:-1]
        dest = args[-1]
        dest_target = self.sandbox.resolve_write(dest)
        dest_p = Path(dest_target)
        if len(srcs) > 1:
            if not dest_p.exists() or not dest_p.is_dir():
                print("mv: when moving multiple files, destination must be an existing directory")
                return
            for s in srcs:
                s_path = self.sandbox.resolve_read(s)
                shutil.move(str(s_path), str(dest_p / s_path.name))
        else:
            s_path = self.sandbox.resolve_read(srcs[0])
            if dest_p.exists() and dest_p.is_dir():
                shutil.move(str(s_path), str(dest_p / s_path.name))
            else:
                shutil.move(str(s_path), str(dest_p))

    # ---------- Text utilities ----------
    def head(self, args):
        if not args:
            print("head: missing file operand")
            return
        n = 10
        file_arg = args[0]
        if args[0].startswith("-n"):
            try:
                if args[0] != "-n":
                    n = int(args[0][2:])
                    file_arg = args[1]
                else:
                    n = int(args[1]); file_arg = args[2]
            except Exception:
                print("head: invalid option")
                return
        target = self.sandbox.resolve_read(file_arg)
        if not target.exists() or not target.is_file():
            print(f"head: {to_sandbox_posix(target, self.sandbox.sandbox_root)}: No such file")
            return
        with open(target, "r", encoding="utf-8", errors="replace") as fh:
            for i in range(n):
                line = fh.readline()
                if not line: break
                print(line.rstrip("\n"))

    def tail(self, args):
        if not args:
            print("tail: missing file operand")
            return
        n = 10
        file_arg = args[0]
        if args[0].startswith("-n"):
            try:
                if args[0] != "-n":
                    n = int(args[0][2:])
                    file_arg = args[1]
                else:
                    n = int(args[1]); file_arg = args[2]
            except Exception:
                print("tail: invalid option")
                return
        target = self.sandbox.resolve_read(file_arg)
        if not target.exists() or not target.is_file():
            print(f"tail: {to_sandbox_posix(target, self.sandbox.sandbox_root)}: No such file")
            return
        with open(target, "rb") as f:
            f.seek(0, os.SEEK_END)
            filesize = f.tell()
            blocksize = 1024
            data = b""
            lines_found = 0
            while filesize > 0 and lines_found <= n:
                read_size = min(blocksize, filesize)
                filesize -= read_size
                f.seek(filesize)
                chunk = f.read(read_size)
                data = chunk + data
                lines_found = data.count(b'\n')
            lines = data.splitlines()[-n:]
            for line in lines:
                try:
                    print(line.decode("utf-8", errors="replace"))
                except Exception:
                    print(line)

    def stat(self, args):
        if not args:
            print("stat: missing operand")
            return
        target = self.sandbox.resolve_read(args[0])
        if not target.exists():
            print(f"stat: cannot stat '{to_sandbox_posix(target, self.sandbox.sandbox_root)}': No such file or directory")
            return
        st = target.stat()
        print(f"  File: {target.name}")
        print(f"  Size: {st.st_size}")
        print(f"Device: {st.st_dev}\tInode: {st.st_ino}\tLinks: {st.st_nlink}")
        print(f"Access: ({oct(st.st_mode)[-3:]}/{filemode(st.st_mode)})")
        print(f"Uid: {st.st_uid}\tGid: {st.st_gid}")
        print(f"Access: {datetime.fromtimestamp(st.st_atime)}")
        print(f"Modify: {datetime.fromtimestamp(st.st_mtime)}")
        print(f"Change: {datetime.fromtimestamp(st.st_ctime)}")

    def chmod(self, args):
        if len(args) < 2:
            print("chmod: missing operand")
            return
        mode_str = args[0]
        path = args[1]
        target = self.sandbox.resolve_write(path)
        try:
            mode = int(mode_str, 8)
            os.chmod(target, mode)
        except ValueError:
            print("chmod: invalid mode")
        except Exception as e:
            print(f"chmod: failed to change permissions of '{to_sandbox_posix(target, self.sandbox.sandbox_root)}': {e}")

    # ---------- Search ----------
    def find(self, args):
        start = "."
        pattern = None
        if args:
            if args[0] == "-name" and len(args) >= 2:
                pattern = args[1]
            else:
                start = args[0]
                if len(args) >= 3 and args[1] == "-name":
                    pattern = args[2]
        start_path = self.sandbox.resolve_read(start)
        for root, dirs, files in os.walk(start_path):
            for name in files + dirs:
                if pattern is None or self._match(name, pattern):
                    full = Path(root) / name
                    try:
                        print(full.relative_to(self.sandbox.sandbox_root).as_posix())
                    except Exception:
                        print(full.as_posix())

    def _match(self, name, pattern):
        if pattern is None:
            return True
        import fnmatch
        return fnmatch.fnmatch(name, pattern)

    def grep(self, args):
        if not args or len(args) < 2:
            print("grep: usage: grep PATTERN FILE...")
            return
        pattern = args[0]
        files = args[1:]
        try:
            regex = re.compile(pattern)
        except re.error:
            print("grep: invalid pattern")
            return
        for f in files:
            try:
                target = self.sandbox.resolve_read(f)
            except SandboxError as e:
                print(e)
                continue
            if not target.exists() or not target.is_file():
                continue
            with open(target, "r", encoding="utf-8", errors="replace") as fh:
                for i, line in enumerate(fh, start=1):
                    if regex.search(line):
                        display = to_sandbox_posix(target, self.sandbox.sandbox_root)
                        print(f"{display}:{i}:{line.rstrip()}")

    # ---------- Monitoring ----------
    def monitor(self, args):
        if psutil is None:
            print("monitor: psutil not installed. Install with: pip install psutil")
            return
        cpu = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()
        print(f"CPU: {cpu:.1f}%  |  Memory: {mem.percent:.1f}% ({mem.used // (1024**2)}MB / {mem.total // (1024**2)}MB)")
        procs = []
        for p in psutil.process_iter(attrs=["pid", "name", "cpu_percent", "memory_percent"]):
            procs.append(p.info)
        procs = sorted(procs, key=lambda x: x.get("cpu_percent", 0), reverse=True)[:8]
        print("\nTop processes (by CPU%):")
        print("{:<6} {:<25} {:>6} {:>7}".format("PID", "NAME", "CPU%", "MEM%"))
        for i in procs:
            print("{:<6} {:<25} {:>6.1f} {:>7.2f}".format(i["pid"], (i["name"] or "")[:24], i.get("cpu_percent", 0.0), i.get("memory_percent", 0.0)))

    # ---------- Help ----------
    def help(self, args):
        """Context-sensitive help:
        - help               -> list commands with short descriptions
        - help <cmd>         -> detailed help for <cmd>
        - <cmd> --help/-h    -> handled by CLI dispatcher and calls this method
        """
        # Add near the top (after imports)
        HELP_DOCS = {
            "ls": {
                "short": "List directory contents.",
                "usage": "ls [PATH]",
                "description": "List files and directories. If PATH is a file, prints the filename. "
                            "Directories are printed with a trailing '/'.",
                "options": ["No additional options implemented; use shell globs (e.g. *.py)"],
                "examples": ["ls", "ls subdir", "ls *.py"],
                "notes": "Output uses POSIX-style paths relative to the sandbox."
            },
            "cd": {
                "short": "Change current directory (session only).",
                "usage": "cd [PATH]",
                "description": "Change the session's current working directory. Without PATH goes to sandbox root (/).",
                "options": [],
                "examples": ["cd demo/sub", "cd ..", "cd /  # go to sandbox root"],
                "notes": "Path must remain inside the sandbox; attempts to escape are rejected."
            },
            "pwd": {
                "short": "Print current working directory.",
                "usage": "pwd",
                "description": "Show current working directory, relative to sandbox root. Sandbox root = '/'.",
                "options": [],
                "examples": ["pwd"],
                "notes": ""
            },
            "mkdir": {
                "short": "Create directories.",
                "usage": "mkdir [-p] DIR",
                "description": "Create directory DIR. Use -p to create parent directories if necessary.",
                "options": ["-p : create parent directories as needed"],
                "examples": ["mkdir newdir", "mkdir -p a/b/c"],
                "notes": ""
            },
            "rm": {
                "short": "Remove file or directory.",
                "usage": "rm [-r|-rf] PATH",
                "description": "Remove a file or directory. Removing directories requires -r (or -rf).",
                "options": ["-r, -rf : remove directories recursively"],
                "examples": ["rm file.txt", "rm -r somedir"],
                "notes": "No force-only flag beyond -r; directories without -r are refused to avoid accidents."
            },
            "touch": {
                "short": "Create empty files or update timestamps.",
                "usage": "touch FILE...",
                "description": "Create empty files (or update their modification time if they exist).",
                "options": [],
                "examples": ["touch a.txt b.txt"],
                "notes": ""
            },
            "cat": {
                "short": "Print file contents.",
                "usage": "cat FILE...",
                "description": "Print contents of files to stdout. Files larger than ~100KB are not printed.",
                "options": [],
                "examples": ["cat README.md", "cat dir/a.txt dir/b.txt"],
                "notes": "Large files are blocked from printing to keep terminal responsive."
            },
            "echo": {
                "short": "Print text or redirect to a file.",
                "usage": "echo [TEXT] [> FILE | >> FILE]",
                "description": "Print TEXT to stdout. Use '>' to overwrite a file or '>>' to append.",
                "options": ["> : overwrite file", ">> : append to file"],
                "examples": ["echo hello", "echo hello > file.txt", "echo more >> file.txt"],
                "notes": ""
            },
            "cp": {
                "short": "Copy files.",
                "usage": "cp SRC... DEST",
                "description": "Copy file(s) to DEST. If multiple SRC are provided, DEST must be an existing directory.",
                "options": ["Recursive copy for directories (-r) is NOT implemented."],
                "examples": ["cp a.txt b.txt", "cp a.txt dir/"],
                "notes": "Directories are skipped unless recursive feature is added."
            },
            "mv": {
                "short": "Move/rename files.",
                "usage": "mv SRC... DEST",
                "description": "Move or rename files. For multiple SRC, DEST must be an existing directory.",
                "options": [],
                "examples": ["mv a.txt b.txt", "mv a.txt dir/"],
                "notes": ""
            },
            "head": {
                "short": "Show first lines of a file.",
                "usage": "head [-nN] FILE",
                "description": "Print the first N lines of FILE (default N=10).",
                "options": ["-nN or -n N : number of lines to print"],
                "examples": ["head file.txt", "head -n5 file.txt"],
                "notes": ""
            },
            "tail": {
                "short": "Show last lines of a file.",
                "usage": "tail [-nN] FILE",
                "description": "Print the last N lines of FILE (default N=10).",
                "options": ["-nN or -n N : number of lines to print"],
                "examples": ["tail file.txt", "tail -n20 file.txt"],
                "notes": ""
            },
            "stat": {
                "short": "Show file metadata.",
                "usage": "stat PATH",
                "description": "Display size, permissions, timestamps and other metadata for PATH.",
                "options": [],
                "examples": ["stat file.txt"],
                "notes": ""
            },
            "chmod": {
                "short": "Change file permissions (numeric).",
                "usage": "chmod MODE PATH",
                "description": "Change file permissions. MODE must be numeric (e.g. 644 or 755).",
                "options": [],
                "examples": ["chmod 644 file.txt"],
                "notes": "On Windows some permission effects may be limited."
            },
            "find": {
                "short": "Find files and directories.",
                "usage": "find [PATH] [-name PATTERN]",
                "description": "Walk directory tree starting at PATH (default '.') and optionally filter by -name PATTERN.",
                "options": ["-name PATTERN : only show entries matching PATTERN (supports globbing)"],
                "examples": ["find", "find . -name \"*.py\"", "find subdir -name test*"],
                "notes": ""
            },
            "grep": {
                "short": "Search files with a regex pattern.",
                "usage": "grep PATTERN FILE...",
                "description": "Search FILE(s) for PATTERN (Python regular expressions) and print matches as file:line:content.",
                "options": [],
                "examples": ["grep TODO src/*.py", "grep \"def\\s+main\" **/*.py"],
                "notes": "Use quotes for patterns containing spaces or shell metacharacters."
            },
            "monitor": {
                "short": "Show CPU/memory and top processes.",
                "usage": "monitor | ps",
                "description": "Display system CPU% and memory% and the top processes by CPU usage.",
                "options": [],
                "examples": ["monitor", "ps"],
                "notes": "Requires psutil for full results. Install with: pip install psutil"
            },
            "help": {
                "short": "Show help (this reference).",
                "usage": "help [COMMAND]",
                "description": "Show a list of commands when run without arguments, or detailed help for COMMAND when provided.",
                "options": [],
                "examples": ["help", "help ls"],
                "notes": "Also supported: '<command> --help' or '<command> -h' to show that command's help."
            },
            "exit": {
                "short": "Exit the terminal.",
                "usage": "exit | quit",
                "description": "Terminate the terminal session.",
                "options": [],
                "examples": ["exit"],
                "notes": ""
            },
        }

        # If no args: show compact list
        if not args:
            print("Available commands (type 'help <command>' for details):\n")
            # Print commands in columns: name + short desc
            names = sorted(HELP_DOCS.keys())
            maxlen = max(len(n) for n in names)
            for n in names:
                short = HELP_DOCS.get(n, {}).get("short", "")
                print(f"  {n.ljust(maxlen)}  - {short}")
            return

        # If args provided, show detailed help for each requested command
        for cmd in args:
            doc = HELP_DOCS.get(cmd)
            if doc is None:
                print(f"No help entry for '{cmd}'. Type 'help' to see available commands.")
                continue

            print(f"\n{cmd}  -  {doc.get('short','')}")
            print(f"Usage: {doc.get('usage','')}")
            if doc.get("description"):
                print("\nDescription:")
                for line in doc["description"].splitlines():
                    print("  " + line)
            if doc.get("options"):
                if doc["options"]:
                    print("\nOptions:")
                    for opt in doc["options"]:
                        print("  " + opt)
            if doc.get("examples"):
                print("\nExamples:")
                for ex in doc["examples"]:
                    print("  " + ex)
            if doc.get("notes"):
                print("\nNotes:")
                for line in str(doc["notes"]).splitlines():
                    print("  " + line)
        print("")  # final newline for spacing
