"""figpact 测试包。

只做两件事：钉死 headless 后端（测试要在没显示器的机器上跑），
把仓库根目录放进 sys.path（`python -m unittest discover -s tests` 在任意 cwd 都能 import figpact）。
不打印、不写文件。
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("MPLBACKEND", "Agg")

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import matplotlib

matplotlib.use("Agg", force=True)
