"""原子发布与人工豁免管理。"""
from pathlib import Path
from typing import Optional


def staging_dir(prefix: str = "figpact-") -> Path:
    """创建临时暂存目录。"""
    pass


def publish(staging: Path | str, target: Path | str) -> list[str]:
    """将暂存目录下的产物原子替换到目标目录（先写临时文件再 os.replace）。"""
    pass


class Exemptions:
    """人工豁免记录管理器。"""

    def __init__(self, path: Path | str):
        self.path = Path(path)

    def load(self) -> dict[str, str]:
        """加载 {签名: 理由}，无 reason 的条目不认。"""
        pass

    def write(self, blockers: list[str], reason: str) -> None:
        """记录新的豁免。reason 为空抛出 ValueError。"""
        pass
