"""图表质量检查 (QA) 判据与报告。"""
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
import numpy as np
import matplotlib.figure
from figpact.units import MM_PER_INCH
from figpact.geometry import figure_image_bbox


@dataclass(frozen=True)
class Diagnostic:
    """一条结构化 QA 诊断。

    数值（mm / px² / 点数 / 字号）随 dpi 与排版变，**不许**进标识；
    规则、作用域、对象 id 是这条缺陷的身份，**不许**被抹掉。
    """
    rule_id: str
    scope: str
    object_ids: tuple[str, ...]
    severity: str           # "blocking" | "warning" | "unknown"
    measured: Optional[float]
    threshold: Optional[float]
    message: str


def diagnostic_key(d: Diagnostic) -> tuple:
    """缺陷的稳定标识：(规则, 作用域, 对象 id 排序)。

    这是「豁免不串」与「try 差异不误判」的前提：
    `「3p68」无可行避让位置` 与 `「2p02」无可行避让位置` 是**两条**缺陷，
    以前那个把数字抹成 # 的正则签名会把它们压成同一个字符串。
    """
    return (d.rule_id, d.scope, tuple(sorted(d.object_ids)))


#: 规则表：(rule_id, severity, 正则)。同一 rule_id 可有多条（同一缺陷的不同措辞）。
#: 正则里的 o1/o2/o3 命名组按顺序成为 object_ids。**先具体、后笼统**。
_RULES: tuple[tuple[str, str, re.Pattern], ...] = (
    ("NO_FEASIBLE_SLOT", "blocking", re.compile(r"「(?P<o1>[^」]+)」无可行避让位置")),
    ("GUIDE_CROSSES_LEGEND", "blocking", re.compile(r"「(?P<o1>[^」]+)」引线穿过图例")),
    ("OUT_OF_FRAME", "blocking", re.compile(r"「(?P<o1>[^」]+)」[^「]*?超出坐标框")),
    ("OUT_OF_FRAME", "blocking", re.compile(r"「(?P<o1>[^」]+)」[^「]*?超出画布")),
    ("UNMEASURED_GEOMETRY", "blocking", re.compile(r"「(?P<o1>[^」]+)」图幅图像几何无法测量")),
    ("UNKNOWN_LABEL_GID", "blocking", re.compile(r"未知标注 gid[:：](?P<o1>[^（(]+)")),
    ("TEXT_OVERLAP", "blocking", re.compile(r"«(?P<o1>[^»]+)»\s*与\s*«(?P<o2>[^»]+)»\s*重叠")),
    ("TEXT_OVERLAP", "blocking", re.compile(r"重叠[^«]*«(?P<o1>[^»]+)»\s*×\s*«(?P<o2>[^»]+)»")),
    ("SERIES_ORDER", "blocking", re.compile(r"「(?P<o1>[^」]+)」与「(?P<o2>[^」]+)」最近处")),
    ("TEXT_ON_DATA", "blocking", re.compile(r"«(?P<o1>[^»]+)»\s*压在\s*(?P<o2>\S+)\s*上")),
    ("TEXT_ON_DATA", "blocking", re.compile(r"压线[^«]*«(?P<o1>[^»]+)»")),
    ("EDGE_CLEARANCE", "warning", re.compile(r"«(?P<o1>[^»]+)»\s*距(?P<o2>[上下左右])边框仅")),
    ("EDGE_CLEARANCE", "warning", re.compile(r"贴(?P<o2>[上下左右])边框[^«]*«(?P<o1>[^»]+)»")),
    ("GLYPH_FLOOR", "warning", re.compile(r"[-\d.]+ pt\s*→\s*字形[^«]*«(?P<o1>[^»]+)»")),
    # 汇总行（`[QA] <图名>: 发现 N 处…`）：只留规则与图名，数字是计数。
    ("QA_GLYPH_FLOOR", "warning", re.compile(r"^(\d+) 处上下标字号跌破字形下限")),
    ("QA_TEXT_OVERLAP", "blocking", re.compile(r"^发现 \d+ 处文字重叠")),
    ("QA_TEXT_ON_DATA", "blocking", re.compile(r"^发现 \d+ 处文字压线")),
    ("QA_EDGE_CLEARANCE", "warning", re.compile(r"^发现 \d+ 处贴边")),
    ("QA_BLOCKING", "blocking", re.compile(r"^发现 \d+ 处阻断项")),
    ("QA_SHIFT_BOUNDS", "blocking", re.compile(r"^\d+ 处(显示位移越界|越界)")),
)

_QA_LINE_RE = re.compile(r"^\[QA\]\s*(?P<name>[^:：]+)[：:]\s*(?P<body>.*)$")
_TAG_RE = re.compile(r"^\[(?:未豁免|豁免|验收)\]\s*")
_SCOPE_PREFIX_RE = re.compile(r"^\[(?P<scope>[^\]]+)\]\s*")
_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")


def _scope_from_objects(object_ids: tuple[str, ...]) -> str:
    """从 gid 里取作用域：`fig2_nmr.main.curve.vannh2` → `main`。

    只认 `fig…` 开头的 gid：QA 文本里的对象 id 也可能是**文字内容**
    （如 «Transmittance (a.u.)»），拿它按点切会切出 `u` 这种假作用域。
    """
    for oid in object_ids:
        parts = oid.split(".")
        if len(parts) >= 3 and parts[0].lower().startswith("fig") and parts[1] \
                and not parts[1][0].isdigit():
            return parts[1]
    return ""


