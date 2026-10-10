"""确定性合成数据：FTIR 风格曲线、NMR 风格峰、柱图。

全部由 `numpy.random.default_rng(固定种子)` 生成，同种子同结果；
不需要任何仪器原始文件，体积为 0（数据在内存里现算）。

导出签名（供测试核对**形状**与**峰位不变**）：
    synthetic_curves()  -> list[(x, y)]      # 3 条 FTIR 透过率曲线
    nmr_spectrum()      -> (x, y)            # NMR 洛伦兹峰
    nmr_peak_ppm()      -> tuple[float, ...] # 峰位，绝不随 scope / 显示参数变化
    bar_series()        -> (labels, values, errors)
    export_signature()  -> dict              # 上面全部要点打包
"""
from __future__ import annotations

import numpy as np

#: 固定种子。改它 = 所有回归基线一起动，别随手改。
SEED = 20261010

CURVE_IDS = ("a", "b", "c")
#: NMR 峰位（ppm）**只在这里定义一次**：任何 scope / 位移都不许改它。
NMR_PEAK_PPM = (7.26, 3.91, 2.02, 1.18)
BAR_LABELS = ("ctrl", "dose_1", "dose_2", "dose_3")

N_CURVE_POINTS = 180
N_NMR_POINTS = 600

#: FTIR 吸收带 (中心 cm⁻¹, 宽度, 幅度)。
_BANDS = ((3300.0, 90.0, 0.50), (1650.0, 25.0, 0.35), (1050.0, 40.0, 0.60))
#: NMR 峰 (ppm, 幅度, 半宽)。
_NMR_PEAKS = ((7.26, 1.00, 0.012), (3.91, 0.60, 0.010), (2.02, 0.45, 0.014), (1.18, 0.80, 0.016))


def synthetic_curves(n_points: int = N_CURVE_POINTS, seed: int = SEED) -> list[tuple[np.ndarray, np.ndarray]]:
    """三条 FTIR 风格曲线，x 从 4000 递减到 400 cm⁻¹；返回 [(x, y), ...]。

    x 轴对三条曲线**完全一致**（同一条 linspace）：scope / 位移只动显示，不动数据。
    """
    rng = np.random.default_rng(seed)
    x = np.linspace(4000.0, 400.0, n_points)
    out: list[tuple[np.ndarray, np.ndarray]] = []
    for i in range(len(CURVE_IDS)):
        y = np.zeros(n_points, dtype=float)
        for center, width, amp in _BANDS:
            y += amp * np.exp(-0.5 * ((x - center) / width) ** 2)
        y += 0.02 * rng.standard_normal(n_points)  # 确定性“噪声”
        out.append((x, np.clip(1.0 - y - 0.6 * i, -0.85, 1.2)))
    return out


def nmr_spectrum(n_points: int = N_NMR_POINTS, seed: int = SEED) -> tuple[np.ndarray, np.ndarray]:
    """NMR 风格洛伦兹峰：ppm 从 8.0 递减到 0.5。峰位见 `nmr_peak_ppm()`。"""
    rng = np.random.default_rng(seed + 1)
    x = np.linspace(8.0, 0.5, n_points)
    y = np.zeros(n_points, dtype=float)
    for ppm, amp, width in _NMR_PEAKS:
        y += amp * (width ** 2) / ((x - ppm) ** 2 + width ** 2)
    y += 0.004 * rng.standard_normal(n_points)
    return x, y


def nmr_peak_ppm() -> tuple[float, ...]:
    """峰位签名：与 scope、位移、字号、画布全部无关。"""
    return tuple(float(p) for p in NMR_PEAK_PPM)


def bar_series(seed: int = SEED) -> tuple[tuple[str, ...], np.ndarray, np.ndarray]:
    """柱图素材：(标签, 均值, 误差棒)。"""
    rng = np.random.default_rng(seed + 2)
    values = np.round(np.array([1.00, 1.42, 1.85, 1.31]) + 0.02 * rng.standard_normal(len(BAR_LABELS)), 3)
    errors = np.round(np.full(len(BAR_LABELS), 0.08), 3)
    return BAR_LABELS, values, errors


def export_signature() -> dict:
    """把“测试要守住的东西”打成一份可比较的签名：形状 + 峰位 + 柱值。"""
    curves = synthetic_curves()
    x_nmr, y_nmr = nmr_spectrum()
    labels, values, errors = bar_series()
    return {
        "n_curves": len(curves),
        "curve_shapes": [[int(c.shape[0])] for c, _ in curves],
        "curve_x_first_last": [float(curves[0][0][0]), float(curves[0][0][-1])],
        "nmr_shape": [int(x_nmr.shape[0]), int(y_nmr.shape[0])],
        "nmr_peak_ppm": list(nmr_peak_ppm()),
        "bar_labels": list(labels),
        "bar_values": [float(v) for v in values],
        "bar_errors": [float(e) for e in errors],
    }
