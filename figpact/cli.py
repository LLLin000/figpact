"""figpact 命令行工具。"""
import argparse
import sys
from typing import Optional


def main(argv: Optional[list[str]] = None) -> int:
    """命令行主入口。"""
    if argv is None:
        argv = sys.argv[1:]
    return 0


if __name__ == "__main__":
    sys.exit(main())
