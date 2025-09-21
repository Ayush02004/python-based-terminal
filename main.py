# main.py
from terminal.cli import TerminalCLI

def main():
    cli = TerminalCLI(base_dir="sandbox")
    cli.run()

if __name__ == "__main__":
    main()
