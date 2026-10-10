"""figpact 模块直接执行入口 (-m figpact)。"""
import sys
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

from figpact.cli import main

if __name__ == "__main__":
    sys.exit(main())