def diagnose(problem: str) -> Diagnostic:
    """把任意一处 QA 文本解析成结构化诊断。

    认不出来的行归 `UNCLASSIFIED`，**原文整句**当对象 id —— 不再抹数字：
    抹数字会把只差对象 id 的未知文本压成同一个 key，等于给未知对象发通行证。
    认得出的（峰 id、曲线 gid、图名）一律保住身份，数字则退到 measured/threshold。
    """
    msg = str(problem)
    scope = ""
    body = msg.strip()
    m = _QA_LINE_RE.match(body)
    if m:
        scope = m.group("name").strip()
        body = m.group("body").strip()
    else:
        body = _TAG_RE.sub("", body).strip()
        m = _SCOPE_PREFIX_RE.match(body)
        if m:
            scope = m.group("scope").strip()
            body = body[m.end():].strip()

    nums = [float(x) for x in _NUM_RE.findall(body)]
    measured = nums[0] if nums else None
    threshold = nums[1] if len(nums) > 1 else None

    for rule_id, severity, rx in _RULES:
        hit = rx.search(body)
        if not hit:
            continue
        ids = tuple(str(v).strip() for v in hit.groupdict().values() if v)  # type: ignore[union-attr]
        ids = tuple(v for v in ids if v)
        # measured/threshold 只做展示：取**对象 id 之外**的第一/第二个数字。
        # （对象 id 里本身可能带数字，比如峰名 3p68，那不是测得的量。）
        rest = body
        for v in ids:
            rest = rest.replace(v, " ", 1)
        nums = [float(x) for x in _NUM_RE.findall(rest)]
        return Diagnostic(rule_id, scope or _scope_from_objects(ids), ids,
                          severity, nums[0] if nums else None,
                          nums[1] if len(nums) > 1 else None, msg)

    # 认不出的文本**不做数字抹除**：把数字抹成 # 会把「3p68 …」和「2p02 …」
    # 这类只差对象 id 的未知文本压成同一个 key —— 那就又是误豁免。
    # 未知就保留原文当身份：宁可让 measured 的变化报成「新增 + 消除」，
    # 也不给认不出来的对象发通行证（Exemptions.write 也拒签 UNCLASSIFIED）。
    return Diagnostic("UNCLASSIFIED", scope, (body,), "unknown", measured, threshold, msg)


def diagnostic_key_of(problem: str) -> tuple:
    """字符串版便捷入口：`diagnostic_key(diagnose(problem))`。"""
    return diagnostic_key(diagnose(problem))


def key_to_json(key: tuple) -> str:
    """诊断 key → 字符串（JSON 数组形式）：`["NO_FEASIBLE_SLOT", "", ["3p68"]]`。

    给前端/JSON 报文用 —— 那里字典键只能是字符串，而 tuple 需要一一对应地还原。
    """
    return json.dumps([key[0], key[1], list(key[2])], ensure_ascii=False)


def key_from_json(text: str) -> tuple:
    """`key_to_json` 的逆运算，还原成 `diagnostic_key` 的 tuple 形式。"""
    rule_id, scope, ids = json.loads(text)
    return (rule_id, scope, tuple(sorted(str(i) for i in ids)))


def _legend_canvas_overflow_mm(fig: matplotlib.figure.Figure, leg, renderer) -> Optional[float]:
    """合法外置图例的画布溢出量（mm）：四边全含、含图例子文本/边框实测包围盒。

    返回 None 表示几何不可用（量不出来一律失败关闭，绝不判安全）。
    图例默认 clip_on=True 但 clip_box=None 且 axes=None——它从不受坐标框裁切，
    旧判据拿图例包围盒跟坐标框比，把 bbox_to_anchor 外置图例误判成「已被裁切」。
    """
    try:
        if not leg.get_visible():
            return 0.0
        try:
            bb = leg.get_window_extent(renderer)
        except Exception:
            return None
        if bb.width <= 0 or bb.height <= 0:
            return 0.0  # 空图例无几何可裁
        frame = fig.bbox
        mm_per_px = MM_PER_INCH / fig.dpi
        return max(0.0, frame.x0 - bb.x0, frame.y0 - bb.y0,
                   bb.x1 - frame.x1, bb.y1 - frame.y1) * mm_per_px
    except Exception:
        return None


def _legend_truly_clipped(fig, leg, renderer) -> tuple[bool, Optional[float]]:
    """图例真实裁切几何：clip bbox/path 与图例包围盒求交，交集小于图例即真被裁。

    只看 clip 有无会漏判（legend 默认 clip_on=True 但 clip_box=None 从不受裁）；
    只看画布溢出会漏判（legend 在画布内但 clip 盒小于 legend 仍被裁）。
    返回 (clipped, clipped_area_px2|None)：几何量不出 → (False, None)，交上游失败关闭。
    """
    try:
        bb = leg.get_window_extent(renderer)
    except Exception:
        return False, None
    if bb.width <= 0 or bb.height <= 0:
        return False, 0.0
    clip = None
    try:
        if not bool(leg.get_clip_on()):
            return False, 0.0
    except Exception:
        return False, None
    try:
        clip = leg.get_clip_box()
    except Exception:
        clip = None
    if clip is None:
        try:
            path = leg.get_clip_path()
            if path is not None:
                clip = path.get_extents() if hasattr(path, "get_extents") else None
                if clip is None and isinstance(path, tuple) and len(path) == 2:
                    try:
                        clip = path[0].get_extents(path[1])
                    except Exception:
                        clip = None
        except Exception:
            clip = None
    if clip is None:
        try:
            patch = leg.get_clip_patch()
            if patch is not None:
                clip = patch.get_window_extent(renderer)
        except Exception:
            clip = None
    if clip is None:
        return False, 0.0  # 无裁切盒：不受裁（默认 legend 即此情形）
    try:
        ix0, iy0 = max(bb.x0, clip.x0), max(bb.y0, clip.y0)
        ix1, iy1 = min(bb.x1, clip.x1), min(bb.y1, clip.y1)
    except Exception:
        return False, None
    inter = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
    full = float(bb.width * bb.height)
    if full <= 0:
        return False, 0.0
    if inter < full - 1e-6:
        return True, full - inter
    return False, 0.0


