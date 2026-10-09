"""物理单位换算：毫米、英寸、磅值。"""

MM_PER_INCH: float = 25.4
PT_TO_MM: float = MM_PER_INCH / 72.0


def mm_to_inch(mm: float) -> float:
    """毫米转英寸。"""
    return mm / MM_PER_INCH


def pt_to_mm(pt: float) -> float:
    """磅值转毫米。"""
    return pt * PT_TO_MM


def canvas_mm(w_mm: float, h_mm: float) -> tuple[float, float]:
    """生成 matplotlib 接受的 figsize (英寸元组)。"""
    return (mm_to_inch(w_mm), mm_to_inch(h_mm))
