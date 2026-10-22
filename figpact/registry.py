"""Artist 图元身份与参数绑定注册表。

一个 gid 只对应一个 Artist：重复注册是**拒绝**（抛 ValueError），不是覆盖 ——
覆盖会让后注册的图元静默顶掉前者，快照与 QA 从此对着错的图元说话。

除身份与参数绑定外，注册表还持有：
  - 节点元数据（parent / editable / science_policy / type），未声明的一律 fail closed；
  - gid ↔ 精确路径数组 的双向映射（路径按层展开，gid 里的点**永不**当分隔符）；
  - 可见但未登记图元的枚举（Text / Line2D / Legend / AxesImage / Patch / 各种
    Collection / 自定义 Artist 全在内）。
"""
from typing import Any, Iterator, Optional
import matplotlib.figure
import matplotlib.text
import matplotlib.lines
import matplotlib.axes
import matplotlib.legend
from figpact.transform import apply_display_shift


def _text_summary(t: Any, limit: int = 30) -> str:
    return f"«{str(t.get_text())[:limit]}»"


def _image_shape(im: Any) -> str:
    try:
        arr = im.get_array()
        return "x".join(str(int(n)) for n in arr.shape)
    except Exception:
        return "?"


def _collection_summary(coll: Any) -> str:
    for getter in ("get_segments", "get_paths"):
        get = getattr(coll, getter, None)
        if get is None:
            continue
        try:
            return f"{getter[4:]}={len(get())}"
        except Exception:
            continue
    return "?"