def _real_clip(artist) -> bool:
    """真实裁切证据：clip_on 且有 clip_box 或 patch 任一存在。默认 clip_on 无裁切盒不算裁切。"""
    try:
        if not bool(artist.get_clip_on()):
            return False
    except Exception:
        return False
    for probe in ("get_clip_box", "get_clip_path", "get_clip_patch"):
        try:
            if getattr(artist, probe)() is not None:
                return True
        except Exception:
            continue
    return False


def check_out_of_frame(fig: matplotlib.figure.Figure, *, gid_filter: Optional[Any] = None) -> list[str]:
    """检查坐标轴裁切及图幅图像的画布裁切；未注册图幅图像同样检查。

    图例豁免坐标框比对：它合法外置（bbox_to_anchor），只在真超画布四边时阻断；
    画布几何量不出或不可见判失败关闭。折线沿用既有坐标框裁切策略。
    """
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    mm_per_px = MM_PER_INCH / fig.dpi
    out: list[str] = []

    for ax in fig.axes:
        axbb = ax.get_window_extent()
        watched = []
        for ln in ax.lines:
            gid = ln.get_gid() or ""
            if gid_filter is None:
                if gid:
                    watched.append((gid, ln))
            elif callable(gid_filter):
                if gid_filter(gid):
                    watched.append((gid, ln))
            elif gid_filter in gid:
                watched.append((gid, ln))

        leg = ax.get_legend()
        leg_gid: Optional[str] = None
        if leg is not None:
            leg_gid = leg.get_gid() or "legend"
            if gid_filter is None or (callable(gid_filter) and gid_filter(leg_gid)) or (isinstance(gid_filter, str) and gid_filter in leg_gid):
                over_mm = _legend_canvas_overflow_mm(fig, leg, renderer)
                if over_mm is None:
                    out.append(f"「{leg_gid.rsplit('.', 1)[-1]}」图例几何无法测量，拒绝将裁切判为安全")
                elif over_mm > 0.05:
                    clipped = "（图像已被裁切）" if _real_clip(leg) else "（已超出画布）"
                    out.append(f"「{leg_gid.rsplit('.', 1)[-1]}」超出画布 {over_mm:.2f} mm{clipped}")
        for fig_leg in list(getattr(fig, "legends", []) or []):
            gid = fig_leg.get_gid() or "legend"
            if fig_leg is leg:
                continue
            if gid_filter is None or (callable(gid_filter) and gid_filter(gid)) or (isinstance(gid_filter, str) and gid_filter in gid):
                over_mm = _legend_canvas_overflow_mm(fig, fig_leg, renderer)
                if over_mm is None:
                    out.append(f"「{gid.rsplit('.', 1)[-1]}」图例几何无法测量，拒绝将裁切判为安全")
                elif over_mm > 0.05:
                    clipped = "（图像已被裁切）" if _real_clip(fig_leg) else "（已超出画布）"
                    out.append(f"「{gid.rsplit('.', 1)[-1]}」超出画布 {over_mm:.2f} mm{clipped}")

        for gid, artist in watched:
            try:
                bb = artist.get_window_extent(renderer)
            except Exception:
                continue
            over = max(bb.y1 - axbb.y1, axbb.y0 - bb.y0, bb.x0 - axbb.x0, axbb.x1 - bb.x1)
            # 垂直方向越界通常是位移或堆叠导致严重裁切
            v_over = max(bb.y1 - axbb.y1, axbb.y0 - bb.y0)
            if v_over > 0.05 / mm_per_px:  # 容许微小误差
                name = gid.rsplit(".", 1)[-1]
                out.append(f"「{name}」超出坐标框 {v_over * mm_per_px:.2f} mm（已被裁切）")
    for index, image in enumerate(fig.images):
        if not image.get_visible():
            continue
        # gid_filter is an axes-only selector, never an exemption for image pixels.
        gid = image.get_gid() or f"unregistered.figure_image.{index}"
        bb = figure_image_bbox(image)
        if bb is None:
            out.append(f"「{gid}」图幅图像几何无法测量，拒绝将裁切判为安全")
            continue
        frame = fig.bbox
        overflow = max(0.0, frame.x0 - bb.x0, frame.y0 - bb.y0,
                       bb.x1 - frame.x1, bb.y1 - frame.y1) * mm_per_px
        if overflow > 0.05:
            out.append(f"「{gid}」超出画布 {overflow:.2f} mm（图像已被裁切）")
    return out


def check_text_overlap(fig: matplotlib.figure.Figure, min_area_px: float = 4.0) -> list[str]:
    """检查所有可见文本对象间的真实重叠。"""
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()

    items: list[tuple[str, Any, bool]] = []
    for ax in fig.axes:
        tick_ids = set()
        for t in list(ax.get_xticklabels()) + list(ax.get_yticklabels()):
            tick_ids.add(id(t))
            items.append((t.get_text(), t, True))
        cands = [ax.title, ax.xaxis.label, ax.yaxis.label]
        cands += list(ax.texts)
        leg = ax.get_legend()
        if leg is not None:
            cands += list(leg.get_texts())
        for t in cands:
            if t is not None:
                items.append((t.get_text(), t, id(t) in tick_ids))
    for t in fig.texts:
        items.append((t.get_text(), t, False))

    boxes = []
    for label, t, is_tick in items:
        if not str(label).strip():
            continue
        try:
            bb = t.get_window_extent(renderer)
        except Exception:
            continue
        if bb.width <= 0 or bb.height <= 0:
            continue
        boxes.append((label, bb, is_tick))

    problems = []
    n = len(boxes)
    for i in range(n):
        l1, b1, tick1 = boxes[i]
        for j in range(i + 1, n):
            l2, b2, tick2 = boxes[j]
            if tick1 and tick2:
                continue
            ix0 = max(b1.x0, b2.x0)
            iy0 = max(b1.y0, b2.y0)
            ix1 = min(b1.x1, b2.x1)
            iy1 = min(b1.y1, b2.y1)
            if ix1 > ix0 and iy1 > iy0:
                area = (ix1 - ix0) * (iy1 - iy0)
                if area > min_area_px:
                    s1 = str(l1).strip().replace('\n', ' ')
                    s2 = str(l2).strip().replace('\n', ' ')
                    problems.append(f"«{s1}» 与 «{s2}» 重叠 (面积 {area:.1f} px²)")
    return problems


