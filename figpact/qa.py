"""图表质量检查 (QA) 判据与报告。"""
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
import numpy as np
import matplotlib.figure
from figpact.units import MM_PER_INCH


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


def check_out_of_frame(fig: matplotlib.figure.Figure, *, gid_filter: Optional[Any] = None) -> list[str]:
    """检查对象是否超出坐标轴框架（裁切）。显示坐标实测。"""
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
        if leg is not None:
            leg_gid = leg.get_gid() or "legend"
            if gid_filter is None or (callable(gid_filter) and gid_filter(leg_gid)) or (isinstance(gid_filter, str) and gid_filter in leg_gid):
                watched.append((leg_gid, leg))

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


def blocking_problems(fig: matplotlib.figure.Figure, *, config: Optional[dict] = None) -> list[str]:
    """汇总阻断项：几何出框（裁切）、文字重叠、文字压线。"""
    problems: list[str] = []
    # 1. 裁剪/出框（包含曲线与图例）
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
