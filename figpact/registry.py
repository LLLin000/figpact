"""Artist 图元身份与参数绑定注册表。"""
from typing import Any, Optional
import matplotlib.figure
import matplotlib.text
import matplotlib.lines
import matplotlib.axes
import matplotlib.legend
from figpact.transform import apply_display_shift


class GidRegistry:
    """管理 Artist 图元、gid 以及其绑定的 YAML 参数。"""

    def __init__(self):
        self._artists: dict[str, Any] = {}
        self._params: dict[str, list[str]] = {}

    def register(self, artist: Any, gid: str, *, params: Optional[list[str]] = None) -> None:
        """注册图元，设置 artist.set_gid(gid)，并绑定参数。"""
        if not gid:
            raise ValueError("gid 不能为空")
        artist.set_gid(gid)
        self._artists[gid] = artist
        self._params[gid] = list(params) if params is not None else []

    def get(self, gid: str) -> Any:
        """获取注册的 Artist。"""
        return self._artists.get(gid)

    def all(self) -> dict[str, Any]:
        """返回所有已注册 {gid: artist}。"""
        return dict(self._artists)

    def params_of(self, gid: str) -> list[str]:
        """返回绑定到该 gid 的参数列表。"""
        return list(self._params.get(gid, []))

    def unregistered(self, fig: matplotlib.figure.Figure) -> list[str]:
        """可见但没有 gid 的对象（按类型+文字摘要描述）。"""
        unreg: list[str] = []

        for ax in fig.axes:
            # 轴标题
            for name, txt in [("xlabel", ax.xaxis.label), ("ylabel", ax.yaxis.label), ("title", ax.title)]:
                if txt is not None and txt.get_visible() and txt.get_text().strip():
                    if not txt.get_gid():
                        unreg.append(f"Text({name}): «{txt.get_text()[:30]}»")

            # 刻度标签通常成批生成，若无 gid 汇总或检查
            # 文本对象
            for t in ax.texts:
                if t.get_visible() and t.get_text().strip() and not t.get_gid():
                    unreg.append(f"Text: «{t.get_text()[:30]}»")

            # 折线 / 曲线
            for ln in ax.lines:
                if ln.get_visible() and not ln.get_gid():
                    pts = len(ln.get_xdata()) if hasattr(ln, "get_xdata") else 0
                    unreg.append(f"Line2D(pts={pts})")

            # 图例
            leg = ax.get_legend()
            if leg is not None and leg.get_visible() and not leg.get_gid():
                unreg.append("Legend")

        for t in fig.texts:
            if t.get_visible() and t.get_text().strip() and not t.get_gid():
                unreg.append(f"FigureText: «{t.get_text()[:30]}»")

        return unreg

    def unbound(self) -> list[str]:
        """有 gid 但没绑任何参数的对象。"""
        return [gid for gid, p in self._params.items() if len(p) == 0]

    def apply_shift(self, gid: str, dx_mm: float = 0.0, dy_mm: float = 0.0) -> None:
        """布局冻结后对已注册对象应用纯显示位移。"""
        art = self.get(gid)
        if art is not None:
            apply_display_shift(art, dx_mm, dy_mm)