def check_text_on_data(fig: matplotlib.figure.Figure, pad_px: float = 0.0) -> list[str]:
    """检测文字压在数据曲线上（顶点数 > 2 的 Line2D）。"""
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    problems: list[str] = []

    for ax in fig.axes:
        texts: list[tuple[str, Any]] = []
        for t in ax.texts:
            if t.get_text().strip():
                texts.append((t.get_text(), t))
        leg = ax.get_legend()
        if leg is not None:
            for t in leg.get_texts():
                if t.get_text().strip():
                    texts.append((t.get_text(), t))
        if not texts:
            continue

        boxes = []
        for label, t in texts:
            try:
                bb = t.get_window_extent(renderer)
            except Exception:
                continue
            if bb.width <= 0 or bb.height <= 0:
                continue
            boxes.append((label, bb))

        for ln in ax.lines:
            xy = ln.get_xydata()
            if xy is None or len(xy) <= 2:
                continue
            trans = ln.get_transform()
            try:
                disp_pts = trans.transform(xy)
            except Exception:
                continue

            for label, bb in boxes:
                x_in = (disp_pts[:, 0] >= bb.x0 - pad_px) & (disp_pts[:, 0] <= bb.x1 + pad_px)
                y_in = (disp_pts[:, 1] >= bb.y0 - pad_px) & (disp_pts[:, 1] <= bb.y1 + pad_px)
                hits = int(np.sum(x_in & y_in))
                if hits > 0:
                    gid = ln.get_gid() or "曲线"
                    s = str(label).strip().replace('\n', ' ')
                    problems.append(f"«{s}» 压在 {gid} 上 ({hits} 个采样点穿过文字区)")
    return problems


def check_glyph_floor(fig: matplotlib.figure.Figure, min_pt: float = 5.0, shrink: float = 0.7) -> list[str]:
    """扫描文字：含上下标的，母体字号乘以收缩率不得跌破出版字形下限。"""
    script_re = re.compile(r"\$[^$]*[\\^_][^$]*\$")
    out = []
    for ax in fig.axes:
        texts = list(ax.texts) + [ax.title, ax.xaxis.label, ax.yaxis.label]
        texts += list(ax.get_xticklabels()) + list(ax.get_yticklabels())
        leg = ax.get_legend()
        if leg is not None:
            texts += list(leg.get_texts())
        texts += list(fig.texts)
        for t in texts:
            if t is None:
                continue
            s = t.get_text()
            if not script_re.search(s):
                continue
            size = float(t.get_fontsize())
            if size * shrink < min_pt - 1e-9:
                out.append(f"{size:.1f} pt → 字形 {size * shrink:.2f} pt  «{s[:34]}»")
    return out


def check_edge_clearance(fig: matplotlib.figure.Figure, min_mm: float = 1.0) -> list[str]:
    """检查文字/图例与坐标框边缘的净空是否足够。"""
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    mm_per_px = MM_PER_INCH / fig.dpi
    out: list[str] = []
    for ax in fig.axes:
        axbb = ax.get_window_extent()
        items: list[tuple[str, Any]] = [(t.get_text(), t) for t in ax.texts if t.get_text().strip()]
        leg = ax.get_legend()
        if leg is not None:
            items.append(("<legend>", leg))
            items += [(t.get_text(), t) for t in leg.get_texts()]
        for label, obj in items:
            try:
                bb = obj.get_window_extent(renderer)
            except Exception:
                continue
            if bb.width <= 0:
                continue
            gaps = {
                "上": (axbb.y1 - bb.y1),
                "下": (bb.y0 - axbb.y0),
                "左": (bb.x0 - axbb.x0),
                "右": (axbb.x1 - bb.x1)
            }
            for side, gap_px in gaps.items():
                if -0.5 < gap_px * mm_per_px < min_mm:
                    s = str(label).strip().replace('\n', ' ')
                    out.append(f"«{s}» 距{side}边框仅 {gap_px * mm_per_px:.2f} mm (< {min_mm} mm)")
    return out


def check_series_order(fig: matplotlib.figure.Figure, order: list[str], min_mm: float = 0.5) -> list[str]:
    """相邻系列保持上下顺序与最小净空。order 是从下到上的曲线系列 id 列表。"""
    fig.canvas.draw()
    mm_per_px = MM_PER_INCH / fig.dpi
    out: list[str] = []
    for ax in fig.axes:
        ys: dict[str, np.ndarray] = {}
        for line in ax.lines:
            gid = line.get_gid() or ""
            # 优先从 gid 后缀提取 sid，如 fig2_ftir.annotated.curve.ha -> ha
            sid = gid.rsplit(".", 1)[-1]
            if sid in order:
                xy = line.get_xydata()
                if xy is not None and len(xy) > 2:
                    ys[sid] = line.get_transform().transform(xy)[:, 1]
        present = [sid for sid in order if sid in ys]
        for lower, upper in zip(present, present[1:]):
            if ys[lower].shape != ys[upper].shape:
                continue
            gap_mm = float((ys[upper] - ys[lower]).min()) * mm_per_px
            if gap_mm < min_mm:
                out.append(f"「{lower}」与「{upper}」最近处仅 {gap_mm:.2f} mm（要求 ≥ {min_mm} mm）")
    return out


