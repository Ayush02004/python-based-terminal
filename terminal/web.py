# terminal/web.py
import os
import pty
import asyncio
import json
import struct
import fcntl
import termios
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse

HERE = Path(__file__).parent
TEMPLATES = HERE / "templates"
INDEX_HTML = TEMPLATES / "index.html"

app = FastAPI()


@app.get("/")
async def index(request: Request):
    return HTMLResponse(INDEX_HTML.read_text())


@app.websocket("/ws")
async def websocket_pty(ws: WebSocket):
    """
    Accept a websocket, spawn `python main.py` in a PTY, and shuttle bytes back and forth.
    This uses loop.add_reader on the master fd (Unix only). It also accepts resize
    messages from the client in the form: {"type":"resize","cols":N,"rows":M}
    """
    await ws.accept()
    loop = asyncio.get_running_loop()

    # Fork a pty and run the Python terminal in the child.
    try:
        pid, master_fd = pty.fork()
    except Exception as e:
        # Unable to fork pty (platform issue)
        await ws.close(code=1011)
        return

    if pid == 0:
        # child process: replace with python main.py
        os.execvpe("python", ["python", "main.py"], os.environ)
        return

    # Parent continues here

    async def _send_bytes(data: bytes):
        try:
            await ws.send_bytes(data)
        except Exception:
            # websocket may be closed concurrently
            pass

    def _read_pty():
        """Called by the event loop when master_fd is readable; schedule a send to websocket."""
        try:
            data = os.read(master_fd, 4096)
            if not data:
                # EOF from child
                asyncio.create_task(ws.close())
                return
            asyncio.create_task(_send_bytes(data))
        except Exception:
            # ignore read errors (ws may be closed)
            pass

    # register reader callback
    loop.add_reader(master_fd, _read_pty)

    try:
        while True:
            msg = await ws.receive()
            mtype = msg.get("type")
            if mtype == "websocket.receive":
                # text messages (keystrokes or resize JSON) or bytes
                text = msg.get("text")
                if text is not None:
                    # Check if client sent JSON (resize) — otherwise treat as keystrokes.
                    s = text.strip()
                    if s.startswith("{"):
                        try:
                            j = json.loads(text)
                            if isinstance(j, dict) and j.get("type") == "resize":
                                # apply terminal window size to PTY
                                rows = int(j.get("rows", 24))
                                cols = int(j.get("cols", 80))
                                try:
                                    # TIOCSWINSZ expects (rows, cols, xpix, ypix)
                                    winsize = struct.pack("HHHH", rows, cols, 0, 0)
                                    fcntl.ioctl(master_fd, termios.TIOCSWINSZ, winsize)
                                except Exception:
                                    # ignore ioctl failures (non-unix or bad fd)
                                    pass
                                # don't forward the resize JSON to the PTY process
                                continue
                        except Exception:
                            # not valid JSON -> fall through to send keystrokes
                            pass
                    # Normal text input from client -> send to PTY
                    try:
                        os.write(master_fd, text.encode())
                    except Exception:
                        pass
                elif msg.get("bytes") is not None:
                    # binary data from client
                    try:
                        os.write(master_fd, msg.get("bytes"))
                    except Exception:
                        pass
            elif mtype == "websocket.disconnect":
                break
    except WebSocketDisconnect:
        pass
    finally:
        # cleanup
        try:
            loop.remove_reader(master_fd)
        except Exception:
            pass
        try:
            os.close(master_fd)
        except Exception:
            pass
        # try to terminate child process
        try:
            os.kill(pid, 15)
        except Exception:
            pass
