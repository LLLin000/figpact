"""图表质量检查 (QA) 判据与报告。"""
from pathlib import Path
from typing import Any, Optional
import matplotlib.figure


def signature(problem: str) -> str:
    """抹掉浮点数与度量值，提取稳定的几何问题签名。"""
    pass


def check_out_of_frame(fig: matplotlib.figure.Figure, *, gid_filter: Optional[Any] = None) -> list[str]:
    """检查对象是否超出坐标轴框架（裁切）。"""
    pass


def check_text_overlap(fig: matplotlib.figure.Figure) -> list[str]:
    """检查文本之间是否有真实重叠（交叠面积 > 阈值）。"""
    pass


def check_text_on_data(fig: matplotlib.figure.Figure) -> list[str]:
    """检查文本是否与数据曲线相交。"""
    pass


def check_glyph_floor(fig: matplotlib.figure.Figure, min_pt: float = 5.0, shrink: float = 0.7) -> list[str]:
    """检查含上下标的文字是否跌破出版字形字号下限。"""
    pass


def check_edge_clearance(fig: matplotlib.figure.Figure, min_mm: float = 1.0) -> list[str]:
    """检查文本或图例距边框的最小净空。"""
    pass


def check_series_order(fig: matplotlib.figure.Figure, order: list[str], min_mm: float = 0.5) -> list[str]:
    """相邻系列保持上下顺序与最小净空。"""
    pass


def audit_pdf(path: Path | str, min_pt: float = 5.0) -> tuple[bool, list]:
    """终极审计导出的 PDF 文件中的字形大小。"""
    pass


def blocking_problems(fig: matplotlib.figure.Figure, *, config: Optional[dict] = None) -> list[str]:
    """汇总所有阻断项（几何出框、重叠、压线、曲线穿插等）。"""
    pass


def report(fig: matplotlib.figure.Figure, name: str = "figure", *, config: Optional[dict] = None) -> bool:
    """打印 QA 报告，返回是否无阻断项。"""
    pass