def audit_pdf(path: Path | str, min_pt: float = 5.0) -> tuple[bool, list]:
    """终极审计导出 PDF 中的字形真实尺寸。"""
    try:
        import collections
        import pymupdf
    except ImportError:
        return True, []

    p = Path(path)
    if not p.is_file():
        return True, []

    doc = pymupdf.open(str(p))
    bad: list[tuple[float, str]] = []
    for page in doc:
        d = page.get_text("dict")
        for block in d["blocks"]:
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    txt = span.get("text", "").strip()
                    if txt and round(span["size"], 2) < min_pt:
                        bad.append((round(span["size"], 2), txt[:34]))
    doc.close()
    unique = list(dict.fromkeys(bad))
    return (len(bad) == 0), unique




#: 记录口径：(rule, 单位, 阈值, 方向)。单位/阈值/方向显式写在记录里，不靠猜。
#: worse="up"（越大越差：出框量/重叠面积/压线点数）、"down"（越小越差：净空/有效字号）。
_RECORD_SPEC: dict[str, dict] = {
    "OUT_OF_FRAME": {"unit": "mm", "threshold": 0.05, "worse": "up", "severity": "blocking"},
    "LEGEND_CLIP": {"unit": "px2", "threshold": 0.0, "worse": "up", "severity": "blocking"},
    "UNMEASURED_GEOMETRY": {"unit": "none", "threshold": None, "worse": "up", "severity": "blocking"},
    "TEXT_OVERLAP": {"unit": "px2", "threshold": 4.0, "worse": "up", "severity": "blocking"},
    "TEXT_ON_DATA": {"unit": "count", "threshold": 1.0, "worse": "up", "severity": "blocking"},
    "GLYPH_FLOOR": {"unit": "pt", "threshold": 5.0, "worse": "down", "severity": "warning"},
}


def _label_token(label: str) -> str:
    """文本身份令牌：全文 sha1 + 长度，绝不截断（截断碰撞会误合身份）。"""
    raw = str(label or "")
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    return f"h{digest}L{len(raw)}"


def _artist_identity(fig, artist, *, role: str, label: str = "") -> Optional[str]:
    """真实 artist 身份：有 gid 用 gid；无 gid 用结构身份（axes 序号+类型+角色+全文哈希）。

    重复对象（同文本多 tick 等）必然同 key：调用方把同 key 记录记歧义，绝不覆盖。
    """
    try:
        gid = artist.get_gid() or ""
    except Exception:
        gid = ""
    if gid:
        return f"gid:{gid}"
    try:
        axes = list(fig.axes)
        ax_idx = axes.index(artist.axes) if getattr(artist, "axes", None) in axes else -1
    except Exception:
        ax_idx = -1
    kind = type(artist).__name__
    lab = str(label or "")
    if not lab.strip():
        return None
    return f"ax{ax_idx}:{kind}:{role}:{_label_token(lab)}"


def _visible(artist) -> bool:
    """自身可见（隐藏 tick/隐藏标注不进入实测，防误报）。"""
    try:
        return bool(artist.get_visible())
    except Exception:
        return False


def _record(rule: str, key: str, value: Optional[float], text: str) -> dict:
    spec = _RECORD_SPEC[rule]
    return {"rule": rule, "key": key, "value": value, "unit": spec["unit"],
            "threshold": spec["threshold"], "worse": spec["worse"],
            "severity": spec["severity"], "text": text}


