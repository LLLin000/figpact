"""G11 init-contract：自动发现可编辑入口 → 人工确认 → 扰动验证。

只做最小闭环，不做任意 Python 改写、不把"找到参数"当成"找到控制权"。

E✓（G11 定义）= 源码绑定存在 ∧ 实际扰动生效 ∧ 对象身份一致 ∧ 无意外副作用，
扰动必须是**非零变化**。Draft 文件默认未确认；未确认条目永不生效、
永不进入 plate 清单；扰动失败的条目永不升级。

复用既有路径，不新建对象识别/测量系统：
- 源码调用发现：标准库 ``ast``（只读解析，不改脚本）。
- 注册关系：脚本构建出的 ``GidRegistry``（``final_size._build_figure``）。
- 扰动与重建：``FigureSession.build_from_yaml``（真实临时 YAML + 整图重建）。
- 扰动量：``effects.probe_value``；几何/样式差分：``effects._geometry_changes``、
  ``effects._style_changes``。
- 目标/非目标角色实测：``plate._audit_code`` + ``plate._role_means``
  （与 compare 表完全同一口径）。
- 科学指纹：``FigureSession._capture_science/_compare_science``。
- QA：``qa.blocking_problems`` 前后对照。
- 写入（仅 plate unify --apply）：``final_size.apply_final_size`` +
  ``patch`` + ``source_writes``。

关于"无意外副作用"的口径（与 effects.check_effects 的区别）：
字号/线宽类样式参数的扰动必然改变包围盒尺寸，并可能引起同一坐标轴内
的确定性布局联动（如 tick 变宽带动 ylabel 平移）。这类联动满足以下条件时
记为"已记录的布局联动"，不否决验证，但必须逐条量化写入证据：
科学指纹不变、无新增 QA 阻断、非目标**角色**实测值不变、无结构增删、
注册表样式变化不超出声明对象。证据公开，任何人可复算复核。
"""
from __future__ import annotations

import ast
import copy
import io
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any, Optional

import yaml

DRAFT_SCHEMA = "contract-draft/1"

#: v0.1 发现范围：调用名 -> (角色, 期望参数键, artist 家族)
ENTRY_CALLS = {
    "set_xlabel": ("axis.title", "axis_font_pt", "xlabel"),
    "set_ylabel": ("axis.title", "axis_font_pt", "ylabel"),
    "set_title": ("axis.title", "axis_font_pt", "title"),
    "tick_params": ("axis.tick", "tick_font_pt", "ticklabels"),
    "plot": ("curve.linewidth", "line_width", "curve"),
}
#: 调用关键字：调用名 -> 承载字号/线宽的关键字
ENTRY_KWARG = {
    "set_xlabel": "fontsize", "set_ylabel": "fontsize", "set_title": "fontsize",
    "tick_params": "labelsize", "plot": "linewidth",
}
#: 已知可验证参数 -> 角色（复用 plate.ROLE_TO_PARAMS 的键）。
KNOWN_PARAM_ROLE = {
    "axis_font_pt": "axis.title",
    "tick_font_pt": "axis.tick",
    "line_width": "curve.linewidth",
}
#: 6 个角色分母（复用 plate.COMPARE_ROLES 的顺序与成员）。
DENOMINATOR_ROLES = ("axis.title", "axis.tick", "curve.linewidth",
                     "panel.label", "legend", "scalebar")
#: YAML 里属于角色但 v0.1 入口覆盖不到的键 -> 角色（系统化 unresolved，不猜）。
ROLE_PARAM_FALLBACK = {
    "label_font_pt": "panel.label", "peak_font_pt": "panel.label",
    "legend_font_pt": "legend",
}
#: 样式扰动可接受的几何家族：角色 -> drawn_shapes kind 关键字。
ROLE_GEOMETRY_FAMILY = {
    "axis.title": ("xlabel_envelope", "ylabel_envelope", "title_envelope"),
    "axis.tick": ("xtick_", "ytick_"),
    "curve.linewidth": ("polyline",),
}


# --------------------------------------------------------------------------- #
# discover（只读：AST + YAML + 一次构建拿注册表）
# --------------------------------------------------------------------------- #

