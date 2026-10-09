"""Artist 图元身份与参数绑定注册表。"""
from typing import Any, Optional
import matplotlib.figure


class GidRegistry:
    """管理 Artist 图元、gid 以及其绑定的 YAML 参数。"""

    def __init__(self):
        self._artists: dict[str, Any] = {}
        self._params: dict[str, list[str]] = {}

    def register(self, artist: Any, gid: str, *, params: Optional[list[str]] = None) -> None:
        """注册图元，设置 artist.set_gid(gid)，并绑定参数。"""
        pass

    def get(self, gid: str) -> Any:
        """获取注册的 Artist。"""
        pass

    def all(self) -> dict[str, Any]:
        """返回所有已注册 {gid: artist}。"""
        pass

    def params_of(self, gid: str) -> list[str]:
        """返回绑定到该 gid 的参数列表。"""
        pass

    def unregistered(self, fig: matplotlib.figure.Figure) -> list[str]:
        """可见但未注册 gid 的对象描述。"""
        pass

    def unbound(self) -> list[str]:
        """有 gid 但未绑定任何参数的对象清单。"""
        pass

    def apply_shift(self, gid: str, dx_mm: float = 0.0, dy_mm: float = 0.0) -> None:
        """对已注册对象应用显示位移。"""
        pass
