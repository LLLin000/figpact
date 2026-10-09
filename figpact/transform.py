"""纯显示位移变换：通过 ScaledTranslation 平移图元，不修改数据坐标。"""
from typing import Any


def apply_display_shift(artist: Any, dx_mm: float = 0.0, dy_mm: float = 0.0) -> None:
    """在底变换基础上叠加 ScaledTranslation (dx_mm, dy_mm)。
    底变换必须通过 artist.get_transform() 获取，以兼容 blended transform。
    """
    pass