class GidRegistry:
    """管理 Artist 图元、gid 以及其绑定的 YAML 参数与精确路径。"""

    def __init__(self, *, scope: Optional[str] = None):
        self._artists: dict[str, Any] = {}
        self._params: dict[str, list[str]] = {}
        self._paths: dict[str, list[list[str]]] = {}
        self._meta: dict[str, dict[str, Any]] = {}
        self._scope = scope

    # ---------------------------------------------------------------- identity
    @property
    def scope(self) -> Optional[str]:
        """这个注册表所属的作用域（一个作用域可以有多个 Axes，别按 axes 猜）。"""
        return self._scope

    def register(
        self,
        artist: Any,
        gid: str,
        *,
        params: Optional[list[str]] = None,
        controlled_by: Optional[list[list[str]]] = None,
        parent: Optional[str] = None,
        editable: Optional[bool] = None,
        science_policy: Optional[str] = None,
        artist_type: Optional[str] = None,
        scope: Optional[str] = None,
    ) -> None:
        """注册图元，设置 artist.set_gid(gid)，并绑定参数与精确路径。

        `controlled_by` 是**精确路径数组**的列表（如 [["scalars", "label_font_pt"]]），
        不是点分字符串；gid 里的点不参与切分。重复 gid 直接抛错。
        """
        if not gid:
            raise ValueError("gid 不能为空")
        if gid in self._artists:
            raise ValueError(f"gid 重复注册：{gid!r}（拒绝覆盖已有图元）")
        artist.set_gid(gid)
        self._artists[gid] = artist
        self._params[gid] = list(params) if params is not None else []
        self._paths[gid] = [[str(seg) for seg in path] for path in (controlled_by or ())]
        self._meta[gid] = {
            "parent": parent,
            "editable": editable,
            "science_policy": science_policy,
            "type": artist_type,
            "scope": scope if scope is not None else self._scope,
        }

    def get(self, gid: str) -> Any:
        """获取注册的 Artist。"""
        return self._artists.get(gid)

    def all(self) -> dict[str, Any]:
        """返回所有已注册 {gid: artist}（注册顺序）。"""
        return dict(self._artists)

    def gids(self) -> list[str]:
        return list(self._artists)

    def params_of(self, gid: str) -> list[str]:
        """返回绑定到该 gid 的参数键列表（遗留字段，保持原义）。"""
        return list(self._params.get(gid, []))

    def meta_of(self, gid: str) -> dict[str, Any]:
        """节点元数据（未声明的字段为 None，由消费方 fail closed）。"""
        return dict(self._meta.get(gid) or {})

    def set_meta(self, gid: str, **fields: Any) -> None:
        """覆盖/补充已注册 gid 的元数据（只认 register 里那几个字段）。"""
        if gid not in self._artists:
            raise KeyError(f"未注册的 gid：{gid!r}")
        for key, value in fields.items():
            if key not in self._meta[gid]:
                raise KeyError(f"未知元数据字段：{key!r}")
            if value is not None:
                self._meta[gid][key] = value

    def scopes(self) -> list[str]:
        """本注册表出现过的所有作用域（注册顺序，去重）。"""
        out: list[str] = []
        for gid in self._artists:
            scope = self._meta[gid].get("scope")
            if scope and scope not in out:
                out.append(scope)
        return out

    # ------------------------------------------------------- exact path mapping
    def paths_of(self, gid: str) -> list[list[str]]:
        """gid → 显式声明的精确路径数组。

        参数名（`params`）**不是**已验证的精确 YAML 路径（可能来自 dict 控件、名字里
        还可能带点），所以绝不在这里合成路径；要映射就暴露到 `params_of` 里等调用方
        用显式契约绑好。
        """
        return [list(p) for p in self._paths.get(gid, [])]

    def declared_paths_of(self, gid: str) -> list[list[str]]:
        """只有显式声明过的受控路径（`paths_of` 的同义别名，语义相同）。"""
        return self.paths_of(gid)

    def objects_of_path(self, path: list[str]) -> list[str]:
        """精确路径 → gids（注册顺序）。与 paths_of 严格互为逆映射。"""
        want = [str(seg) for seg in path]
        return [gid for gid in self._artists if want in self.paths_of(gid)]

    def paths_for_gid(self) -> dict[str, list[list[str]]]:
        return {gid: self.paths_of(gid) for gid in self._artists}

    def parameter_index(self) -> list[dict[str, Any]]:
        """[{path, objects}]，由 gid→paths 单向生成，保证两向往返一致。"""
        index: dict[tuple[str, ...], list[str]] = {}
        for gid in self._artists:
            for path in self.paths_of(gid):
                index.setdefault(tuple(path), []).append(gid)
        return [{"path": list(key), "objects": list(index[key])} for key in index]

    def bind_parameters(self, records: Any) -> dict[str, Any]:
        """绑定契约参数记录 [{key, path, objects}]，补全 gid 的受控路径。

        返回 {'bound': n, 'dangling': [gid, ...]} —— 指向未注册 gid 的记录是
        悬空引用，如实上报，不静默丢弃也不自动新建图元。
        """
        bound = 0
        dangling: list[str] = []
        for rec in records or ():
            if not isinstance(rec, dict):
                continue
            path = [str(seg) for seg in (rec.get("path") or ())]
            key = rec.get("key")
            objects = rec.get("objects") or ()
            if not path and key is None:
                continue
            for gid in objects:
                if gid not in self._artists:
                    if gid not in dangling:
                        dangling.append(gid)
                    continue
                if path and path not in self._paths[gid]:
                    self._paths[gid].append(list(path))
                if key is not None and key not in self._params[gid]:
                    self._params[gid].append(key)
                bound += 1
        return {"bound": bound, "dangling": dangling}

    # ------------------------------------------------------------ unregistered
    def _iter_visible_artists(self, fig: matplotlib.figure.Figure) -> Iterator[tuple[Any, str]]:
        """所有可见图元 (artist, 描述)。按 axes 顺序，确定性，每个 Artist 只出一次。

        Text / Line2D / Legend / AxesImage / Patch / LineCollection 等集合 / 自定义
        Artist 全都在内 —— 可见就算数，不能因为某个夹具断言「unregistered 为空」就
        把一整类可见对象从清点里漏掉。
        """
        seen: set[int] = set()

        def take(artist: Any, descriptor: str) -> Optional[tuple[Any, str]]:
            if artist is None or id(artist) in seen:
                return None
            seen.add(id(artist))
            return artist, descriptor

        axes = list(fig.axes)
        seen_axes = {id(ax) for ax in axes}
        index = 0
        while index < len(axes):
            for child in axes[index].child_axes:
                if isinstance(child, matplotlib.axes.Axes) and id(child) not in seen_axes:
                    seen_axes.add(id(child))
                    axes.append(child)
            index += 1
        for ax in axes:
            for name, txt in (("xlabel", ax.xaxis.label), ("ylabel", ax.yaxis.label), ("title", ax.title)):
                if txt is not None and txt.get_visible() and txt.get_text().strip():
                    entry = take(txt, f"Text({name}): {_text_summary(txt)}")
                    if entry:
                        yield entry
            for t in ax.texts:
                if t.get_visible() and t.get_text().strip():
                    entry = take(t, f"Text: {_text_summary(t)}")
                    if entry:
                        yield entry
            for ln in ax.lines:
                if ln.get_visible():
                    pts = len(ln.get_xdata()) if hasattr(ln, "get_xdata") else 0
                    entry = take(ln, f"Line2D(pts={pts})")
                    if entry:
                        yield entry
            for im in ax.images:
                if im.get_visible():
                    entry = take(im, f"AxesImage({_image_shape(im)})")
                    if entry:
                        yield entry
            for patch in ax.patches:
                if patch.get_visible():
                    entry = take(patch, f"{type(patch).__name__}")
                    if entry:
                        yield entry
            for coll in ax.collections:
                if coll.get_visible():
                    entry = take(coll, f"{type(coll).__name__}({_collection_summary(coll)})")
                    if entry:
                        yield entry
            for extra in getattr(ax, "artists", ()) or ():
                if getattr(extra, "get_visible", lambda: True)():
                    entry = take(extra, f"{type(extra).__name__}")
                    if entry:
                        yield entry
            leg = ax.get_legend()
            if leg is not None and leg.get_visible():
                entry = take(leg, "Legend")
                if entry:
                    yield entry
        for im in fig.images:
            if im.get_visible():
                entry = take(im, f"FigureImage({_image_shape(im)})")
                if entry:
                    yield entry
        for t in fig.texts:
            if t.get_visible() and t.get_text().strip():
                entry = take(t, f"FigureText: {_text_summary(t)}")
                if entry:
                    yield entry
        for extra in getattr(fig, "artists", ()) or ():
            if getattr(extra, "get_visible", lambda: True)():
                entry = take(extra, f"FigureArtist({type(extra).__name__})")
                if entry:
                    yield entry
        for leg in getattr(fig, "legends", ()) or ():
            if leg.get_visible():
                entry = take(leg, "FigureLegend")
                if entry:
                    yield entry

    def unregistered_artists(self, fig: matplotlib.figure.Figure) -> list[dict[str, Any]]:
        """可见但没有 gid 的图元（连带 artist 本体，供快照建节点）。"""
        out: list[dict[str, Any]] = []
        for artist, descriptor in self._iter_visible_artists(fig):
            if not artist.get_gid():
                out.append({"descriptor": descriptor, "artist": artist})
        return out

    def unregistered(self, fig: matplotlib.figure.Figure) -> list[str]:
        """可见但没有 gid 的对象（按类型+文字摘要描述）。"""
        return [entry["descriptor"] for entry in self.unregistered_artists(fig)]

    def unbound(self) -> list[str]:
        """有 gid 但没绑任何参数的对象。"""
        return [gid for gid, p in self._params.items() if len(p) == 0]

    def apply_shift(self, gid: str, dx_mm: float = 0.0, dy_mm: float = 0.0) -> None:
        """布局冻结后对已注册对象应用纯显示位移。"""
        art = self.get(gid)
        if art is not None:
            apply_display_shift(art, dx_mm, dy_mm)
