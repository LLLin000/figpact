"""纯显示位移变换：通过 ScaledTranslation 平移图元，不修改数据坐标。"""
from typing import Any
from matplotlib.transforms import ScaledTranslation
from matplotlib.patches import Patch


def apply_display_shift(artist: Any, dx_mm: float = 0.0, dy_mm: float = 0.0) -> None:
    """在底变换基础上叠加 ScaledTranslation (dx_mm, dy_mm)。
    Patch 的局部形状变换由自身保留，只在数据/混合坐标变换上叠加毫米位移。
    """
    if not dx_mm and not dy_mm:
        return
    fig = artist.figure
    if fig is None and hasattr(artist, "axes") and artist.axes is not None:
        fig = artist.axes.figure
    if fig is None:
        raise ValueError(f"Artist {artist} 尚未关联到 Figure，无法获取 dpi_scale_trans")

    shift = ScaledTranslation(dx_mm / 25.4, dy_mm / 25.4, fig.dpi_scale_trans)
    base_trans = artist.get_data_transform() if isinstance(artist, Patch) else artist.get_transform()
    artist.set_transform(base_trans + shift)
