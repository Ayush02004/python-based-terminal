# Python Sandboxed Terminal

**Live Demo:** [Replit Deployment](https://0b0eabe7-fdf6-49a8-8ffc-8835d48822be-00-sf594yq47ohn.pike.replit.dev/)

A Python-based **sandboxed terminal** that supports common Linux-like commands inside a safe workspace. Runs locally in your shell or via a browser UI (FastAPI + WebSocket + xterm.js).

---

## Features
- Sandbox — all file operations restricted to `sandbox/`
- Commands: `ls`, `cd`, `pwd`, `mkdir`, `rm`, `touch`, `cat`, `echo`, `grep`, `find`, `head`, `tail`, `stat`, `chmod`, `cp`, `mv`, `monitor` (psutil)
- Error handling for invalid commands
- CLI mode (`python main.py`)
- Web mode (browser terminal with xterm.js)

---

## Quick Start

### Run Locally
```bash
git clone https://github.com/your-username/your-repo.git
cd your-repo
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Web terminal
uvicorn terminal.web:app --host 127.0.0.1 --port 8000 --reload
# open http://127.0.0.1:8000/

# CLI terminal
python main.py
```
## Project Architecture

### Backend Components
- **FastAPI Web Server** (`terminal/web.py`): Serves the HTML interface and handles WebSocket connections
- **Terminal CLI** (`terminal/cli.py`): Implements the sandboxed command-line interface
- **Sandbox Manager** (`terminal/sandbox.py`): Manages file system restrictions and security
- **Commands Executor** (`terminal/commands.py`): Handles command execution in the sandbox
- **Server Runner** (`server.py`): Main entry point that starts the web server

### Frontend
- **Web Interface** (`terminal/templates/index.html`): HTML page with xterm.js terminal emulator
- Uses WebSocket connection to communicate with the backend PTY (pseudo-terminal)

### Key Features
- Web-based terminal interface using xterm.js
- Sandboxed file system operations (restricted to `sandbox/` directory)
- Real-time terminal communication via WebSocket
- Support for common Unix commands: ls, cd, pwd, mkdir, rm, touch, cat, etc.
- Tab completion and command history

## Dependencies
- Python 3.12
- FastAPI 0.117.1
- uvicorn 0.36.0 with standard extras
- psutil 7.1.0
- jinja2 3.1.6

## Workflow Configuration
- **Terminal Server**: Runs `python server.py` on port 5000
- Configured for webview output to show the terminal interface to users

## Deployment
- Configured for autoscale deployment target
- Production command: `python server.py`
- Serves on port 5000 with proper host binding for web access