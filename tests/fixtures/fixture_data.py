"""夹具科学载荷：全部由固定种子现算，不读任何仪器原始文件。

这里只有**数据**，没有 Figure、没有配置、没有任何输出副作用。原生夹具脚本
（native_ftir / native_nmr / native_panels / native_mixed / native_negatives）
通过 `load_science()` 各自调用本模块，取得自己那份受保护的数组与文本。

受保护的事实（测试与任务期望都引用这些名字）：
- FTIR：三条曲线共用同一条**严格递减**的波数网格；带位窗口（cm⁻¹）是显示窗口。
- NMR：峰位（ppm）与积分窗口；归属文本；谱线本身。
- 显微图：四张**固定种子**的 uint8 RGB 数组、每张的视野宽度（µm）＝裁切语义、
  比例尺代表的物理长度（µm）。
"""
from __future__ import annotations

import hashlib
from functools import lru_cache

import numpy as np

#: 固定种子。改它 = 所有科学签名一起动；夹具测试会直接失败，这是故意的。
SEED = 20261010

# ── FTIR ────────────────────────────────────────────────────────────────────
FTIR_CURVE_IDS = ("a", "b", "c")
FTIR_N = 240
#: 波数轴**递减**（光谱惯例）：4000 → 400 cm⁻¹。
FTIR_X_FIRST, FTIR_X_LAST = 4000.0, 400.0
#: 带位窗口 (下界, 上界, 身份 id)：窗口是受保护的显示窗口，不是装饰。
FTIR_BANDS = (
    (3200.0, 3550.0, "oh"),
    (1580.0, 1680.0, "coo_cc"),
    (1000.0, 1100.0, "coc"),
    (400.0, 560.0, "zn_o"),
)
FTIR_XLIM = (4000.0, 400.0)
#: 纵向范围留出真实毫米的位移余量（曲线数据只占中间一段）。
FTIR_YLIM = (-1.6, 1.8)
#: 带位标签的数据锚点高度（a.u.）：在所有曲线之上，标签只再叠一个**毫米**位移。
FTIR_LABEL_Y = 1.50
#: 带位文本：受保护的科学文本（改字 = 改了这张图在说什么）。
FTIR_BAND_TEXT = {
    "oh": "O–H",
    "coo_cc": "COO$^{-}$/C=C",
    "coc": "C–O–C",
    "zn_o": "Zn–O",
}
#: 吸收带 (中心 cm⁻¹, 宽度 cm⁻¹, 幅度)。
_FTIR_BANDS_SHAPE = ((3300.0, 90.0, 0.50), (1650.0, 25.0, 0.35), (1050.0, 40.0, 0.60))
#: 堆叠台阶的基线（a.u.）：三条曲线本身是分开画的同一物理量。
_FTIR_BASE = (0.0, -0.60, -1.20)

# ── NMR ─────────────────────────────────────────────────────────────────────
NMR_N = 800
#: 化学位移轴同样递减：8.0 → 0.5 ppm。
NMR_PPM_FIRST, NMR_PPM_LAST = 8.0, 0.5
#: (峰位 ppm, 幅度, 半宽 ppm, 归属氢数)。
NMR_PEAKS = (
    (7.26, 1.00, 0.012, "1H"),
    (3.91, 0.60, 0.010, "3H"),
    (2.02, 0.45, 0.014, "3H"),
    (1.18, 0.80, 0.016, "3H"),
)
#: 受保护的积分窗口半宽（ppm）：窗口一变，"归属"这件事就不是同一件事了。
NMR_WINDOW_PPM = 0.06
NMR_XLIM = (8.0, 0.5)
NMR_YLIM = (-0.10, 1.35)

# ── 显微图 ──────────────────────────────────────────────────────────────────
PANEL_IDS = ("a", "b", "c", "d")
#: (高, 宽, 通道)：四张图**形状相同**，内容不同。
PANEL_SHAPE = (200, 260, 3)
#: 每个像素代表的物理长度（µm/px）——裁切语义的一半。
PANEL_UM_PER_PX = {"a": 0.20, "b": 0.10, "c": 0.05, "d": 0.40}
#: 比例尺代表的物理长度（µm）——比例尺语义。
SCALE_BAR_UM = 10.0