def _call_name(node: ast.Call) -> Optional[str]:
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def _param_of_value(node: ast.AST) -> Any:
    """值节点 -> 参数键 / None(字面量) / 'UNKNOWN'(看不懂)。"""
    n = node
    if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            and n.func.id in ("float", "int") and n.args):
        n = n.args[0]
    if (isinstance(n, ast.Subscript) and isinstance(n.value, ast.Name)
            and n.value.id == "cfg"):
        s = n.slice
        if isinstance(s, ast.Constant) and isinstance(s.value, str):
            return s.value
        return "UNKNOWN"
    if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == "get" and isinstance(n.func.value, ast.Name)
            and n.func.value.id == "cfg" and n.args
            and isinstance(n.args[0], ast.Constant)):
        return n.args[0].value
    if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)) \
            and not isinstance(n.value, bool):
        return None
    return "UNKNOWN"


def _iter_calls(tree: ast.AST, source: str) -> list[dict]:
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node)
        if name not in ENTRY_CALLS:
            continue
        kw = ENTRY_KWARG[name]
        role, expect, family = ENTRY_CALLS[name]
        hit = None
        for k in node.keywords:
            if k.arg == kw:
                hit = k.value
                break
        if hit is None:
            out.append({"entry": name, "role": role, "expect": expect,
                        "family": family, "line": node.lineno,
                        "call": (ast.get_source_segment(source, node) or name)[:160],
                        "param": "UNKNOWN", "reason": f"{name}() 未见 {kw}=（非常见写法）"})
            continue
        param = _param_of_value(hit)
        out.append({"entry": name, "role": role, "expect": expect,
                    "family": family, "line": node.lineno,
                    "call": (ast.get_source_segment(source, node) or name)[:160],
                    "param": param,
                    "reason": None if param == expect else (
                        "字面量：无 YAML 绑定" if param is None else
                        f"参数 {param!r} 非 {expect}（超 v0.1 范围/写法不明）"
                        if isinstance(param, str) else "写法不明")})
    return out


def _unsupported_safety(tree: ast.AST, source: str) -> list[dict]:
    """安全锁定项：坐标窗口类调用，有也不许碰（证据，不是能力）。"""
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node)
        if name in ("set_xlim", "set_ylim", "set_zlim"):
            out.append({"kind": "safety", "role": None, "call": name,
                        "line": node.lineno,
                        "reason": f"{name}() 改坐标窗口：科学内容锁定，永不自动改"})
    return out


