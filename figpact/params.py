"""参数导出与覆盖审计模块。"""
import ast
import importlib.util
import inspect
import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any, Optional

import yaml
import matplotlib.text
import matplotlib.lines
import matplotlib.patches
import matplotlib.legend
import matplotlib.spines
import matplotlib.axis
import matplotlib.figure

from figpact.registry import GidRegistry


def _load_script_and_config(script_path: Path, config_path: Optional[Path] = None):
    """静默加载绘图脚本与配置，获取模块对象与当前配置字典。"""
    script_p = Path(script_path).resolve()
    cfg_p = Path(config_path).resolve() if config_path else None

    spec = importlib.util.spec_from_file_location(script_p.stem, script_p)
    if not spec or not spec.loader:
        raise RuntimeError(f"无法为脚本创建 loader: {script_p}")
    mod = importlib.util.module_from_spec(spec)

    old_argv = list(sys.argv)
    cmd_argv = [script_p.name, "--inventory"]
    if cfg_p and cfg_p.is_file():
        cmd_argv.extend(["--config", str(cfg_p)])
    sys.argv = cmd_argv

    f = io.StringIO()
    with redirect_stdout(f):
        try:
            spec.loader.exec_module(mod)
        except SystemExit:
            pass
        finally:
            sys.argv = old_argv

    # 读取当前配置
    if cfg_p and cfg_p.is_file():
        cur_cfg = yaml.safe_load(cfg_p.read_text(encoding="utf-8")) or {}
    else:
        cur_cfg = getattr(mod, "CONFIG", {}) or {}

    return mod, cur_cfg


def _extract_groups_from_mod(mod: Any) -> list[tuple[str, list]]:
    """从脚本模块的 list_params 函数 AST 中提取 groups 声明，并在模块命名空间中求值。"""
    fn = getattr(mod, "list_params", None)
    if not fn:
        return []
    try:
        src = inspect.getsource(fn)
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name) and t.id == "groups":
                        code = compile(ast.Expression(node.value), "<ast>", "eval")
                        return eval(code, mod.__dict__)
    except Exception:
        pass
    return []


