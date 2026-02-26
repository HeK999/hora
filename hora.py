#!/usr/bin/env python3

from pathlib import Path
import sys


def main() -> None:
    local_src = Path(__file__).resolve().parent / "src"
    if local_src.is_dir():
        sys.path.insert(0, str(local_src))

    from hora.cli import main as cli_main

    cli_main()


if __name__ == "__main__":
    main()