def discover(script: Any, config: Any, scope: Optional[str] = None) -> dict:
    """只读发现：返回 draft 字典（candidates/unresolved/unsupported/coverage）。"""
    from figpact import final_size as fs_mod

    script_p = Path(str(script)).expanduser().resolve()
    config_p = Path(str(config)).expanduser().resolve()
    source = script_p.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=script_p.name)
    raw_cfg = yaml.safe_load(config_p.read_text(encoding="utf-8")) or {}

    module = fs_mod._import_script(script_p)
    cfg = fs_mod._load_config(module, script_p, config_p)
    if scope is None:
        scopes = getattr(module, "SCOPES", None)
        scope = (scopes[0] if scopes else "main")
    (_fig_reg, _scope) = (None, scope)
    try:
        (fig, reg), scope = fs_mod._build_figure(module, cfg, scope)
    finally:
        pass
    try:
        gid_of_param: dict[str, list[str]] = {}
        for gid in reg.all():
            for key in reg.params_of(gid):
                gid_of_param.setdefault(key, []).append(gid)
    finally:
        import matplotlib.pyplot as plt
        plt.close(fig)

    calls = _iter_calls(tree, source)
    by_param: dict[str, list[dict]] = {}
    unresolved: list[dict] = []
    for c in calls:
        if c["param"] == c["expect"] and c["param"] in KNOWN_PARAM_ROLE:
            by_param.setdefault(c["param"], []).append(c)
        else:
            unresolved.append({
                "kind": "entry", "role": c["role"],
                "reason": c["reason"] or f"{c['entry']}() 无法确定可编辑绑定，不得猜",
                "location": {"file": script_p.name, "line": c["line"],
                             "call": c["call"]},
            })
    seen_yaml_keys = set()
    for key, val in (raw_cfg.items() if isinstance(raw_cfg, dict) else []):
        if key in KNOWN_PARAM_ROLE and key not in by_param:
            unresolved.append({
                "kind": "unwired", "role": KNOWN_PARAM_ROLE[key],
                "reason": f"YAML 有 {key}={val!r} 但未发现 v0.1 入口调用接线，不得猜",
                "location": {"file": config_p.name, "line": None, "call": None},
            })
        if key in ROLE_PARAM_FALLBACK:
            seen_yaml_keys.add(key)
    for key in sorted(seen_yaml_keys):
        unresolved.append({
            "kind": "out_of_scope", "role": ROLE_PARAM_FALLBACK[key],
            "reason": f"YAML 有 {key} 但其调用（annotate/legend 分支）超出 v0.1 发现范围，不得猜",
            "location": {"file": config_p.name, "line": None, "call": None},
        })

    candidates = []
    for param in sorted(by_param):
        locs = by_param[param]
        gids = sorted(gid_of_param.get(param, []))
        candidates.append({
            "role": KNOWN_PARAM_ROLE[param],
            "param": param,
            "source": [{"file": script_p.name, "line": c["line"],
                        "call": c["call"]} for c in sorted(locs, key=lambda d: d["line"])],
            "artist": {"gid": gids[0] if len(gids) == 1 else None,
                       "gids": gids,
                       "kind": locs[0]["family"],
                       "registered": bool(gids)},
            "confidence": "high" if gids else "medium",
            "confirmed": False, "verified": False, "evidence": None,
        })
    unsupported = _unsupported_safety(tree, source)
    unsupported.append({"kind": "noncode", "role": "scalebar",
                        "reason": "非显微图无 scalebar 角色；SVG/PNG 无源码入口（compare 只报告）"})
    draft = {
        "schema_version": DRAFT_SCHEMA,
        "script": str(script_p), "config": str(config_p), "scope": scope,
        "candidates": candidates, "unresolved": unresolved,
        "unsupported": unsupported,
        "coverage": _coverage(candidates, unresolved, unsupported),
    }
    return draft

# --------------------------------------------------------------------------- #
# coverage（分母恒为 6 角色，含未知/未覆盖）
# --------------------------------------------------------------------------- #

def _coverage(candidates: list[dict], unresolved: list[dict],
              unsupported: list[dict]) -> dict:
    verified = {c["role"] for c in candidates if c.get("verified")}
    cand = {c["role"] for c in candidates if not c.get("verified")}
    unres = {u.get("role") for u in unresolved if u.get("role")}
    unsup = {u.get("role") for u in unsupported if u.get("role")}
    # 每个角色只计一次，verified 优先。
    cand -= verified
    unres -= verified | cand
    unsup -= verified | cand | unres
    return {
        "verified_editable": sorted(verified),
        "candidate": sorted(cand),
        "unresolved": sorted(unres),
        "unsupported": sorted(unsup),
        "denominator_roles": list(DENOMINATOR_ROLES),
        "denominator_note": "分母恒为 6 个角色（含未发现/未覆盖），不得把没发现从分母剔除",
    }