def export_params_catalog(script_path: Path, config_path: Optional[Path] = None) -> dict[str, Any]:
    """从脚本与配置导出参数全集数据结构。

    结构组织：按 图 (figure) -> scope -> 分组 (group) -> 参数列表 (params)。
    """
    mod, cur_cfg = _load_script_and_config(script_path, config_path)

    fig_id = getattr(mod, "FIGURE_ID", script_path.stem)
    scopes = list(getattr(mod, "SCOPES", ("main",)))
    groups_def = _extract_groups_from_mod(mod)
    scalars = getattr(mod, "SCALARS", {})

    # 1. 标量参数按分组提取
    scalar_groups: list[dict[str, Any]] = []
    handled_keys = set()
    for g_title, items in groups_def:
        param_list = []
        for key, cname, unit, (lo, hi), desc in items:
            handled_keys.add(key)
            val = cur_cfg.get(key)
            p_type = "int" if isinstance(scalars.get(key, (float,))[0], type) and scalars.get(key)[0] is int else "float"
            step = 1 if p_type == "int" else (0.05 if "anchor" in key or "width" in key or "pt" in key else 0.1)
            param_list.append({
                "key": key,
                "path": [key],
                "中文名": cname,
                "所属可见对象分组": g_title,
                "类型": p_type,
                "单位": unit,
                "min": lo,
                "max": hi,
                "step": step,
                "当前值": val,
                "调大会怎样": desc,
            })
        scalar_groups.append({
            "group": g_title,
            "params": param_list,
        })

    # 2. 布尔开关参数
    bool_keys = getattr(mod, "BOOL_KEYS", ())
    if bool_keys:
        bool_list = []
        for bk in bool_keys:
            handled_keys.add(bk)
            val = bool(cur_cfg.get(bk, False))
            bool_list.append({
                "key": bk,
                "path": [bk],
                "中文名": "标注显示ppm后缀" if bk == "show_ppm" else bk,
                "所属可见对象分组": "开关 (Booleans)",
                "类型": "bool",
                "单位": "",
                "min": None,
                "max": None,
                "step": None,
                "当前值": val,
                "调大会怎样": "设为 true 标注带 ppm 数值（更宽），false 只显示基团名（窄约 40%）",
            })
        scalar_groups.append({
            "group": "开关 (Booleans)",
            "params": bool_list,
        })

    # 3. 按 scope 组装
    scopes_data = {}
    shift_limit = getattr(mod, "SHIFT_LIMIT_MM", 10.0)

    for sc in scopes:
        # 深拷贝标量分组给该 scope
        sc_groups = json.loads(json.dumps(scalar_groups, ensure_ascii=False))

        # 为当前 scope 添加位移参数分组
        shifts_cfg = cur_cfg.get("shifts_mm", {}) or {}
        sc_shifts = shifts_cfg.get(sc, {}) or {}
        shift_params = []

        # 曲线位移 (FTIR) 或整层位移 (NMR)
        curve_ids = getattr(mod, "CURVE_IDS", None)
        sample_ids = getattr(mod, "SAMPLE_IDS", None)
        target_ids = sample_ids or curve_ids or ()

        for sid in target_ids:
            cur_val = sc_shifts.get(sid, 0.0)
            shift_params.append({
                "key": f"shifts_mm.{sc}.{sid}",
                "path": ["shifts_mm", sc, sid],
                "中文名": f"层位移 ({sid})" if sample_ids else f"曲线位移 ({sid})",
                "所属可见对象分组": "位移 (Shifts)",
                "类型": "float",
                "单位": "mm",
                "min": -shift_limit,
                "max": shift_limit,
                "step": 0.1,
                "当前值": cur_val,
                "调大会怎样": f"仅 {sid} 整组图元纯显示向上平移指定毫米，不动科研数据",
            })

        # 逐标注微调 (NMR 独有)
        peak_label_shifts = cur_cfg.get("peak_label_shifts_mm", {}) or {}
        sc_peak_shifts = peak_label_shifts.get(sc, {}) or {}
        peak_templates = getattr(mod, "PEAK_LABELS_TEMPLATE", ())
        samples_cfg = getattr(mod, "SAMPLES_CONFIG", ())
        gid_tag_fn = getattr(mod, "_gid_tag", lambda ppm: f"{ppm:.2f}".replace(".", "p"))

        for _ppm, _idx, _grp, *_ in peak_templates:
            _sid = samples_cfg[_idx][7] if _idx < len(samples_cfg) else "sample"
            tag = gid_tag_fn(_ppm)
            short_gid = f"peak.{_sid}.{tag}"
            cur_pair = sc_peak_shifts.get(short_gid, [0.0, 0.0])
            shift_params.append({
                "key": f"peak_label_shifts_mm.{sc}.{short_gid}",
                "path": ["peak_label_shifts_mm", sc, short_gid],
                "中文名": f"标注微调 {short_gid} ({_grp})",
                "所属可见对象分组": "标注位移 (Peak Label Shifts)",
                "类型": "[dx,dy]",
                "单位": "mm",
                "min": -shift_limit,
                "max": shift_limit,
                "step": 0.1,
                "当前值": cur_pair,
                "调大会怎样": f"标注 {short_gid} 独立微调 [dx, dy] 毫米，引线自动跟随重新连接",
            })

        if shift_params:
            sc_groups.append({
                "group": "位移微调 (Shifts & Offsets)",
                "params": shift_params,
            })

        scopes_data[sc] = {
            "scope": sc,
            "groups": sc_groups,
        }

    return {
        "figure": fig_id,
        "script": str(script_path),
        "config": str(config_path) if config_path else "",
        "scopes": scopes_data,
    }