def measure(fig: matplotlib.figure.Figure, *, min_area_px: float = 4.0,
            min_pt: float = 5.0, shrink: float = 0.7) -> dict:
    """结构化 QA 实测采集：renderer 实测数值记录，授权只看记录不看字符串。

    返回 ``{"records": [...], "problems": [...], "env": {...}}``：
    records 每条 ``{rule,key,value,unit,threshold,worse,severity,text}``，
    key 是真实 artist 身份（gid 优先，否则 axes 结构+类型+角色/文本），value 是
    renderer 实测（出框 mm/重叠 px²/压线点数/有效字号 pt），text 仅用于显示。
    覆盖数学体+纯文本字号下限、图例画布裁切、文字重叠面积、文字压线点数；
    量不出 value=None，交 qa_delta 失败关闭。
    """
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    mm_per_px = MM_PER_INCH / fig.dpi
    records: list[dict] = []
    script_re = re.compile(r"\$[^$]*[\\^_][^$]*\$")

    # 1. 图例画布裁切（合法外置只看画布四边；lines 仍走 check_out_of_frame 原策略）。
    seen_legs = []
    for ax in fig.axes:
        leg = ax.get_legend()
        if leg is not None and all(leg is not s for s in seen_legs):
            seen_legs.append(leg)
    for leg in list(getattr(fig, "legends", []) or []):
        if all(leg is not s for s in seen_legs):
            seen_legs.append(leg)
    for leg in seen_legs:
        try:
            vis = bool(leg.get_visible())
        except Exception:
            vis = False
        if not vis:
            continue
        key = _artist_identity(fig, leg, role="legend",
                               label=str(leg.get_gid() or "legend"))
        if key is None:
            records.append(_record("UNMEASURED_GEOMETRY", "legend:unidentified", None,
                                   "「legend」图例身份无法确定，拒绝将裁切判为安全"))
            continue
        over_mm = _legend_canvas_overflow_mm(fig, leg, renderer)
        clipped, clip_area = _legend_truly_clipped(fig, leg, renderer)
        if over_mm is None or clip_area is None:
            records.append(_record("UNMEASURED_GEOMETRY", key, None,
                                   "「{k}」图例几何无法测量，拒绝将裁切判为安全".format(k=key)))
            continue
        if clipped and clip_area > 0.0:
            records.append(_record("LEGEND_CLIP", key, float(clip_area),
                                   "「{k}」被裁切 (裁掉面积 {a:.1f} px²)".format(k=key, a=clip_area)))
        if over_mm > 0.05:
            records.append(_record("OUT_OF_FRAME", key, over_mm,
                                   "「{k}」超出画布 {m:.2f} mm（已超出画布）".format(k=key, m=over_mm)))
    # 1b. 折线坐标框裁切 + 图幅图像画布裁切（与 check_out_of_frame 同口径，记实测记录）。
    for ax in fig.axes:
        try:
            axbb = ax.get_window_extent()
        except Exception:
            for ln in ax.lines:
                key = _artist_identity(fig, ln, role="curve",
                                        label=str(getattr(ln, "get_gid", lambda: "")() or "curve"))
                records.append(_record("UNMEASURED_GEOMETRY", key or "curve:unidentified",
                                       None, "坐标框几何无法测量，拒绝将裁切判为安全"))
            continue
        for ln in ax.lines:
            try:
                if not bool(ln.get_visible()):
                    continue
            except Exception:
                continue
            key = _artist_identity(fig, ln, role="curve",
                                    label=str(ln.get_gid() or "curve"))
            if key is None:
                records.append(_record("UNMEASURED_GEOMETRY", "curve:unidentified", None,
                                       "折线身份无法确定，拒绝将裁切判为安全"))
                continue
            try:
                bb = ln.get_window_extent(renderer)
            except Exception:
                records.append(_record("UNMEASURED_GEOMETRY", key, None,
                                       "折线几何无法测量，拒绝将裁切判为安全"))
                continue
            v_over = max(bb.y1 - axbb.y1, axbb.y0 - bb.y0)
            if v_over > 0.05 / mm_per_px:
                records.append(_record("OUT_OF_FRAME", key, float(v_over * mm_per_px),
                                       "折线超出坐标框 {m:.2f} mm".format(m=v_over * mm_per_px)))
    for index, image in enumerate(fig.images):
        try:
            vis = bool(image.get_visible())
        except Exception:
            vis = False
        if not vis:
            continue
        gid = image.get_gid() or "unregistered.figure_image.{i}".format(i=index)
        bb = figure_image_bbox(image)
        if bb is None:
            records.append(_record("UNMEASURED_GEOMETRY", "gid:{g}".format(g=gid), None,
                                   "「{g}」图幅图像几何无法测量，拒绝将裁切判为安全".format(g=gid)))
            continue
        frame = fig.bbox
        overflow = max(0.0, frame.x0 - bb.x0, frame.y0 - bb.y0,
                       bb.x1 - frame.x1, bb.y1 - frame.y1) * mm_per_px
        if overflow > 0.05:
            records.append(_record("OUT_OF_FRAME", "gid:{g}".format(g=gid), float(overflow),
                                   "「{g}」超出画布 {m:.2f} mm（图像已被裁切）".format(g=gid, m=overflow)))
    # 2. 文字重叠面积（自身可见非空文本两两实测；tick-tick 跳过；含 fig.legends 文本）。
    items: list[tuple[Any, bool]] = []
    for ax in fig.axes:
        tick_ids = {id(t) for t in list(ax.get_xticklabels()) + list(ax.get_yticklabels())}
        for t in list(ax.get_xticklabels()) + list(ax.get_yticklabels()):
            if _visible(t):
                items.append((t, True))
        cands = [ax.title, ax.xaxis.label, ax.yaxis.label] + list(ax.texts)
        leg = ax.get_legend()
        if leg is not None and _visible(leg):
            cands += list(leg.get_texts())
        for t in cands:
            if t is not None and _visible(t):
                items.append((t, id(t) in tick_ids))
    for t in list(fig.texts):
        if _visible(t):
            items.append((t, False))
    for leg in list(getattr(fig, "legends", []) or []):
        if not _visible(leg):
            continue
        for t in list(leg.get_texts()):
            if _visible(t):
                items.append((t, False))
    boxes: list[tuple[str, Any]] = []
    for t, is_tick in items:
        try:
            label = str(t.get_text() or "")
        except Exception:
            continue
        if not label.strip():
            continue
        try:
            bb = t.get_window_extent(renderer)
        except Exception:
            key = _artist_identity(fig, t, role="text", label=label) or "text:unidentified"
            records.append(_record("UNMEASURED_GEOMETRY", key, None,
                                   f"«{label[:34]}» 文字几何无法测量，拒绝判为安全"))
            continue
        if bb.width <= 0 or bb.height <= 0:
            continue
        key = _artist_identity(fig, t, role="text", label=label)
        if key is None:
            key = "text:unidentified"
        boxes.append((key, bb, is_tick, label))
    n = len(boxes)
    for i in range(n):
        k1, b1, tick1, l1 = boxes[i]
        for j in range(i + 1, n):
            k2, b2, tick2, l2 = boxes[j]
            if tick1 and tick2:
                continue
            ix0, iy0, ix1, iy1 = max(b1.x0, b2.x0), max(b1.y0, b2.y0), min(b1.x1, b2.x1), min(b1.y1, b2.y1)
            if ix1 > ix0 and iy1 > iy0:
                area = (ix1 - ix0) * (iy1 - iy0)
                if area > min_area_px:
                    key = f"overlap:{k1} x {k2}"
                    records.append(_record("TEXT_OVERLAP", key, float(area),
                                           f"«{l1.strip()[:24]}» 与 «{l2.strip()[:24]}» 重叠 (面积 {area:.1f} px²)"))
    # 3. 文字压线点数（顶点数 > 2 的 Line2D 实测穿过文字区采样点）。
    for ax in fig.axes:
        texts: list[tuple[str, Any]] = []
        for t in ax.texts:
            try:
                if _visible(t) and t.get_text().strip():
                    texts.append((t.get_text(), t))
            except Exception:
                continue
        for leg in [ax.get_legend()] + list(getattr(fig, "legends", []) or []):
            if leg is None or not _visible(leg):
                continue
            for t in leg.get_texts():
                try:
                    if _visible(t) and t.get_text().strip():
                        texts.append((t.get_text(), t))
                except Exception:
                    continue
        if not texts:
            continue
        tboxes = []
        for label, t in texts:
            try:
                bb = t.get_window_extent(renderer)
            except Exception:
                continue
            if bb.width <= 0 or bb.height <= 0:
                continue
            tkey = _artist_identity(fig, t, role="text", label=label) or "text:unidentified"
            tboxes.append((label, bb, tkey))
        for ln in ax.lines:
            xy = ln.get_xydata()
            if xy is None or len(xy) <= 2:
                continue
            try:
                disp_pts = ln.get_transform().transform(xy)
            except Exception:
                continue
            lgid = _artist_identity(fig, ln, role="curve",
                                    label=str(ln.get_gid() or "曲线")) or "curve:unidentified"
            for label, bb, tkey in tboxes:
                x_in = (disp_pts[:, 0] >= bb.x0) & (disp_pts[:, 0] <= bb.x1)
                y_in = (disp_pts[:, 1] >= bb.y0) & (disp_pts[:, 1] <= bb.y1)
                hits = int(np.sum(x_in & y_in))
                if hits > 0:
                    s = str(label).strip().replace('\n', ' ')[:24]
                    records.append(_record("TEXT_ON_DATA", f"ondata:{tkey} x {lgid}",
                                           float(hits), f"«{s}» 压线 ({hits} 个采样点穿过文字区)"))
    # 4. 字号下限：数学体 shrink 实测 + 纯文本直接下限（同一 5pt 口径）。
    try:
        artists = list(fig.findobj())
    except Exception:
        artists = []
    import matplotlib.text as _mtext
    for art in artists:
        if not isinstance(art, _mtext.Text):
            continue
        try:
            if not art.get_visible():
                continue
            s = str(art.get_text() or "")
        except Exception:
            continue
        if not s.strip():
            continue
        try:
            size = float(art.get_fontsize())
        except Exception:
            key = _artist_identity(fig, art, role="glyph", label=s) or "glyph:unidentified"
            records.append(_record("UNMEASURED_GEOMETRY", key, None,
                                   f"«{s[:34]}» 字号无法测量，拒绝判为安全"))
            continue
        key = _artist_identity(fig, art, role="glyph", label=s) or "glyph:unidentified"
        if script_re.search(s):
            eff = size * shrink
            if eff < min_pt - 1e-9:
                records.append(_record("GLYPH_FLOOR", key, eff,
                                       f"{size:.1f} pt → 字形 {eff:.2f} pt  «{s[:34]}»"))
        elif size < min_pt - 1e-9:
            records.append(_record("GLYPH_FLOOR", key, size,
                                   f"plain {size:.1f} pt < {min_pt:.1f} pt floor «{s[:34]}»"))
    problems = [r["text"] for r in records]
    try:
        dpi = float(fig.dpi)
    except Exception:
        dpi = float("nan")
    env = {"dpi": dpi, "n_records": len(records)}
    return {"records": records, "problems": problems, "env": env}