def coverage_report(draft: dict) -> str:
    cov = draft.get("coverage") or {}
    lines = ["contract coverage（分母恒为 6 角色）："]
    for key in ("verified_editable", "candidate", "unresolved", "unsupported"):
        vals = cov.get(key, [])
        lines.append(f"- {key}: {len(vals)} {vals}")
    lines.append(f"- denominator: {cov.get('denominator_roles', [])}")
    lines.append(f"  {cov.get('denominator_note', '')}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# 已验证契约加载（清单用：只认 confirmed + verified 条目）
# --------------------------------------------------------------------------- #

def load_verified(path: Any) -> dict:
    """读 draft 文件，只返回人工确认且扰动验证通过的条目。"""
    p = Path(str(path)).expanduser().resolve()
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if data.get("schema_version") != DRAFT_SCHEMA:
        raise ValueError(f"未知 contract draft 版本：{data.get('schema_version')!r}")
    entries = []
    for c in data.get("candidates") or []:
        if c.get("confirmed") and c.get("verified"):
            entries.append(c)
    return {"path": str(p), "scope": data.get("scope"),
            "script": data.get("script"), "config": data.get("config"),
            "params": sorted({c["param"] for c in entries}),
            "entries": entries,
            "n_candidates": len(data.get("candidates") or [])}


# --------------------------------------------------------------------------- #
# verify（只读扰动验证：未确认不生效，失败不升级）
# --------------------------------------------------------------------------- #

def _role_means_of(script: str, config_path: str, scope: str,
                   width_mm: float) -> dict:
    from figpact import plate as plate_mod
    spec = {"label": "verify", "path": str(script), "config": str(config_path),
            "scope": scope}
    item = plate_mod._audit_code(spec, float(width_mm))
    return plate_mod._role_means(item)


def verify(path: Any, width_mm: Optional[float] = None) -> dict:
    """对 draft 里 confirmed 的条目做真实扰动验证，原地写回 verified/evidence。

    只读：扰动走临时 YAML，不写脚本/YAML源文件（只更新 draft 文件本身）。
    返回 {verified:[...], failed:[...], skipped_unconfirmed:n}。
    """
    from figpact import effects
    from figpact.qa import blocking_problems
    from figpact.session import FigureSession, drawn_shapes

    p = Path(str(path)).expanduser().resolve()
    draft = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    script, config, scope = draft["script"], draft["config"], draft["scope"]
    base_cfg = yaml.safe_load(Path(config).read_text(encoding="utf-8")) or {}
    if width_mm is None:
        width_mm = float(base_cfg.get("canvas_w_mm", 42.0))

    verified, failed, skipped = [], [], 0
    session: Optional[FigureSession] = None
    try:
        for cand in draft.get("candidates") or []:
            if not cand.get("confirmed"):
                skipped += 1
                continue
            if cand.get("verified"):
                verified.append(cand["param"])
                continue
            param, role = cand["param"], cand["role"]
            cur = base_cfg.get(param)
            if isinstance(cur, bool) or not isinstance(cur, (int, float)):
                cand["verified"] = False
                cand["evidence"] = {"failure": f"YAML 里 {param} 非有限数字：{cur!r}"}
                failed.append(param)
                continue
            from figpact import final_size as _fs
            _scal = getattr(_fs._import_script(Path(script)), "SCALARS", {}) or {}
            _b = _scal.get(param)
            _bounds = ({"min": _b[1], "max": _b[2]}
                       if isinstance(_b, tuple) and len(_b) == 3 else {})
            probe = effects.probe_value(_bounds, float(cur))
            if probe is None or probe == float(cur):
                cand["verified"] = False
                cand["evidence"] = {"failure": f"给不出非零有界扰动（当前 {cur}）"}
                failed.append(param)
                continue
            pert = copy.deepcopy(base_cfg)
            pert[param] = probe
            tmp = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False,
                                              encoding="utf8")
            try:
                yaml.safe_dump(pert, tmp, sort_keys=False, allow_unicode=True)
                tmp.close()
                if session is None:
                    session = FigureSession(script, config, scope)
                base_shapes = session._baseline["shapes"]
                base_styles = session._baseline["styles"]
                base_science = session._baseline["science"]
                base_qa = list(session._baseline["qa"]["qa"])
                base_gids = list(session._baseline["gids"])
                try:
                    with redirect_stdout(io.StringIO()):
                        fig, reg = session.build_from_yaml(tmp.name)
                except Exception as error:
                    cand["verified"] = False
                    cand["evidence"] = {
                        "failure": f"扰动重建失败：{type(error).__name__}: {error}",
                        "perturbation": {"path": [param], "from": cur, "to": probe}}
                    failed.append(param)
                    continue
                try:
                    with redirect_stdout(io.StringIO()):
                        after_shapes = drawn_shapes(fig, reg, include_frames=True)
                    after_styles = session._styles(fig, reg)
                    after_science = session._capture_science(fig, reg)
                    with redirect_stdout(io.StringIO()):
                        after_qa = list(blocking_problems(fig))
                finally:
                    import matplotlib.pyplot as plt
                    plt.close(fig)
                problems: list[str] = []
                # 1) 目标角色实测生效（plate 同一口径前后测）。
                try:
                    before_means = _role_means_of(script, config, scope, width_mm)
                    after_means = _role_means_of(script, tmp.name, scope, width_mm)
                except Exception as error:
                    cand["verified"] = False
                    cand["evidence"] = {
                        "failure": f"前后实测失败：{type(error).__name__}: {error}",
                        "perturbation": {"path": [param], "from": cur, "to": probe}}
                    failed.append(param)
                    continue
                bval = sorted(before_means.get(role, []))
                aval = sorted(after_means.get(role, []))
                if bval == aval:
                    problems.append(f"目标角色 {role} 实测无变化（{bval}）")
                elif (sum(aval) / len(aval) - sum(bval) / len(bval)) * (probe - cur) < 0:
                    problems.append(f"目标角色 {role} 变化方向与扰动相反（{bval}→{aval}）")
                nontarget_ok = {}
                for r, bv in before_means.items():
                    if r == role:
                        continue
                    av = sorted(after_means.get(r, []))
                    nontarget_ok[r] = (sorted(bv) == av)
                    if sorted(bv) != av:
                        problems.append(f"非目标角色 {r} 实测变化（{sorted(bv)}→{av}）")
                # 2) 科学指纹。
                try:
                    sci_ok, sci_notes = session._compare_science(base_science, after_science)
                except Exception as error:
                    problems.append(f"科学指纹不可比：{type(error).__name__}: {error}")
                    sci_ok, sci_notes = False, [str(error)]
                if sci_ok is False:
                    problems.append("科学指纹变化：" + "; ".join(map(str, sci_notes)))
                # 3) QA 新增。
                qa_added = sorted(set(after_qa) - set(base_qa))
                if qa_added:
                    problems.append(f"新增 QA 阻断：{qa_added}")
                # 4) 结构增删 / 对象身份。
                geo, added, removed = effects._geometry_changes(base_shapes, after_shapes)
                if added or removed:
                    problems.append(f"可见结构增删：新增 {added}，消失 {removed}")
                after_gids = sorted(reg.all())
                identity_ok = (after_gids == base_gids)
                if not identity_ok:
                    problems.append("注册对象集合变化（对象身份不一致）")
                # 5) 注册表样式变化不得超出声明对象。
                stch = effects._style_changes(
                    base_styles, after_styles,
                    sorted(set(base_styles) | set(after_styles)))
                declared_gids = {gid for gid in base_gids
                                 if param in reg.params_of(gid)}
                style_out = sorted(set(stch) - declared_gids)
                if style_out:
                    problems.append(f"注册表样式牵连未声明对象：{style_out}")
                # 6) 几何联动：家族内 = 预期；家族外 = 已记录联动（量化，不否决）。
                family = ROLE_GEOMETRY_FAMILY.get(role, ())
                in_family = {k: v for k, v in geo.items()
                             if any(f in k for f in family)}
                side = {k: v for k, v in geo.items() if k not in in_family}
                if problems:
                    cand["verified"] = False
                    cand["evidence"] = {
                        "failure": "; ".join(problems),
                        "perturbation": {"path": [param], "from": cur, "to": probe}}
                    failed.append(param)
                    continue
                cand["verified"] = True
                cand["evidence"] = {
                    "perturbation": {"path": [param], "from": float(cur),
                                     "to": float(probe),
                                     "nonzero": probe != float(cur)},
                    "width_mm": float(width_mm),
                    "target_role": role,
                    "target_before": bval, "target_after": aval,
                    "nontarget_unchanged": {r: sorted(v) for r, v in before_means.items()
                                            if r != role},
                    "science": {
                        "digest_before": base_science.get("digest"),
                        "digest_after": after_science.get("digest"),
                        "unchanged": True},
                    "qa_added": qa_added,
                    "object_identity": {"gids_stable": identity_ok,
                                        "n_gids": len(base_gids)},
                    "geometry_family": sorted(in_family),
                    "side_effects": [
                        {"key": k, "delta": v,
                         "disposition": "recorded-layout-coupling"}
                        for k, v in sorted(side.items())],
                }
                verified.append(param)
            finally:
                try:
                    Path(tmp.name).unlink()
                except OSError:
                    pass
    finally:
        if session is not None:
            session.close()
    draft["coverage"] = _coverage(draft.get("candidates") or [],
                                  draft.get("unresolved") or [],
                                  draft.get("unsupported") or [])
    p.write_text(yaml.safe_dump(draft, sort_keys=False, allow_unicode=True),
                 encoding="utf-8")
    return {"verified": verified, "failed": failed,
            "skipped_unconfirmed": skipped, "contract": str(p)}