def audit_artists_coverage(script_path: Path, config_path: Optional[Path] = None) -> dict[str, Any]:
    """渲染后遍历 Figure 中所有可见 artist 的可调属性，归入五类并生成审计数据。"""
    mod, cur_cfg = _load_script_and_config(script_path, config_path)

    fig = getattr(mod, "fig", None)
    reg = getattr(mod, "reg", None)
    if fig is None and hasattr(mod, "build_figure_and_registry"):
        fig, reg = mod.build_figure_and_registry("annotated")

    if fig is None or reg is None:
        raise RuntimeError(f"未能从 {script_path} 获取 Figure 与 GidRegistry")

    try:
        fig.canvas.draw()
    except Exception:
        pass

    # 收集全部可见 artist 的属性
    entries = []
    # 类别常量
    CAT_YAML = "已暴露为 YAML 参数"
    CAT_GLOBAL = "全局样式（figure_style 统一）"
    CAT_SCIENCE = "科学锁定（峰位、显示窗、归一化、归属）"
    CAT_DERIVED = "由其他参数派生"
    CAT_UNCOVERED = "未覆盖"

    for ax in fig.axes:
        for art in ax.get_children():
            if not getattr(art, "get_visible", lambda: True)():
                continue
            gid = getattr(art, "get_gid", lambda: None)()
            art_type = type(art).__name__

            # 1. 过滤 ax 内部辅助私有 Text（空标题等）
            if isinstance(art, matplotlib.text.Text):
                txt = art.get_text().strip()
                if not txt and gid is None:
                    continue

            # 2. 轴背景 Rectangle
            if isinstance(art, matplotlib.patches.Rectangle) and art is ax.patch:
                entries.append({
                    "artist_type": "AxesPatch",
                    "gid": "axes.patch",
                    "property": "facecolor / edgecolor (坐标轴背景颜色)",
                    "category": CAT_GLOBAL,
                    "reason": "由 figure_style / rcParams 统一设定为白色无边框背景",
                })
                continue

            # 3. 边框 Spines
            if isinstance(art, matplotlib.spines.Spine):
                s_name = art.spine_type
                entries.append({
                    "artist_type": f"Spine({s_name})",
                    "gid": f"axes.spine.{s_name}",
                    "property": "linewidth / color (边框线宽与颜色)",
                    "category": CAT_GLOBAL,
                    "reason": "边框线宽由 figure_style.apply() 的 rcParams axes.linewidth 统一锁死",
                })
                entries.append({
                    "artist_type": f"Spine({s_name})",
                    "gid": f"axes.spine.{s_name}.visible",
                    "property": "visible (边框可见性开关)",
                    "category": CAT_UNCOVERED,
                    "suggestion": "建议归类：全局样式（figure_style 统一四边框封闭原则）",
                    "reason": "未在 YAML 中暴露开关，代码中默认全开",
                })
                continue

            # 4. 坐标轴 XAxis / YAxis
            if isinstance(art, (matplotlib.axis.XAxis, matplotlib.axis.YAxis)):
                ax_name = "XAxis" if isinstance(art, matplotlib.axis.XAxis) else "YAxis"
                # 轴范围
                entries.append({
                    "artist_type": ax_name,
                    "gid": f"axes.{ax_name.lower()}.limits",
                    "property": "view limits (显示范围)",
                    "category": CAT_SCIENCE,
                    "reason": "光谱/核磁化学位移显示窗（如 FTIR 4000-400 cm⁻¹，NMR 0-10.5 ppm）是科学量，锁定不可调",
                })
                # 刻度线与主刻度
                entries.append({
                    "artist_type": ax_name,
                    "gid": f"axes.{ax_name.lower()}.ticks",
                    "property": "tick direction / tick length / tick width",
                    "category": CAT_GLOBAL,
                    "reason": "刻度朝向、长度与线宽由 figure_style.apply() 的 rcParams 统一管辖",
                })
                # 刻度文字字号
                entries.append({
                    "artist_type": ax_name,
                    "gid": f"axes.{ax_name.lower()}.ticklabels",
                    "property": "fontsize (刻度数字字号)",
                    "category": CAT_YAML,
                    "reason": "已暴露为 YAML 参数 tick_font_pt",
                })
                # 次刻度与刻度密度
                entries.append({
                    "artist_type": ax_name,
                    "gid": f"axes.{ax_name.lower()}.minor_ticks",
                    "property": "minor_ticks / tick_density (次刻度开关与密度)",
                    "category": CAT_UNCOVERED,
                    "suggestion": "建议归类：全局样式（由 figure_style 统一配置 minor_locator，避免各图风格割裂）",
                    "reason": "未在 YAML 参数中暴露单独刻度步长调节项",
                })
                continue

            # 5. 图例 Legend
            if isinstance(art, matplotlib.legend.Legend):
                entries.append({
                    "artist_type": "Legend",
                    "gid": gid or "legend",
                    "property": "fontsize (图例字号)",
                    "category": CAT_YAML,
                    "reason": "已暴露为 YAML 参数 legend_font_pt",
                })
                entries.append({
                    "artist_type": "Legend",
                    "gid": gid or "legend",
                    "property": "ncols (图例列数)",
                    "category": CAT_YAML,
                    "reason": "已暴露为 YAML 参数 legend_cols",
                })
                entries.append({
                    "artist_type": "Legend",
                    "gid": gid or "legend",
                    "property": "bbox_to_anchor_x (水平锚点)",
                    "category": CAT_YAML,
                    "reason": "已暴露为 YAML 参数 legend_anchor_x",
                })
                entries.append({
                    "artist_type": "Legend",
                    "gid": gid or "legend",
                    "property": "frameon (图例外框)",
                    "category": CAT_GLOBAL,
                    "reason": "figure_style 规范固定为无外框 (frameon=False)",
                })
                entries.append({
                    "artist_type": "Legend",
                    "gid": gid or "legend",
                    "property": "vertical_position (图例纵向位置)",
                    "category": CAT_DERIVED,
                    "reason": "纵向固定在顶部 (0.98)，顶部净空由引擎排版统一求解",
                })
                entries.append({
                    "artist_type": "Legend",
                    "gid": gid or "legend",
                    "property": "handlelength / labelspacing (图例内部间距紧凑度)",
                    "category": CAT_UNCOVERED,
                    "suggestion": "建议归类：由其他参数派生（按 legend_font_pt 等比缩放，无需单独旋钮）",
                    "reason": "当前硬编码在 legend 调用参数中",
                })
                continue

            # 6. FTIR 官能团归属阴影带 (Rectangle)
            if isinstance(art, matplotlib.patches.Rectangle):
                bounds = art.get_bbox().bounds
                w = bounds[2]
                entries.append({
                    "artist_type": "Rectangle",
                    "gid": f"shade_band.{bounds[0]:.0f}_{bounds[0]+w:.0f}",
                    "property": "x_span (阴影带波段范围)",
                    "category": CAT_SCIENCE,
                    "reason": f"文献标准官能团红外吸收波数区间 [{bounds[0]:.0f}, {bounds[0]+w:.0f}] cm⁻¹ 为客观物理化学事实，科学锁定",
                })
                entries.append({
                    "artist_type": "Rectangle",
                    "gid": f"shade_band.{bounds[0]:.0f}_{bounds[0]+w:.0f}",
                    "property": "color / alpha (阴影填充色与透明度)",
                    "category": CAT_GLOBAL,
                    "reason": "由 figure_style.shade_band 统一使用全套标准灰色 (#BFBFBF, alpha=0.32)",
                })
                entries.append({
                    "artist_type": "Rectangle",
                    "gid": f"shade_band.{bounds[0]:.0f}_{bounds[0]+w:.0f}",
                    "property": "edgecolor / linestyle (阴影带两侧边界虚线)",
                    "category": CAT_UNCOVERED,
                    "suggestion": "建议归类：全局样式（统一默认无边界虚线，保持画面干净）",
                    "reason": "阴影带目前仅有填充面，无边界虚线控制属性",
                })
                continue

            # 7. 谱线与基线 (Line2D)
            if isinstance(art, matplotlib.lines.Line2D):
                pts = len(art.get_xdata())
                # 曲线
                if "curve" in (gid or "") or pts > 100:
                    entries.append({
                        "artist_type": "Line2D (Curve)",
                        "gid": gid or f"curve.{pts}",
                        "property": "linewidth (谱线线宽)",
                        "category": CAT_YAML,
                        "reason": "已暴露为 YAML 参数 line_width",
                    })
                    entries.append({
                        "artist_type": "Line2D (Curve)",
                        "gid": gid or f"curve.{pts}",
                        "property": "vertical_gap (垂直层间距)",
                        "category": CAT_YAML,
                        "reason": "已暴露为 YAML 参数 stack_gap / layer_gap",
                    })
                    entries.append({
                        "artist_type": "Line2D (Curve)",
                        "gid": gid or f"curve.{pts}",
                        "property": "display_shift_dy (纯显示位移)",
                        "category": CAT_YAML,
                        "reason": "已暴露为 YAML 参数 shifts_mm",
                    })
                    entries.append({
                        "artist_type": "Line2D (Curve)",
                        "gid": gid or f"curve.{pts}",
                        "property": "data_xy (波长/化学位移与吸光度数值)",
                        "category": CAT_SCIENCE,
                        "reason": "仪器采集原始物理数据、定标结果与吸光度转换，不可人为修改",
                    })
                    entries.append({
                        "artist_type": "Line2D (Curve)",
                        "gid": gid or f"curve.{pts}",
                        "property": "color (谱线系列颜色)",
                        "category": CAT_GLOBAL,
                        "reason": "由 figure_style.MATERIAL 调色板按样品材料属性全局统一分配",
                    })
                    entries.append({
                        "artist_type": "Line2D (Curve)",
                        "gid": gid or f"curve.{pts}",
                        "property": "solid_capstyle (曲线线端样式)",
                        "category": CAT_UNCOVERED,
                        "suggestion": "建议归类：全局样式（figure_style 统一 capstyle='round' 防毛刺）",
                        "reason": "未在 YAML 参数中开放单独线帽调节",
                    })
                    continue

                # 基线
                if "baseline" in (gid or ""):
                    entries.append({
                        "artist_type": "Line2D (Baseline)",
                        "gid": gid,
                        "property": "vertical_position (基线位置)",
                        "category": CAT_YAML,
                        "reason": "已暴露为 YAML 参数 layer_gap / shifts_mm",
                    })
                    entries.append({
                        "artist_type": "Line2D (Baseline)",
                        "gid": gid,
                        "property": "linestyle / linewidth / color",
                        "category": CAT_GLOBAL,
                        "reason": "虚线样式由 figure_style 全局统一 (#E2E2E2, lw=0.45, ls='--')",
                    })
                    continue

                # NMR 标注引线
                if "guide" in (gid or ""):
                    entries.append({
                        "artist_type": "Line2D (Guide)",
                        "gid": gid,
                        "property": "anchor_point (峰尖锚点坐标)",
                        "category": CAT_SCIENCE,
                        "reason": "引线起始端锚定在数学极大值峰尖坐标，由谱线数据实测确定，科学锁定",
                    })
                    entries.append({
                        "artist_type": "Line2D (Guide)",
                        "gid": gid,
                        "property": "target_point (标注文本连接端)",
                        "category": CAT_DERIVED,
                        "reason": "引线末端由标注文本避让位置与 peak_label_shifts_mm 几何推导派生跟随",
                    })
                    entries.append({
                        "artist_type": "Line2D (Guide)",
                        "gid": gid,
                        "property": "linewidth / color",
                        "category": CAT_GLOBAL,
                        "reason": "引线规格由全局规范统一 (lw=0.55, text color)",
                    })
                    entries.append({
                        "artist_type": "Line2D (Guide)",
                        "gid": gid,
                        "property": "linestyle (引线线型：实线/点虚线)",
                        "category": CAT_UNCOVERED,
                        "suggestion": "建议归类：全局样式（统一实线细线，避免视觉琐碎）",
                        "reason": "代码中固定为实线，未提供配置项",
                    })
                    continue

            # 8. 文本对象 (Text)
            if isinstance(art, matplotlib.text.Text):
                # 轴标题
                if art is ax.xaxis.label or "xlabel" in (gid or ""):
                    entries.append({
                        "artist_type": "Text (XLabel)",
                        "gid": gid or "axes.xlabel",
                        "property": "fontsize (轴标题字号)",
                        "category": CAT_YAML,
                        "reason": "已暴露为 YAML 参数 axis_font_pt",
                    })
                    entries.append({
                        "artist_type": "Text (XLabel)",
                        "gid": gid or "axes.xlabel",
                        "property": "content (标题内容文字与单位)",
                        "category": CAT_SCIENCE,
                        "reason": "物理量名称与单位定义（如 Wavenumber (cm⁻¹)、Chemical Shift δ (ppm)）属于科学事实，不可更改",
                    })
                    continue

                if art is ax.yaxis.label or "ylabel" in (gid or ""):
                    entries.append({
                        "artist_type": "Text (YLabel)",
                        "gid": gid or "axes.ylabel",
                        "property": "fontsize (轴标题字号)",
                        "category": CAT_YAML,
                        "reason": "已暴露为 YAML 参数 axis_font_pt",
                    })
                    entries.append({
                        "artist_type": "Text (YLabel)",
                        "gid": gid or "axes.ylabel",
                        "property": "content (标题内容文字与单位)",
                        "category": CAT_SCIENCE,
                        "reason": "物理量标准化单位（如 Transmittance (a.u.)、Normalized Intensity (a.u.)）属于科学事实，不可更改",
                    })
                    continue

                # 溶剂截顶标记 //
                if "break" in (gid or "") or art.get_text().strip() == "//":
                    entries.append({
                        "artist_type": "Text (Break)",
                        "gid": gid or "break_mark",
                        "property": "fontsize (截顶标记字号)",
                        "category": CAT_YAML,
                        "reason": "已暴露为 YAML 参数 note_font_pt",
                    })
                    entries.append({
                        "artist_type": "Text (Break)",
                        "gid": gid or "break_mark",
                        "property": "x_position (截顶标记横向位置)",
                        "category": CAT_SCIENCE,
                        "reason": "标记居中对齐在真实溶剂残留峰位（如 CDCl3 7.26 ppm, D2O 4.79 ppm），科学锁定",
                    })
                    entries.append({
                        "artist_type": "Text (Break)",
                        "gid": gid or "break_mark",
                        "property": "y_position (截顶标记垂直位置)",
                        "category": CAT_DERIVED,
                        "reason": "截顶垂直位置由溶剂截顶阈值 PEAK_MAX_NORM 与 layer_gap / shifts_mm 派生",
                    })
                    continue

                # 对照版小注
                if "title" in (gid or "") or "Vendor-processed" in art.get_text():
                    entries.append({
                        "artist_type": "Text (Note)",
                        "gid": gid or "note_title",
                        "property": "fontsize (小注说明字号)",
                        "category": CAT_YAML,
                        "reason": "已暴露为 YAML 参数 note_font_pt",
                    })
                    entries.append({
                        "artist_type": "Text (Note)",
                        "gid": gid or "note_title",
                        "property": "content (小注文字内容)",
                        "category": CAT_SCIENCE,
                        "reason": "说明文字属于学术严谨性声明，不可篡改",
                    })
                    continue

                # FTIR 官能团标签
                if "band" in (gid or ""):
                    entries.append({
                        "artist_type": "Text (BandLabel)",
                        "gid": gid,
                        "property": "fontsize (官能团字号)",
                        "category": CAT_YAML,
                        "reason": "已暴露为 YAML 参数 label_font_pt",
                    })
                    entries.append({
                        "artist_type": "Text (BandLabel)",
                        "gid": gid,
                        "property": "edge_margin (左右边框避让)",
                        "category": CAT_YAML,
                        "reason": "已暴露为 YAML 参数 label_edge_margin_mm",
                    })
                    entries.append({
                        "artist_type": "Text (BandLabel)",
                        "gid": gid,
                        "property": "top_clearance (图例下方净空)",
                        "category": CAT_YAML,
                        "reason": "已暴露为 YAML 参数 label_gap_top_mm",
                    })
                    entries.append({
                        "artist_type": "Text (BandLabel)",
                        "gid": gid,
                        "property": "content (官能团化学名称)",
                        "category": CAT_SCIENCE,
                        "reason": f"化学结构官能团归属文字 «{art.get_text()}» 属于实验解释，科学锁定",
                    })
                    entries.append({
                        "artist_type": "Text (BandLabel)",
                        "gid": gid,
                        "property": "tier_y (阶梯分层高度)",
                        "category": CAT_DERIVED,
                        "reason": "阶梯避让分层高度由文本实测包络框与排版算法派生求解",
                    })
                    entries.append({
                        "artist_type": "Text (BandLabel)",
                        "gid": gid,
                        "property": "rotation (标签文字倾斜角)",
                        "category": CAT_UNCOVERED,
                        "suggestion": "建议归类：全局样式（严格保持 0 度水平放置，期刊严禁斜字标签）",
                        "reason": "固定水平绘制，未暴露旋转角度参数",
                    })
                    continue

                # NMR 诊断峰标注
                if "peak" in (gid or ""):
                    entries.append({
                        "artist_type": "Text (PeakLabel)",
                        "gid": gid,
                        "property": "fontsize (峰标注字号)",
                        "category": CAT_YAML,
                        "reason": "已暴露为 YAML 参数 peak_font_pt",
                    })
                    entries.append({
                        "artist_type": "Text (PeakLabel)",
                        "gid": gid,
                        "property": "label_lift (离峰顶垂直净空)",
                        "category": CAT_YAML,
                        "reason": "已暴露为 YAML 参数 label_lift",
                    })
                    entries.append({
                        "artist_type": "Text (PeakLabel)",
                        "gid": gid,
                        "property": "label_min_gap_mm (横向最小避让净空)",
                        "category": CAT_YAML,
                        "reason": "已暴露为 YAML 参数 label_min_gap_mm",
                    })
                    entries.append({
                        "artist_type": "Text (PeakLabel)",
                        "gid": gid,
                        "property": "label_max_dx_mm (自动避让最大横移窗口)",
                        "category": CAT_YAML,
                        "reason": "已暴露为 YAML 参数 label_max_dx_mm",
                    })
                    entries.append({
                        "artist_type": "Text (PeakLabel)",
                        "gid": gid,
                        "property": "label_lanes (避让层数限制)",
                        "category": CAT_YAML,
                        "reason": "已暴露为 YAML 参数 label_lanes",
                    })
                    entries.append({
                        "artist_type": "Text (PeakLabel)",
                        "gid": gid,
                        "property": "ppm_suffix_visible (是否显示ppm读数)",
                        "category": CAT_YAML,
                        "reason": "已暴露为 YAML 参数 show_ppm",
                    })
                    entries.append({
                        "artist_type": "Text (PeakLabel)",
                        "gid": gid,
                        "property": "micro_shift_dx_dy (独立显示微移)",
                        "category": CAT_YAML,
                        "reason": "已暴露为 YAML 参数 peak_label_shifts_mm",
                    })
                    entries.append({
                        "artist_type": "Text (PeakLabel)",
                        "gid": gid,
                        "property": "group_name (化学基团名称)",
                        "category": CAT_SCIENCE,
                        "reason": f"基团归属 «{art.get_text()}» 属于论文解释核心，科学锁定",
                    })
                    entries.append({
                        "artist_type": "Text (PeakLabel)",
                        "gid": gid,
                        "property": "peak_ppm_detected (动态峰位读数)",
                        "category": CAT_SCIENCE,
                        "reason": "动态检测算法从谱线极大值提取的 ppm 数值属于实测数据，不可人为修改",
                    })
                    entries.append({
                        "artist_type": "Text (PeakLabel)",
                        "gid": gid,
                        "property": "rotation (峰标注旋转角)",
                        "category": CAT_UNCOVERED,
                        "suggestion": "建议归类：全局样式（统一水平摆放）",
                        "reason": "自动避让引擎默认水平计算包络盒，未开放文字旋转",
                    })
                    continue

                # 兜底可见 Text
                entries.append({
                    "artist_type": "Text",
                    "gid": gid or "unnamed_text",
                    "property": "content / format",
                    "category": CAT_UNCOVERED,
                    "suggestion": "建议归类：未覆盖（视内容归入科学内容或排版标签）",
                    "reason": f"未分类文本对象 «{art.get_text()[:30]}»",
                })

    # 统计五类分布
    stats = {
        CAT_YAML: 0,
        CAT_GLOBAL: 0,
        CAT_SCIENCE: 0,
        CAT_DERIVED: 0,
        CAT_UNCOVERED: 0,
    }
    for e in entries:
        cat = e["category"]
        stats[cat] = stats.get(cat, 0) + 1

    uncovered_list = [e for e in entries if e["category"] == CAT_UNCOVERED]

    return {
        "stats": stats,
        "total_properties": len(entries),
        "entries": entries,
        "uncovered": uncovered_list,
    }