# ── 反序插值（修好的那处） ───────────────────────────────────────────────────
def interp_descending(x, y, xq: float) -> float:
    """在**递减**网格上取值。

    `np.interp` 只接受升序 xp：拿递减的波数/化学位移轴喂给它，返回的是
    毫无意义的数（旧夹具就是这么在谱线上放探针文字的）。这里先反序再插值，
    并且对"不是严格递减"的输入直接报错，免得修好的地方又被悄悄改回去。
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if x.ndim != 1 or y.shape != x.shape or x.size < 2:
        raise ValueError(f"x/y 必须是一维等长数组（>=2 点）；得到 {x.shape} / {y.shape}")
    if not np.all(np.diff(x) < 0):
        raise ValueError("interp_descending 只接受严格递减的 x 网格")
    return float(np.interp(xq, x[::-1], y[::-1]))


# ── FTIR 数据 ───────────────────────────────────────────────────────────────
def ftir_x() -> np.ndarray:
    """三条曲线共用的波数网格：严格递减，不含重复点。"""
    return np.linspace(FTIR_X_FIRST, FTIR_X_LAST, FTIR_N)


def ftir_curves() -> list[tuple[np.ndarray, np.ndarray]]:
    """三条透过率风格曲线；x 与 `ftir_x()` 逐位相同（同一条网网格）。"""
    rng = np.random.default_rng(SEED)
    x = ftir_x()
    out: list[tuple[np.ndarray, np.ndarray]] = []
    for base in _FTIR_BASE:
        y = np.zeros(FTIR_N, dtype=float)
        for center, width, amp in _FTIR_BANDS_SHAPE:
            y += amp * np.exp(-0.5 * ((x - center) / width) ** 2)
        y += 0.02 * rng.standard_normal(FTIR_N)  # 确定性"噪声"
        out.append((x, base + np.clip(1.0 - y, -0.25, 1.05)))
    return out


def ftir_band_limits() -> dict[str, tuple[float, float]]:
    """带位窗口（cm⁻¹）：受保护的显示窗口，不是排版参数。"""
    return {bid: (float(lo), float(hi)) for lo, hi, bid in FTIR_BANDS}


def ftir_band_centers() -> dict[str, float]:
    limits = ftir_band_limits()
    return {bid: 0.5 * (lo + hi) for bid, (lo, hi) in limits.items()}


def ftir_curve_values_at(curve: int, xq: float) -> float:
    """曲线在某个波数处的值（走修好的反序插值）。"""
    x, y = ftir_curves()[curve]
    return interp_descending(x, y, xq)


#: "处理后"对照用的平滑窗宽（点数，奇数）。
FTIR_PROCESS_WINDOW = 5


def ftir_processed_curves() -> list[tuple[np.ndarray, np.ndarray]]:
    """合成的"仪器处理后"对照：对同一条曲线做 `FTIR_PROCESS_WINDOW` 点滑动平均。

    处理链在这里声明**一次**（夹具的 `science_manifest` 也照抄这一句）：只有
    滑动平均，没有基线漂移、没有归一化、没有重采样、没有点数变化。
    边界用端点复制填充，所以"处理后"与"原始"的 x 网格逐位相同。
    """
    window = FTIR_PROCESS_WINDOW
    if window % 2 != 1 or window < 3:
        raise ValueError("平滑窗宽必须是 >=3 的奇数")
    kernel = np.full(window, 1.0 / window)
    pad = window // 2
    out: list[tuple[np.ndarray, np.ndarray]] = []
    for x, y in ftir_curves():
        padded = np.concatenate([np.full(pad, y[0]), y, np.full(pad, y[-1])])
        out.append((x, np.convolve(padded, kernel, mode="valid")))
    return out


# ── NMR 数据 ────────────────────────────────────────────────────────────────
def nmr_spectrum() -> tuple[np.ndarray, np.ndarray]:
    """洛伦兹峰叠加谱：ppm 轴严格递减。"""
    rng = np.random.default_rng(SEED + 1)
    x = np.linspace(NMR_PPM_FIRST, NMR_PPM_LAST, NMR_N)
    y = np.zeros(NMR_N, dtype=float)
    for ppm, amp, width, _ in NMR_PEAKS:
        y += amp * (width ** 2) / ((x - ppm) ** 2 + width ** 2)
    y += 0.004 * rng.standard_normal(NMR_N)
    return x, y


def nmr_peak_ppm() -> tuple[float, ...]:
    """峰位签名：与 scope、位移、字号、画布全部无关。"""
    return tuple(float(p) for p, _, _, _ in NMR_PEAKS)


def nmr_peak_heights() -> tuple[float, ...]:
    """每个峰位的谱线高度（反序插值取回）。"""
    x, y = nmr_spectrum()
    return tuple(interp_descending(x, y, ppm) for ppm in nmr_peak_ppm())


def nmr_windows_ppm() -> tuple[tuple[float, float], ...]:
    """受保护的积分窗口（ppm）。"""
    return tuple((ppm - NMR_WINDOW_PPM, ppm + NMR_WINDOW_PPM) for ppm in nmr_peak_ppm())


def nmr_assignments() -> dict[str, str]:
    """归属文本：受保护的**科学文本**，排版可以挪位置、不可以改字。"""
    return {f"{ppm:.2f}": f"{ppm:.2f} ({h})" for ppm, _, _, h in NMR_PEAKS}


# ── 显微图数据 ──────────────────────────────────────────────────────────────
@lru_cache(maxsize=None)
def micrograph(panel_id: str) -> np.ndarray:
    """固定种子的 uint8 RGB 图：同 id 每次返回**同一个数组对象**。

    只读返回：图元层若在原数组上就地改写，`im.get_array()` 的下一次读
    立刻就能看出（也才能把"像素字节不变"测成真事）。
    """
    if panel_id not in PANEL_IDS:
        raise ValueError(f"未知面板 {panel_id!r}；可用：{list(PANEL_IDS)}")
    index = PANEL_IDS.index(panel_id)
    rng = np.random.default_rng(SEED + 100 + index)
    height, width, _ = PANEL_SHAPE
    yy, xx = np.mgrid[0:height, 0:width]
    field = np.zeros((height, width), dtype=float)
    for _ in range(16 + 5 * index):
        cx = float(rng.uniform(0.0, width))
        cy = float(rng.uniform(0.0, height))
        radius = float(rng.uniform(7.0, 24.0))
        amp = float(rng.uniform(0.35, 1.00))
        field += amp * np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / (2.0 * radius * radius))
    field += 0.05 * rng.standard_normal((height, width))
    low, high = float(field.min()), float(field.max())
    scaled = (field - low) / (high - low)
    red = (scaled * 235.0 + 10.0).astype(np.uint8)
    green = (scaled * 215.0 + 25.0).astype(np.uint8)
    blue = (scaled * 195.0 + 35.0).astype(np.uint8)
    img = np.stack([red, green, blue], axis=-1)
    img.setflags(write=False)
    return img


def panel_field_width_um(panel_id: str) -> float:
    """面板裁切窗口的物理宽度（µm）：整幅视野 = 全像素。"""
    if panel_id not in PANEL_IDS:
        raise ValueError(f"未知面板 {panel_id!r}；可用：{list(PANEL_IDS)}")
    return float(PANEL_SHAPE[1]) * float(PANEL_UM_PER_PX[panel_id])


def scale_bar_fraction(panel_id: str) -> float:
    """比例尺占面板显示宽度的比例：由**物理语义**（µm）反推，不是拍脑袋的。"""
    return SCALE_BAR_UM / panel_field_width_um(panel_id)


# ── 指纹 ────────────────────────────────────────────────────────────────────
def array_digest(array: np.ndarray) -> str:
    """数组字节的 SHA256：测"科学载荷在排版前后逐字节不变"用。"""
    return hashlib.sha256(np.ascontiguousarray(array).tobytes()).hexdigest()


def science_digest() -> dict[str, str]:
    """全部受保护数组的指纹（不含任何显示参数）。"""
    digest: dict[str, str] = {}
    for sid, (x, y) in zip(FTIR_CURVE_IDS, ftir_curves()):
        digest[f"ftir.{sid}.x"] = array_digest(x)
        digest[f"ftir.{sid}.y"] = array_digest(y)
        digest[f"ftir.{sid}.processed.y"] = array_digest(ftir_processed_curves()[FTIR_CURVE_IDS.index(sid)][1])
    x_nmr, y_nmr = nmr_spectrum()
    digest["nmr.x"] = array_digest(x_nmr)
    digest["nmr.y"] = array_digest(y_nmr)
    for pid in PANEL_IDS:
        digest[f"panel.{pid}"] = array_digest(micrograph(pid))
    return digest