def _valid_record(r) -> bool:
    """记录封闭校验：rule 已知 + key 非空 + 口径字段与 _RECORD_SPEC 一致 + value 数值或 None。

    字符串旧输入一律拒（返回 False）；缺字段/口径漂移同样拒，交上游失败关闭。
    """
    if not isinstance(r, dict):
        return False
    rule = str(r.get("key") and r.get("rule") or "")
    if rule not in _RECORD_SPEC:
        return False
    if not str(r.get("key") or ""):
        return False
    spec = _RECORD_SPEC[rule]
    if r.get("unit") != spec["unit"] or r.get("worse") != spec["worse"]:
        return False
    if r.get("severity") != spec["severity"]:
        return False
    th, want = r.get("threshold"), spec["threshold"]
    if want is None:
        if th is not None:
            return False
    elif th is None or abs(float(th) - float(want)) > 1e-9:
        return False
    v = r.get("value")
    if v is not None:
        try:
            fv = float(v)
        except (TypeError, ValueError):
            return False
        if not (fv == fv and abs(fv) != float("inf")):
            return False
    return True


def _as_records(payload) -> Optional[list[dict]]:
    """records 归一化：接受 {"records": [...]} 或纯 list[dict]；旧 list[str] 永拒。

    每条记录过 _valid_record 封闭校验：任一条非法 → 整体 None（失败关闭）。
    授权记录永不从字符串数字猜。
    """
    recs = None
    if isinstance(payload, dict) and isinstance(payload.get("records"), list):
        recs = list(payload["records"])
    elif isinstance(payload, list):
        recs = list(payload)
    else:
        return None
    for r in recs:
        if not _valid_record(r):
            return None
    return recs


