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
        print("Type 'help' for supported commands (same as earlier).")