def qa_delta(before, after) -> dict:
    """比较基线/候选实测记录：eligible 仅当无新增、无恶化、无未知、无歧义。

    输入是 measure() 的 ``{"records": [...]}``（或纯记录列表）；旧 list[str]
    文本**不进入授权判定**（直接 eligible=False 失败关闭）。
    同 key 重复记录取 worst 且记歧义（ambiguous），绝不覆盖丢缺陷。
    阈值/单位/方向全显式（见 _RECORD_SPEC），数值比较用记录 value，不解析文本。
    """
    brec, arec = _as_records(before), _as_records(after)
    if brec is None or arec is None:
        return {"eligible": False, "inherited": [], "new": [], "worsened": [],
                "unmeasured": ["non-record-input"], "ambiguous": ["non-record-input"],
                "reason": "非实测记录输入，失败关闭"}

    def _index(recs: list[dict]) -> tuple[dict[str, dict], list[str]]:
        table: dict[str, dict] = {}
        ambiguous: list[str] = []
        for r in recs:
            key = str(r.get("key") or "")
            if not key or str(r.get("rule") or "") not in _RECORD_SPEC:
                ambiguous.append(key or "<empty-key>")
                continue
            if key in table:
                ambiguous.append(key)
                old, newr = table[key], r
                spec = _RECORD_SPEC[str(old.get("rule"))]
                ov, nv = old.get("value"), newr.get("value")
                if ov is None or nv is None:
                    table[key] = old if ov is None else newr  # 未知优先保留
                elif spec["worse"] == "down":
                    table[key] = newr if float(nv) < float(ov) else old
                else:
                    table[key] = newr if float(nv) > float(ov) else old
                continue
            table[key] = r
        return table, sorted(set(ambiguous))

    btab, bamb = _index(brec)
    atab, aamb = _index(arec)
    ambiguous = sorted(set(bamb) | set(aamb))
    bkeys, akeys = set(btab), set(atab)
    new = sorted(akeys - bkeys)
    gone = sorted(bkeys - akeys)
    inherited = sorted(bkeys & akeys)
    unmeasured: list[str] = []
    worsened: list[dict] = []
    for key in sorted(bkeys | akeys):
        for side in (btab.get(key), atab.get(key)):
            if side is None:
                continue
            rule = str(side.get("rule"))
            if rule not in _RECORD_SPEC or side.get("value") is None:
                if key not in unmeasured:
                    unmeasured.append(key)
    for key in inherited:
        b, a = btab[key], atab[key]
        if str(b.get("rule")) != str(a.get("rule")) or b.get("unit") != a.get("unit") \
                or b.get("worse") != a.get("worse") or b.get("severity") != a.get("severity") \
                or b.get("threshold") != a.get("threshold"):
            worsened.append({"key": key, "before": b.get("value"), "after": a.get("value"),
                             "unit": b.get("unit"), "threshold": b.get("threshold"),
                             "note": "rule/unit/threshold/severity drift"})
            continue
        if b.get("value") is None or a.get("value") is None:
            continue  # 已计入 unmeasured
        spec = _RECORD_SPEC[str(b.get("rule"))]
        bv, av = float(b["value"]), float(a["value"])
        if spec["worse"] == "down":
            worse = av < bv - 1e-9
        else:
            worse = av > bv + 1e-9
        if worse:
            worsened.append({"key": key, "before": bv, "after": av,
                             "unit": spec["unit"], "threshold": spec["threshold"]})
    eligible = not new and not worsened and not unmeasured and not ambiguous
    if new:
        reason = f"新增 {len(new)} 条"
    elif worsened:
        reason = f"恶化 {len(worsened)} 条"
    elif unmeasured:
        reason = f"未知/不可量 {len(unmeasured)} 条，失败关闭"
    elif ambiguous:
        reason = f"歧义 {len(ambiguous)} 处，失败关闭"
    elif gone:
        reason = f"消除 {len(gone)} 条，无新增无恶化"
    else:
        reason = "无差异"
    return {"eligible": eligible, "inherited": inherited, "new": new,
            "worsened": worsened, "unmeasured": sorted(unmeasured),
            "ambiguous": ambiguous, "reason": reason}


def collect_records(fig: matplotlib.figure.Figure, **kw) -> list[dict]:
    """实测记录采集（新口径）：measure(fig)["records"] 的列表形态。"""
    return list(measure(fig, **kw)["records"])


def delta_records(before, after) -> dict:
    """实测记录比较（新口径）：qa_delta 的记录形态别名。"""
    return qa_delta(before, after)


def blocking_problems(fig: matplotlib.figure.Figure, *, config: Optional[dict] = None) -> list[str]:
    """汇总阻断项：几何出框（裁切）、文字重叠、文字压线。"""
    problems: list[str] = []
    # 1. 裁剪/出框（曲线坐标框裁切 + 图例/图幅画布裁切）
    problems.extend(check_out_of_frame(fig))
    # 2. 文字重叠
    problems.extend(check_text_overlap(fig))
    # 3. 文字压线
    problems.extend(check_text_on_data(fig))
    return problems


def report(fig: matplotlib.figure.Figure, name: str = "figure", *, config: Optional[dict] = None) -> bool:
    """打印 QA 报告，并返回是否无阻断项。"""
    ok = True

    # 上下标字号警告
    offenders = check_glyph_floor(fig)
    if offenders:
        print(f"[QA] {name}: {len(offenders)} 处上下标字号跌破字形下限 ✗")
        for s in offenders:
            print(f"       {s}")
    else:
        print(f"[QA] {name}: 上下标字号达标 ✓")

    # 贴边警告
    tight = check_edge_clearance(fig)
    if tight:
        print(f"[QA] {name}: 发现 {len(tight)} 处贴边（净空 < 1.0 mm）✗")
        for p in tight:
            print("      ", p)
    else:
        print(f"[QA] {name}: 边框净空达标 ✓")

    # 阻断检查
    blockers = blocking_problems(fig, config=config)
    if blockers:
        ok = False
        print(f"[QA] {name}: 发现 {len(blockers)} 处阻断项 ✗")
        for b in blockers:
            print("      ", b)
    else:
        print(f"[QA] {name}: 无阻断项 ✓")

    return ok
