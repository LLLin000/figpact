"""figpact 命令行工具。"""
import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

from pathlib import Path
from typing import Optional
import yaml
from figpact.config import ConfigError, check_schema
from figpact.final_size import audit_figure, render_report, apply_final_size


def _find_schema_in_script(script_path: Path) -> Optional[dict]:
    """尝试从绘图脚本中提取 SCHEMA。"""
    try:
        spec = importlib.util.spec_from_file_location("_temp_script", script_path)
        if spec and spec.loader:
            mod = importlib.util.module_from_spec(spec)
            # 不直接 exec 全脚本，避免触发绘图，而是做静态 AST 或读全局
            # 若脚本有 SCHEMA 变量，可尝试获取
    except Exception:
        pass
    return None


def cmd_validate(args: argparse.Namespace) -> int:
    """按脚本或通用规范校验 YAML。"""
    yaml_path = Path(args.yaml).expanduser().resolve()
    if not yaml_path.is_file():
        print(f"[错误] 配置文件不存在：{yaml_path}", file=sys.stderr)
        return 1

    try:
        raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[错误] YAML 解析失败：{e}", file=sys.stderr)
        return 1

    # 寻找相邻脚本
    script = None
    if args.script:
        script = Path(args.script).expanduser().resolve()
    else:
        # 在 yaml 所在目录下寻找绘图脚本 (plot_*.py 或同名或排除 figure_style.py)
        candidates = [p for p in yaml_path.parent.glob("*.py") if p.name != "figure_style.py"]
        if candidates:
            # 优先选 plot_*.py 或含 yaml 主名的脚本
            matched = [p for p in candidates if yaml_path.stem in p.stem or p.stem.startswith("plot")]
            script = matched[0] if matched else candidates[0]
    schema = None
    if script and script.is_file():
        try:
            # 运行脚本自身的 --validate 或导入 SCHEMA
            # 简单方式：运行 python script.py --list-params 或 --help
            # 也可以直接检查通用字段
            pass
        except Exception:
            pass

    # 若未指定特定 schema，则以脚本自身或加载校验
    if script and script.is_file():
        # 执行脚本以子进程验证配置
        cmd = [sys.executable, "-X", "utf8", str(script), "--config", str(yaml_path), "--list-params"]
        res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
        if res.returncode != 0:
            print(res.stderr.strip() or res.stdout.strip(), file=sys.stderr)
            return res.returncode
        print(f"[验证] {yaml_path.name} 校验通过 ✓")
        return 0
    else:
        print(f"[验证] 基础 YAML 格式有效：{yaml_path.name} ✓")
        return 0


def cmd_render(args: argparse.Namespace) -> int:
    """以子进程跑脚本，转发 --config / --strict。"""
    script = Path(args.script).expanduser().resolve()
    if not script.is_file():
        print(f"[错误] 脚本不存在：{script}", file=sys.stderr)
        return 1

    cmd = [sys.executable, "-X", "utf8", str(script)]
    if args.config:
        cmd.extend(["--config", str(Path(args.config).expanduser().resolve())])
    if args.strict:
        cmd.append("--strict")

    res = subprocess.run(cmd, cwd=str(script.parent))
    return res.returncode


#: 真实扰动校验（figpact.effects）只有 EFFECT_OK 算通过；SKIPPED_* 是「声明不可编辑、未扰动」，不是缺陷。
_REAL_PASS = {'EFFECT_OK'}
_REAL_SKIPPED_PREFIX = 'SKIPPED'
#: 旧启发式（脚本自带 --check-effect）的状态词表，只为兼容既有消费者。
_LEGACY_PASS = {'VERIFIED', 'EFFECT_OK', 'PASS', 'OK', 'EFFECTIVE'}


def _effect_scope(args, data):
    """Explicit --scope wins; a single declared scope is unambiguous; several are AMBIGUOUS."""
    requested = getattr(args, "scope", None)
    if requested:
        return requested, []
    scopes = data.get("scopes")
    if isinstance(scopes, dict):
        names = sorted(scopes)
        if len(names) == 1:
            return names[0], names
        return None, names
    return None, []


def _print_real_effects(report) -> int:
    """Print the real-perturbation verdicts. Only EFFECT_OK counts as verified."""
    status = str(report.get("status", "UNKNOWN"))
    results = report.get("results", [])
    if status.startswith("UNSUPPORTED"):
        print(f"[UNSUPPORTED] 生效检查未执行：{status} {report.get('message', '')}".strip(), file=sys.stderr)
        print("  UNSUPPORTED 不是通过 —— 没有契约就没有可扰动验证的绑定。", file=sys.stderr)
        return 2
    for entry in results:
        name = entry.get("key") or "/".join(str(s) for s in entry.get("path", []))
        print(f"  • {name:<24} 状态: {entry.get('status', 'UNKNOWN'):<20} "
              f"声明对象: {len(entry.get('declared_objects', []))}")
        for line in list(entry.get("diagnostics", []))[:3]:
            print(f"      - {line}")
    failing = [e for e in results if e.get("status") not in _REAL_PASS
               and not str(e.get("status", "")).startswith(_REAL_SKIPPED_PREFIX)]
    if results and status == "OK" and not failing:
        print(f"\n[OK] {len(results)} 个声明参数均通过真实临时 YAML 扰动 + 整图重建验证")
        return 0
    print(f"\n[未通过] 状态计数: {report.get('counts', {})}", file=sys.stderr)
    print(f"  未确认生效或与声明不符：{[e.get('key') for e in failing]}", file=sys.stderr)
    return 1


def _print_effect_section(script: Path, config_path: Optional[Path], data: dict, args) -> int:
    """--check-effect goes through the real validator, never an Artist-mutation heuristic."""
    print("\n=== 参数生效检查 (Effectiveness Check) ===")
    scope, options = _effect_scope(args, data)
    reason = ""
    report = None
    if config_path is None:
        reason = "真实扰动校验需要 --config（没有基线配置就没有可比对的 YAML）"
    elif scope is None:
        reason = "无法确定作用域，请显式传 --scope" + (f"；候选：{options}" if options else "")
    else:
        try:
            from figpact.effects import check_effects
            report = check_effects(script, config_path, scope)
        except Exception as error:
            reason = f"真实 YAML 扰动校验不可用：{error}"
    if report is not None:
        return _print_real_effects(report)

    effects = data.get("param_effects") or {}
    if not effects and config_path is not None:
        effects = _run_script_inventory(script, config_path, check_effect=True).get("param_effects") or {}
    if not effects:
        print(f"[UNSUPPORTED] 参数生效检查未执行：{reason}", file=sys.stderr)
        print("  UNSUPPORTED 不是通过 —— 请修复契约/作用域后重跑，不要据此认为参数已生效。",
              file=sys.stderr)
        return 2
    failing = []
    for name, info in sorted(effects.items()):
        status = str(info.get("status", "UNKNOWN"))
        print(f"  • {name:<24} 状态: {status:<20} 关联图元数: {info.get('bound_gids_count', 0)}")
        if status not in _LEGACY_PASS:
            failing.append(name)
    if failing:
        print(f"\n[警告] 未确认生效的参数：{', '.join(failing)}", file=sys.stderr)
        return 1
    print(f"\n[OK] {len(effects)} 个绑定参数均通过扰动生效验证")
    return 0


def cmd_inventory(args: argparse.Namespace) -> int:
    """转发 --inventory 给脚本，把 JSON 打印成人看的清单，支持生效检查。"""
    script = Path(args.script).expanduser().resolve()
    if not script.is_file():
        print(f"[错误] 脚本不存在：{script}", file=sys.stderr)
        return 1

    cmd = [sys.executable, "-X", "utf8", str(script), "--inventory"]
    config_path = Path(args.config).expanduser().resolve() if args.config else None
    if config_path:
        cmd.extend(["--config", str(config_path)])

    res = subprocess.run(cmd, cwd=str(script.parent), capture_output=True, text=True, encoding="utf-8")
    if res.returncode != 0:
        print(res.stderr.strip() or res.stdout.strip(), file=sys.stderr)
        return res.returncode

    try:
        data = json.loads(res.stdout)
    except Exception:
        # 如果脚本输出包含其他文字，尝试找 JSON 部分
        text = res.stdout.strip()
        idx = text.find("{")
        if idx >= 0:
            data = json.loads(text[idx:])
        else:
            print(text)
            return 0

    items = data.get("items", [])
    unreg = data.get("unregistered", [])
    unb = data.get("unbound", [])

    print(f"=== 图元清点清单 (共 {len(items)} 个已登记图元) ===")
    for it in items:
        params_str = ", ".join(it.get("params", [])) or "无绑定"
        print(f"• [{it.get('gid')}] ({it.get('type')}): {it.get('summary')} | 绑定参数: {params_str}")

    print("\n=== 清点统计摘要 ===")
    print(f"总登记对象: {len(items)}")
    print(f"未登记对象 (unregistered): {len(unreg)}")
    for u in unreg:
        print(f"  - {u}")
    print(f"未绑定参数对象 (unbound): {len(unb)}")
    for ub in unb:
        print(f"  - {ub}")

    if getattr(args, "check_effect", False):
        return _print_effect_section(script, config_path, data, args)

    return 0


def cmd_inspect(args: argparse.Namespace) -> int:
    """转发 --inspect <gid> 给脚本。"""
    script = Path(args.script).expanduser().resolve()
    if not script.is_file():
        print(f"[错误] 脚本不存在：{script}", file=sys.stderr)
        return 1

    cmd = [sys.executable, "-X", "utf8", str(script), "--inspect", args.gid]
    if args.config:
        cmd.extend(["--config", str(Path(args.config).expanduser().resolve())])

    res = subprocess.run(cmd, cwd=str(script.parent))
    return res.returncode
def cmd_list_params(args: argparse.Namespace) -> int:
    """转发 --list-params 给脚本。"""
    script = Path(args.script).expanduser().resolve()
    if not script.is_file():
        print(f"[错误] 脚本不存在：{script}", file=sys.stderr)
        return 1

    cmd = [sys.executable, "-X", "utf8", str(script), "--list-params"]
    if args.config:
        cmd.extend(["--config", str(Path(args.config).expanduser().resolve())])

    res = subprocess.run(cmd, cwd=str(script.parent))
    return res.returncode


def _deep_merge_dict(target: dict, patch: dict) -> None:
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(target.get(k), dict):
            _deep_merge_dict(target[k], v)
        else:
            target[k] = v


def _apply_set_key(target: dict, key: str, val_str: str) -> None:
    val = yaml.safe_load(val_str)
    parts = key.split(".")
    cur = target
    for p in parts[:-1]:
        if p not in cur or not isinstance(cur[p], dict):
            cur[p] = {}
        cur = cur[p]
    cur[parts[-1]] = val


def _get_key_path(d: dict, key: str):
    parts = key.split(".")
    cur = d
    for p in parts:
        if not isinstance(cur, dict) or p not in cur:
            return None
        cur = cur[p]
    return cur


def _set_key_path(d: dict, key: str, val):
    parts = key.split(".")
    cur = d
    for p in parts[:-1]:
        if p not in cur or not isinstance(cur[p], dict):
            cur[p] = {}
        cur = cur[p]
    cur[parts[-1]] = val


def _run_script_inventory(script: Path, cfg_path: Path, *, check_effect: bool = False) -> dict:
    cmd = [sys.executable, "-X", "utf8", str(script), "--config", str(cfg_path), "--inventory"]
    if check_effect:
        cmd.append("--check-effect")
    res = subprocess.run(cmd, cwd=str(script.parent), capture_output=True, text=True, encoding="utf-8")
    text = res.stdout.strip()
    idx = text.find("{")
    if idx >= 0:
        try:
            return json.loads(text[idx:])
        except Exception:
            pass
    return {}


def _run_script_strict(script: Path, cfg_path: Path, probe_dir: Optional[Path] = None) -> tuple[int, list[str]]:
    """跑 `--strict`。**永远是试算**：产物只许落进 probe_dir。

    隔离归这条共享路径管，不归调用方管 —— 谁调它（`figpact try`、GUI 的试算面板）
    都拿不到「试算把正式输出覆盖了」这个结果：
      ① 设 `FIGPACT_PROBE_DIR`，凡走 `figpact.publish.publish()` 的脚本自动改道；
      ② 脚本自己支持 `--probe <dir>` 的再显式传一遍（直接 savefig 的脚本靠它）。
    没给 probe_dir 就自建一个临时目录，跑完删掉。
    """
    own_tmp = None
    if probe_dir is None:
        own_tmp = tempfile.mkdtemp(prefix="figpact-probe-")
        probe_dir = Path(own_tmp)
    try:
        cmd = [sys.executable, "-X", "utf8", str(script), "--config", str(cfg_path), "--strict"]
        try:
            src = script.read_text(encoding="utf-8", errors="replace")
        except OSError:
            src = ""
        if '"--probe"' in src or "'--probe'" in src:
            cmd.extend(["--probe", str(probe_dir)])
        env = {**os.environ, "FIGPACT_PROBE_DIR": str(probe_dir)}
        res = subprocess.run(cmd, cwd=str(script.parent), capture_output=True, text=True,
                             encoding="utf-8", env=env)
    finally:
        if own_tmp:
            shutil.rmtree(own_tmp, ignore_errors=True)
    qa_lines = []
    for line in (res.stdout + "\n" + res.stderr).splitlines():
        l = line.strip()
        if "[QA]" in l or "[验收]" in l or "[未豁免]" in l or "超出坐标框" in l or "压线" in l or "NO_FEASIBLE_SLOT" in l:
            qa_lines.append(l)
    return res.returncode, qa_lines


def cmd_try(args: argparse.Namespace) -> int:
    """把 patch/--set 在内存中合并到当前配置，试算位移、QA 差异与参数可行区间。"""
    from figpact.qa import diagnose, diagnostic_key

    script = Path(args.script).expanduser().resolve()
    if not script.is_file():
        print(f"[错误] 脚本不存在：{script}", file=sys.stderr)
        return 1

    config_path = Path(args.config).expanduser().resolve()
    if not config_path.is_file():
        print(f"[错误] 配置文件不存在：{config_path}", file=sys.stderr)
        return 1

    base_config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    patched_config = yaml.safe_load(yaml.safe_dump(base_config))

    modified_keys = []
    if args.patch:
        patch_path = Path(args.patch).expanduser().resolve()
        if not patch_path.is_file():
            print(f"[错误] Patch 文件不存在：{patch_path}", file=sys.stderr)
            return 1
        patch_dict = yaml.safe_load(patch_path.read_text(encoding="utf-8")) or {}
        _deep_merge_dict(patched_config, patch_dict)
        modified_keys.extend(list(patch_dict.keys()))

    if args.set:
        for item in args.set:
            if "=" in item:
                k, v = item.split("=", 1)
                _apply_set_key(patched_config, k.strip(), v.strip())
                modified_keys.append(k.strip())

    with tempfile.TemporaryDirectory(prefix="figpact-try-") as tmp_dir:
        td = Path(tmp_dir)
        base_yaml = td / "base.yaml"
        patched_yaml = td / "patched.yaml"
        # 试算沙箱：四条路径（基线/候选/异常/二分）全部只许写这里，
        # examples 里的正式输出由 hash 前后比对把关（见 commit 里的验收脚本）。
        probe = td / "probe"

        base_yaml.write_text(yaml.safe_dump(base_config), encoding="utf-8")
        patched_yaml.write_text(yaml.safe_dump(patched_config), encoding="utf-8")

        # 1. 运行 baseline 与 try 的 inventory
        inv_before = _run_script_inventory(script, base_yaml)
        inv_after = _run_script_inventory(script, patched_yaml)

        # 2. 运行 baseline 与 try 的 strict 检查
        code_before, qa_before = _run_script_strict(script, base_yaml, probe)
        code_after, qa_after = _run_script_strict(script, patched_yaml, probe)

        # 计算对象位移 (mm)
        print("=== 1. 对象位移 (Movement Delta) ===")
        snap_map_before = {it["gid"]: it.get("snapshot", {}) for it in inv_before.get("items", [])}
        snap_map_after = {it["gid"]: it.get("snapshot", {}) for it in inv_after.get("items", [])}
        moved_count = 0
        # 换算必须用**测量时的真实 dpi**：bbox 来自 inventory 那次渲染的显示像素。
        # 以前写死 300 dpi，而图是 figure.dpi=120 → 位移被缩到 40%（-0.5mm 报成 -0.20）。
        # 现在读 inventory 一并返回的 figure_dpi；两边不一致时按测量元数据为准。
        dpi_before = float(inv_before.get("figure_dpi") or 0) or None
        dpi_after = float(inv_after.get("figure_dpi") or 0) or None
        if dpi_before and dpi_after and abs(dpi_before - dpi_after) > 1e-6:
            print(f"[warn] 两次 inventory 的 dpi 不一致（{dpi_before} vs {dpi_after}），按前者换算")
        measure_dpi = dpi_before or dpi_after or 300.0
        px_per_mm = measure_dpi / 25.4
        print(f"[测量] bbox 取自 figure.dpi={measure_dpi:g}（换算 {px_per_mm:.3f} px/mm）")
        for gid, s_after in snap_map_after.items():
            s_before = snap_map_before.get(gid)
            if not s_before:
                continue
            bb0 = s_before.get("bbox")
            bb1 = s_after.get("bbox")
            if bb0 and bb1:
                dx_px = ((bb1[0] + bb1[2]) - (bb0[0] + bb0[2])) / 2.0
                dy_px = ((bb1[1] + bb1[3]) - (bb0[1] + bb0[3])) / 2.0
                dx_mm = dx_px / px_per_mm
                dy_mm = dy_px / px_per_mm
                dist_mm = (dx_mm**2 + dy_mm**2)**0.5
                if dist_mm > 0.05:
                    moved_count += 1
                    print(f"• [{gid}]: dx = {dx_mm:+.2f} mm, dy = {dy_mm:+.2f} mm (位移 {dist_mm:.2f} mm)")
            elif s_before.get("position") and s_after.get("position"):
                p0 = s_before["position"]
                p1 = s_after["position"]
                dp = ((p1[0] - p0[0])**2 + (p1[1] - p0[1])**2)**0.5
                if dp > 1e-4:
                    moved_count += 1
                    print(f"• [{gid}]: position 改变 {p0} -> {p1}")
        if moved_count == 0:
            print("（无图元发生物理位置位移）")

        # 计算 QA 差异：按**结构化诊断 key**（规则 + 作用域 + 对象 id）比对，
        # 数值（mm/px²/点数）不参与 —— 所以「3p68 解决、2p02 新增」不会再被误判成无变化。
        print("\n=== 2. QA 差异 (QA Delta) ===")
        key_before = {diagnostic_key(diagnose(q)): q for q in qa_before}
        key_after = {diagnostic_key(diagnose(q)): q for q in qa_after}

        added_keys = set(key_after.keys()) - set(key_before.keys())
        removed_keys = set(key_before.keys()) - set(key_after.keys())

        if added_keys:
            print("【新增阻断/警告】:")
            for k in sorted(added_keys):
                print(f"  + {key_after[k]}")
                print(f"      key: {k[0]} | scope={k[1] or '-'} | objects={list(k[2])}")
        else:
            print("【新增阻断/警告】: 无")

        if removed_keys:
            print("【消除阻断/警告】:")
            for k in sorted(removed_keys):
                print(f"  - {key_before[k]}")
                print(f"      key: {k[0]} | scope={k[1] or '-'} | objects={list(k[2])}")
        else:
            print("【消除阻断/警告】: 无")
        print(f"Strict 状态: 修改前 exit={code_before} -> 修改后 exit={code_after}")

        # 3. 参数可行区间二分试算
        print("\n=== 3. 参数可行区间 (Feasible Interval via Bisection) ===")
        for p_key in set(modified_keys):
            val_now = _get_key_path(patched_config, p_key)
            val_orig = _get_key_path(base_config, p_key)
            if not isinstance(val_now, (int, float)) or isinstance(val_now, bool):
                continue
            if val_orig is None:
                val_orig = 0.0

            def test_candidate(v_test: float) -> bool:
                c_test = yaml.safe_load(yaml.safe_dump(base_config))
                _set_key_path(c_test, p_key, v_test)
                cand_yaml = td / "cand.yaml"
                cand_yaml.write_text(yaml.safe_dump(c_test), encoding="utf-8")
                c_ret, _ = _run_script_strict(script, cand_yaml, probe)
                return c_ret == 0

            # 二分找边界：以基线为锚点分别向两侧探索
            # 下界 (向负方向)
            v_orig_val = float(val_orig)
            # 探索负方向安全边界
            low = v_orig_val - max(abs(float(val_now) - v_orig_val) * 3.0, 5.0)
            high = v_orig_val
            # 确认 high 是通过的
            iters_low = 0
            if test_candidate(high):
                while high - low > 0.02 and iters_low < 12:
                    mid = (low + high) / 2.0
                    iters_low += 1
                    if test_candidate(mid):
                        high = mid
                    else:
                        low = mid
                feasible_min = high
            else:
                feasible_min = v_orig_val

            # 上界 (向正方向)
            low_u = v_orig_val
            high_u = v_orig_val + max(abs(float(val_now) - v_orig_val) * 3.0, 5.0)
            iters_high = 0
            if test_candidate(low_u):
                while high_u - low_u > 0.02 and iters_high < 12:
                    mid = (low_u + high_u) / 2.0
                    iters_high += 1
                    if test_candidate(mid):
                        low_u = mid
                    else:
                        high_u = mid
                feasible_max = low_u
            else:
                feasible_max = v_orig_val

            tot_iters = iters_low + iters_high
            print(f"• {p_key} 可行 [{feasible_min:.2f}, {feasible_max:.2f}] (二分迭代 {tot_iters} 次，收敛阈值 0.02 mm)")

    return 0

def cmd_agent(args: argparse.Namespace) -> int:
    """本机持久会话：stdin/stdout 上跑 JSON-RPC，stdout 只承载协议本身。"""
    from figpact.agent_api import serve

    return serve(args.script, args.config, args.scope, output_dir=args.output_dir)


def cmd_export_params(args: argparse.Namespace) -> int:
    """从注册表与脚本规范导出全部参数为结构化 JSON。"""
    script = Path(args.script).expanduser().resolve()
    if not script.is_file():
        print(f"[错误] 脚本不存在：{script}", file=sys.stderr)
        return 1
    cfg = Path(args.config).expanduser().resolve() if args.config else None
    catalog = export_params_catalog(script, cfg)
    if args.json:
        print(json.dumps(catalog, ensure_ascii=False, indent=2))
    else:
        print(f"图表: {catalog['figure']}")
        for sc_name, sc_data in catalog["scopes"].items():
            print(f"\n[作用域: {sc_name}]")
            for grp in sc_data["groups"]:
                print(f"  === {grp['group']} ===")
                for p in grp["params"]:
                    print(f"    • {p['key']:<30} {p['中文名']:<16} 当前值={p['当前值']} [{p['min']}, {p['max']}] {p['调大会怎样']}")
    return 0


def cmd_audit_params(args: argparse.Namespace) -> int:
    """渲染后遍历所有可见 artist，输出五类可调属性覆盖审计报告。"""
    script = Path(args.script).expanduser().resolve()
    if not script.is_file():
        print(f"[错误] 脚本不存在：{script}", file=sys.stderr)
        return 1
    cfg = Path(args.config).expanduser().resolve() if args.config else None
    report = audit_artists_coverage(script, cfg)

    out_lines = [
        f"# 参数全集覆盖审计报告 - {script.name}",
        "",
        f"- 脚本: `{script}`",
        f"- 配置: `{cfg or '默认'}`",
        f"- 总属性数: {report['total_properties']}",
        "",
        "## 1. 五类属性统计",
        "",
        "| 分类 | 属性项数 | 占比 | 简要说明 |",
        "| :--- | :---: | :---: | :--- |",
    ]
    tot = report["total_properties"] or 1
    cat_desc = {
        "已暴露为 YAML 参数": "已在配置文件和 list_params 中声明为可编辑参数",
        "全局样式（figure_style 统一）": "由统一出版规范锁死（字族、色板、边框/刻度线宽、虚线样式等）",
        "科学锁定（峰位、显示窗、归一化、归属）": "涉及实验科学真实性（仪器原始数据、显示范围、官能团/峰归属、化学位移定标）",
        "由其他参数派生": "由几何约束、实测文本包络框或前序参数算法求解派生，不可单独设置",
        "未覆盖": "属于图元可见特征但尚未归入上述四类的未管辖项",
    }
    for cat, count in report["stats"].items():
        ratio = (count / tot) * 100.0
        out_lines.append(f"| {cat} | {count} | {ratio:.1f}% | {cat_desc.get(cat, '')} |")

    out_lines.extend([
        "",
        "## 2. 未覆盖项清单及建议归类",
        "",
    ])
    if report["uncovered"]:
        out_lines.append("| 序号 | Artist 类型 | GID / 标识 | 属性 | 当前状态 | 建议归类与理由 |")
        out_lines.append("| :---: | :--- | :--- | :--- | :--- | :--- |")
        for idx, item in enumerate(report["uncovered"], 1):
            out_lines.append(f"| {idx} | {item['artist_type']} | `{item['gid']}` | {item['property']} | 未覆盖 | {item.get('suggestion', '建议归入全局样式或参数')} |")
    else:
        out_lines.append("✓ **全部可见图元属性已完整覆盖并归档于前四类，无未覆盖孤立属性。**")

    out_lines.extend([
        "",
        "## 3. 详细属性分布清单 (前 15 条抽样)",
        "",
        "| Artist 类型 | GID | 属性 | 分类 | 归类理由 |",
        "| :--- | :--- | :--- | :--- | :--- |",
    ])
    for item in report["entries"][:15]:
        out_lines.append(f"| {item['artist_type']} | `{item['gid']}` | {item['property']} | {item['category']} | {item['reason']} |")

    md_content = "\n".join(out_lines) + "\n"

    if args.output:
        out_p = Path(args.output).expanduser().resolve()
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(md_content, encoding="utf-8")
        print(f"[审计] 审计报告已生成至：{out_p}")

    print("\n" + md_content)
    return 0





def cmd_contract_discover(args: argparse.Namespace) -> int:
    """G11：只读发现可编辑入口，写 Contract Draft 文件（默认未确认，不生效）。"""
    from figpact import init_contract as ic

    try:
        draft = ic.discover(args.script, args.config, scope=args.scope)
    except (FileNotFoundError, ValueError, SyntaxError) as e:
        print(f"[错误] 发现失败：{type(e).__name__}: {e}", file=sys.stderr)
        return 2
    out = Path(args.out).expanduser().resolve() if args.out else (
        Path(args.script).expanduser().resolve().parent / "demo.contract.yaml")
    if out.exists() and not args.force:
        print(f"[错误] 目标已存在（不覆盖）：{out}（用 --force 覆盖）", file=sys.stderr)
        return 1
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(draft, sort_keys=False, allow_unicode=True), encoding="utf-8")
    print(f"[contract] draft 已写：{out}")
    print(ic.coverage_report(draft))
    return 0


def cmd_contract_verify(args: argparse.Namespace) -> int:
    """G11：对 draft 里已人工确认条目做扰动验证（只读扰动，原地写回 draft）。"""
    from figpact import init_contract as ic

    try:
        res = ic.verify(args.contract, width_mm=args.width_mm)
    except (FileNotFoundError, ValueError) as e:
        print(f"[错误] 验证失败：{type(e).__name__}: {e}", file=sys.stderr)
        return 2
    draft = yaml.safe_load(Path(res["contract"]).read_text(encoding="utf-8")) or {}
    print(f"[contract] verified={res['verified']} failed={res['failed']} "
          f"skipped_unconfirmed={res['skipped_unconfirmed']}")
    print(ic.coverage_report(draft))
    return 0 if not res["failed"] else 1


def cmd_final_size(args: argparse.Namespace) -> int:
    script = Path(args.script).expanduser().resolve()
    cfg = Path(args.config).expanduser().resolve() if args.config else None
    result = audit_figure(
        script,
        config=cfg,
        target_width_mm=args.target_mm,
        scope=args.scope,
        output=args.output,
    )
    if args.json or args.output:
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(render_report(result))
    return 0

def cmd_final_size_apply(args):
    script = Path(args.script).expanduser().resolve()
    cfg = Path(args.config).expanduser().resolve() if args.config else None
    result = apply_final_size(script, config=cfg, target_width_mm=args.target_mm,
                             target_axis_font_pt=args.axis_pt,
                             target_tick_font_pt=args.tick_pt,
                             target_line_pt=args.line_pt, scope=args.scope,
                             mode=args.mode)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _plate_from_manifest(args) -> tuple:
    """plate.yaml manifest -> (manifest, specs, widths); None manifest for legacy flags."""
    from figpact import plate as plate_mod

    manifest_path = getattr(args, "manifest", None)
    if not manifest_path:
        return None, *_plate_specs(args)
    try:
        manifest = plate_mod.load_plate(manifest_path)
    except (FileNotFoundError, ValueError) as e:
        print(plate_mod.refusal_lines(str(e), "检查 plate.yaml 路径/figures/design 是否合法",
                                      "figpact plate compare <plate.yaml>"),
              file=sys.stderr)
        raise SystemExit(2)
    specs, widths = plate_mod.manifest_specs_widths(manifest)
    return manifest, specs, widths


def cmd_plate_compare(args) -> int:
    from figpact import plate as plate_mod
    try:
        manifest, specs, widths = _plate_from_manifest(args)
        result = plate_mod.audit(specs, widths)
    except (FileNotFoundError, ValueError) as e:
        print(plate_mod.refusal_lines(str(e), "检查 plate.yaml 或 --figure 路径/宽度是否正确",
                                      "figpact plate compare <plate.yaml>"),
              file=sys.stderr)
        return 2
    plan_targets = plate_mod.manifest_shared_targets(manifest) if manifest else {}
    plan = (plate_mod.plan_unify(result, plan_targets, manifest.get("contracts"))
            if manifest else None)
    compare = plate_mod.compare_roles(result, manifest, plan)
    if getattr(args, "out", None):
        Path(args.out).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).expanduser().resolve().write_text(
            json.dumps({"audit": result, "compare": compare}, ensure_ascii=False, indent=2),
            encoding="utf-8")
    if args.json:
        print(json.dumps({"audit": result, "compare": compare}, ensure_ascii=False, indent=2))
    else:
        print(plate_mod.render_compare_text(result, compare, manifest))
    return 0


def _plate_specs(args) -> tuple[list[dict], list[float]]:
    figs = getattr(args, "figure", []) or []
    if not figs:
        print("[错误] 至少指定一张图：--figure script.py[,config.yaml][,scope][:width]（可重复）", file=sys.stderr)
        raise SystemExit(2)
    default_width = getattr(args, "width_mm", None)
    specs, widths = [], []
    for raw in figs:
        width = default_width
        item = raw
        if ":" in raw:
            item, tail = raw.rsplit(":", 1)
            try:
                width = float(tail)
            except ValueError:
                item = raw
        parts = item.split(",")
        spec: dict = {"path": parts[0].strip()}
        if len(parts) > 1 and parts[1].strip():
            spec["config"] = parts[1].strip()
        if len(parts) > 2 and parts[2].strip():
            spec["scope"] = parts[2].strip()
        if len(parts) > 3 and parts[3].strip():
            spec["label"] = parts[3].strip()
        if width is None:
            print(f"[错误] 缺少目标宽度：{raw}（用 --width-mm 或 --figure ...:宽度）", file=sys.stderr)
            raise SystemExit(2)
        spec["_width_mm"] = float(width)
        specs.append(spec)
        widths.append(float(width))
    return specs, widths


def cmd_plate_audit(args) -> int:
    from figpact import plate as plate_mod
    try:
        specs, widths = _plate_specs(args)
        result = plate_mod.audit(specs, widths)
    except (FileNotFoundError, ValueError) as e:
        print(plate_mod.refusal_lines(str(e), "检查 --figure 路径/宽度是否正确",
                                      "figpact plate audit --figure <script.py,config.yaml> --width-mm 42 --json"),
              file=sys.stderr)
        return 2
    if getattr(args, "out", None):
        Path(args.out).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).expanduser().resolve().write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(plate_mod.render_audit_text(result))
    return 0


def cmd_plate_unify(args) -> int:
    from figpact import plate as plate_mod
    manifest = None
    try:
        if getattr(args, "manifest", None):
            manifest = plate_mod.load_plate(args.manifest)
            specs, widths = plate_mod.manifest_specs_widths(manifest)
            result = plate_mod.audit(specs, widths)
            targets = plate_mod.manifest_shared_targets(manifest)
        else:
            specs, widths = _plate_specs(args)
            result = plate_mod.audit(specs, widths)
            targets = {}
    except (FileNotFoundError, ValueError) as e:
        print(plate_mod.refusal_lines(str(e), "检查 plate.yaml 或 --figure 路径/宽度是否正确",
                                      "figpact plate unify <plate.yaml> [--apply]"),
              file=sys.stderr)
        return 2
    if getattr(args, "target_width_mm", None) is not None:
        targets["target_width_mm"] = float(args.target_width_mm)
    if getattr(args, "axis_pt", None) is not None:
        targets["axis_font_pt"] = float(args.axis_pt)
    if getattr(args, "tick_pt", None) is not None:
        targets["tick_font_pt"] = float(args.tick_pt)
    if getattr(args, "line_pt", None) is not None:
        targets["line_width"] = float(args.line_pt)
    plan = plate_mod.plan_unify(result, targets,
                                manifest.get("contracts") if manifest else None)
    if manifest is not None:
        plan["manifest_hash"] = manifest["manifest_hash"]
        plan["tokens"] = plate_mod._role_targets(manifest, plan)
    if not args.apply:
        print(json.dumps({"status": plan["status"], "plan": plan}, ensure_ascii=False, indent=2))
        return 0 if plan["status"] == "feasible" else 1
    if plan["status"] == "infeasible" and not plan.get("steps"):
        print(json.dumps({"status": "infeasible", "plan": plan}, ensure_ascii=False, indent=2))
        return 1
    for s, w in zip(specs, widths):
        s["_width_mm"] = float(targets.get("target_width_mm", w))
    unified = plate_mod.unify(plan, specs=specs,
                              contracts=manifest.get("contracts") if manifest else None)
    after = unified.get("after") if isinstance(unified.get("after"), dict) else None
    compare = plate_mod.compare_roles(after or result, manifest, plan)
    rec = plate_mod.receipt(result, plan, unified if after else None,
                            manifest=manifest, compare=compare,
                            change_audit=unified.get("change_audits"))
    print(json.dumps({"status": unified["status"], "plan": plan, "unify": unified,
                      "compare": compare, "receipt": rec}, ensure_ascii=False, indent=2))
    ok = unified["status"] in ("OK", "PARTIAL")
    if any(item.get("result", {}).get("figure_verification_state") == "FAIL"
           for item in unified.get("per_figure", [])):
        ok = False
    if unified.get("change_audits") and any(c.get("blocking") for c in unified["change_audits"] if isinstance(c, dict)):
        ok = False
    if after:
        bad = [f for f in after.get("figures", []) if f.get("out_of_bounds") or f.get("infeasible")]
        ok = ok and not bad
    return 0 if ok else 1


def cmd_plate_receipt(args) -> int:
    from figpact import plate as plate_mod
    manifest = None
    try:
        if getattr(args, "manifest", None):
            manifest = plate_mod.load_plate(args.manifest)
            specs, widths = plate_mod.manifest_specs_widths(manifest)
            result = plate_mod.audit(specs, widths)
        else:
            specs, widths = _plate_specs(args)
            result = plate_mod.audit(specs, widths)
    except (FileNotFoundError, ValueError) as e:
        print(plate_mod.refusal_lines(str(e), "检查 plate.yaml 或 --figure 路径/宽度是否正确",
                                      "figpact plate receipt <plate.yaml>"),
              file=sys.stderr)
        return 2
    compare = plate_mod.compare_roles(result, manifest)
    rec = plate_mod.receipt(result, manifest=manifest, compare=compare)
    if getattr(args, "out", None):
        Path(args.out).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).expanduser().resolve().write_text(
            json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(rec, ensure_ascii=False, indent=2))
    return 0


def cmd_ui(args: argparse.Namespace) -> int:
    """thin wrapper over inspector_server; does not implement its own service."""
    from figpact.inspector_server import main as run_inspector
    argv = []
    if getattr(args, "script", None):
        argv += ["--script", str(args.script)]
    if getattr(args, "config", None):
        argv += ["--config", str(args.config)]
    if getattr(args, "scope", None):
        argv += ["--scope", str(args.scope)]
    if getattr(args, "port", None) is not None:
        argv += ["--port", str(args.port)]
    if getattr(args, "dpi", None) is not None:
        argv += ["--dpi", str(args.dpi)]
    return int(run_inspector(argv) or 0)


def cmd_overlay(args) -> int:
    """Verified declarative styles; never rewrite the plotting script."""
    from figpact import style_overlay

    try:
        if args.overlay_cmd == "inventory":
            result = {"targets": style_overlay.inventory(
                args.script, args.config, args.scope)}
            code = 0
        elif args.overlay_cmd == "apply":
            edits = json.loads(Path(args.edits).read_text(encoding="utf-8")) if args.edits else []
            result = style_overlay.apply(
                args.script, args.config, args.scope, edits=edits,
                overlay=args.overlay, expected_before_sha256=args.expected_sha256,
                allow_draft=args.allow_draft, remove=args.remove)
            code = 0 if (result.get("local_edit_state") == "PASS"
                         and result.get("figure_verification_state") == "PASS") else 1
        else:
            if args.output:
                output = Path(args.output).expanduser().resolve()
                if output.suffix.lower() not in (".png", ".svg", ".pdf"):
                    raise ValueError("output must be PNG, SVG or PDF")
                result = style_overlay.render(args.overlay, output)
            else:
                fig, _reg, result = style_overlay.load(args.overlay)
                if fig is not None:
                    import matplotlib.pyplot as plt
                    plt.close(fig)
            code = 0 if (result.get("local_edit_state") == "PASS"
                         and result.get("figure_verification_state") == "PASS") else 1
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return code
    except (ValueError, OSError, RuntimeError) as error:
        print(json.dumps({"status": "REFUSED", "local_edit_state": "ERROR",
                          "message": str(error)}, ensure_ascii=False, indent=2))
        return 1


def main(argv: Optional[list[str]] = None) -> int:
    """命令行主入口。"""
    if argv is None:
        argv = sys.argv[1:]

    parser = argparse.ArgumentParser(prog="figpact", description="科研出版图参数契约与质量保障引擎")
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    # validate <yaml> [--script <py>]
    p_val = subparsers.add_parser("validate", help="按脚本声明的 schema 校验配置 YAML")
    p_val.add_argument("yaml", help="配置文件 YAML 路径")
    p_val.add_argument("--script", default=None, help="对应的绘图脚本路径")

    # render --script <py> --config <yaml> [--strict]
    p_ren = subparsers.add_parser("render", help="以子进程跑脚本渲染图表")
    p_ren.add_argument("--script", required=True, help="绘图脚本路径")
    p_ren.add_argument("--config", default=None, help="配置文件 YAML 路径")
    p_ren.add_argument("--strict", action="store_true", help="严格模式（有阻断项则退出码非零）")

    # inventory --script <py> --config <yaml> [--check-effect]
    p_inv = subparsers.add_parser("inventory", help="获取可见图元清点清单")
    p_inv.add_argument("--script", required=True, help="绘图脚本路径")
    p_inv.add_argument("--config", default=None, help="配置文件 YAML 路径")
    p_inv.add_argument("--check-effect", action="store_true", help="执行参数生效扰动检查")
    p_inv.add_argument("--scope", default=None, help="生效检查使用的作用域（脚本声明多个 scope 时必须显式指定）")
    # inspect <gid> --script <py> --config <yaml>
    p_ins = subparsers.add_parser("inspect", help="检查特定 gid 的图元信息")
    p_ins.add_argument("gid", help="要检查的图元 gid")
    p_ins.add_argument("--script", required=True, help="绘图脚本路径")
    p_ins.add_argument("--config", default=None, help="配置文件 YAML 路径")

    # export --script <py> --config <yaml> (等价于 render --strict)
    p_exp = subparsers.add_parser("export", help="导出图表（等价于 render --strict）")
    p_exp.add_argument("--script", required=True, help="绘图脚本路径")
    p_exp.add_argument("--config", default=None, help="配置文件 YAML 路径")
    # list-params --script <py> [--config <yaml>]
    p_lp = subparsers.add_parser("list-params", help="按可见对象分组打印全部参数清单与可微调对象")
    p_lp.add_argument("--script", required=True, help="绘图脚本路径")
    p_lp.add_argument("--config", default=None, help="配置文件 YAML 路径")

    # try --script <py> --config <yaml> [--patch <patch.yaml>] [--set k=v ...]
    p_try = subparsers.add_parser("try", help="内存合并配置并试算位移、QA差异与参数可行区间")
    p_try.add_argument("--script", required=True, help="绘图脚本路径")
    p_try.add_argument("--config", required=True, help="配置文件 YAML 路径")
    p_try.add_argument("--patch", default=None, help="补丁 YAML 文件路径")
    p_try.add_argument("--set", action="append", default=[], help="键值对覆盖 (k=v)，可重复")

    # export-params --script <py> [--config <yaml>] [--json]
    p_ep = subparsers.add_parser("export-params", help="导出每张图、每个 scope 的全部参数清单为 JSON")
    p_ep.add_argument("--script", required=True, help="绘图脚本路径")
    p_ep.add_argument("--config", default=None, help="配置文件 YAML 路径")
    p_ep.add_argument("--json", action="store_true", help="以 JSON 格式输出")

    # audit-params --script <py> [--config <yaml>] [--output <report.md>]
    p_ap = subparsers.add_parser("audit-params", help="遍历可见图元所有可调属性并做五类参数全集审计")
    p_ap.add_argument("--script", required=True, help="绘图脚本路径")
    p_ap.add_argument("--config", default=None, help="配置文件 YAML 路径")
    p_ap.add_argument("--output", default=None, help="输出 Markdown 报告路径")

    # ui --script <py> [--config <yaml>] (thin wrapper)
    p_ui = subparsers.add_parser("ui", help="启动 Inspector（薄封装，服务仍由 inspector_server 提供）")
    p_ui.add_argument("--script", default=None, help="可信本地绘图脚本")
    p_ui.add_argument("--config", default=None, help="配置 YAML")
    p_ui.add_argument("--scope", default="main", help="作用域")
    p_ui.add_argument("--port", type=int, default=0, help="端口")
    p_ui.add_argument("--dpi", type=int, default=600, choices=(120, 240, 600), help="显示分辨率")

    # agent --script <py> --config <yaml> --scope <name> [--output-dir <dir>]
    p_agent = subparsers.add_parser("agent", help="本机持久 JSON-RPC 会话：snapshot/inspect/try_layout/render_preview/commit")
    p_agent.add_argument("--script", required=True, help="绘图脚本路径")
    p_agent.add_argument("--config", required=True, help="配置文件 YAML 路径")
    p_agent.add_argument("--scope", required=True, help="会话作用域（一张图一个工作进程）")
    p_agent.add_argument("--output-dir", default=None, dest="output_dir",
                         help="产物根目录（默认脚本所在目录）")
    # final-size (read-only)
    p_fs = subparsers.add_parser("final-size", aliases=["audit-final-size"], help="只读 final-size 审计")
    p_fs.add_argument("--script", required=True, help="绘图脚本路径")
    p_fs.add_argument("--config", default=None, help="配置文件路径")
    p_fs.add_argument("--target-mm", type=float, default=None, dest="target_mm", help="目标最终宽度 mm")
    p_fs.add_argument("--scope", default=None, help="作用域")
    p_fs.add_argument("--output", default=None, help="输出 JSON 文件")
    p_fs.add_argument("--json", action="store_true", help="JSON 输出")

    # final-size-apply (controlled modification)
    p_fsa = subparsers.add_parser("final-size-apply", help="受控 final-size 修改")
    p_fsa.add_argument("--script", required=True)
    p_fsa.add_argument("--config", default=None)
    p_fsa.add_argument("--target-mm", type=float, default=None, dest="target_mm")
    p_fsa.add_argument("--axis-pt", type=float, default=8.0, dest="axis_pt")
    p_fsa.add_argument("--tick-pt", type=float, default=7.0, dest="tick_pt")
    p_fsa.add_argument("--line-pt", type=float, default=0.8, dest="line_pt")
    p_fsa.add_argument("--scope", default=None)
    p_fsa.add_argument("--mode", default="B", choices=["A","B"])

    # contract discover|verify (G11 init-contract 最小闭环)
    p_contract = subparsers.add_parser("contract", help="G11：发现可编辑入口 / 扰动验证")
    contract_sub = p_contract.add_subparsers(dest="contract_cmd", required=True)
    p_cd = contract_sub.add_parser("discover", help="只读发现可编辑入口，写 Contract Draft（默认未确认）")
    p_cd.add_argument("--script", required=True, help="绘图脚本路径")
    p_cd.add_argument("--config", required=True, help="配置文件 YAML 路径")
    p_cd.add_argument("--scope", default=None, help="作用域（默认脚本首个 scope）")
    p_cd.add_argument("--out", default=None, help="Draft 输出路径（默认脚本同目录 demo.contract.yaml）")
    p_cd.add_argument("--force", action="store_true", help="允许覆盖已存在的 Draft")
    p_cv = contract_sub.add_parser("verify", help="对已确认条目做真实扰动验证（只读扰动）")
    p_cv.add_argument("contract", help="Contract Draft 文件路径")
    p_cv.add_argument("--width-mm", type=float, default=None, help="前后实测的目标宽度 mm（默认 YAML 画布宽）")
    p_plate = subparsers.add_parser("plate", help="跨图件实测比较 / 源码级统一 / 回执")
    plate_sub = p_plate.add_subparsers(dest="plate_cmd", required=True)
    p_pa = plate_sub.add_parser("audit", help="多张图最终尺寸下实测比较")
    p_pa.add_argument("--figure", action="append", default=[],
                      help="script.py[,config.yaml][,scope][,label][:width]，可重复")
    p_pa.add_argument("--width-mm", type=float, default=None, help="默认目标宽度 mm")
    p_pa.add_argument("--out", default=None, help="审计 JSON 输出路径")
    p_pa.add_argument("--json", action="store_true", help="JSON 输出（默认人类可读表）")
    p_pc = plate_sub.add_parser("compare", help="跨图角色表：实测值 + Comparable/Editable/Conformant")
    p_pc.add_argument("manifest", nargs="?", default=None, help="plate.yaml 清单路径")
    p_pc.add_argument("--figure", action="append", default=[],
                      help="script.py[,config.yaml][,scope][,label][:width]，可重复（无清单时用）")
    p_pc.add_argument("--width-mm", type=float, default=None, help="默认目标宽度 mm（无清单时用）")
    p_pc.add_argument("--out", default=None, help="compare JSON 输出路径")
    p_pc.add_argument("--json", action="store_true", help="JSON 输出（默认人类可读表）")
    p_pu = plate_sub.add_parser("unify", help="由共享 token 规划并（--apply 才）统一源码参数")
    p_pu.add_argument("manifest", nargs="?", default=None, help="plate.yaml 清单路径（给则由 design token 驱动）")
    p_pu.add_argument("--figure", action="append", default=[],
                      help="script.py[,config.yaml][,scope][,label][:width]，可重复（无清单时用）")
    p_pu.add_argument("--width-mm", type=float, default=None, help="默认目标宽度 mm（无清单时用）")
    p_pu.add_argument("--target-width-mm", type=float, default=None, help="统一后的目标宽度 mm（覆盖清单）")
    p_pu.add_argument("--axis-pt", type=float, default=None, help="轴标题目标 pt（覆盖 token）")
    p_pu.add_argument("--tick-pt", type=float, default=None, help="刻度目标 pt（覆盖 token）")
    p_pu.add_argument("--line-pt", type=float, default=None, help="线宽目标 pt（覆盖 token）")
    p_pu.add_argument("--apply", action="store_true", help="写入源码并重审计")
    p_pr = plate_sub.add_parser("receipt", help="输出可复算 JSON 回执（含三边界与 token 来源）")
    p_pr.add_argument("manifest", nargs="?", default=None, help="plate.yaml 清单路径（给则回执带清单哈希与 token 来源）")
    p_pr.add_argument("--figure", action="append", default=[],
                      help="script.py[,config.yaml][,scope][,label][:width]，可重复（无清单时用）")
    p_pr.add_argument("--width-mm", type=float, default=None, help="默认目标宽度 mm（无清单时用）")
    p_pr.add_argument("--out", default=None, help="回执 JSON 输出路径")

    p_overlay = subparsers.add_parser("overlay", help="Verified Style Overlay（不改原始 Python）")
    overlay_sub = p_overlay.add_subparsers(dest="overlay_cmd", required=True)
    for name in ("inventory", "apply"):
        p = overlay_sub.add_parser(name)
        p.add_argument("--script", required=True)
        p.add_argument("--config", default=None)
        p.add_argument("--scope", default=None)
        if name == "apply":
            p.add_argument("--edits", default=None, help="增量 upsert JSON list: target_id + absolute value")
            p.add_argument("--overlay", required=True, help="声明式样式 JSON，不是 Python 改写")
            p.add_argument("--expected-sha256", default=None, help="更新既有 Overlay 的内容哈希")
            p.add_argument("--remove", action="append", default=[], help="显式移除一个已保存 target_id，可重复")
            p.add_argument("--allow-draft", action="store_true", help="显式允许局部通过但整图 QA 失败的草稿")
    p_or = overlay_sub.add_parser("render", help="从原图与持久化 Overlay 重建、验证、渲染")
    p_or.add_argument("overlay")
    p_or.add_argument("--output", default=None)

    args = parser.parse_args(argv)

    if args.subcommand == "validate":
        return cmd_validate(args)
    elif args.subcommand == "overlay":
        return cmd_overlay(args)
    elif args.subcommand == "render":
        return cmd_render(args)
    elif args.subcommand == "export":
        args.strict = True
        return cmd_render(args)
    elif args.subcommand == "inventory":
        return cmd_inventory(args)
    elif args.subcommand == "inspect":
        return cmd_inspect(args)
    elif args.subcommand == "list-params":
        return cmd_list_params(args)
    elif args.subcommand == "contract":
        if args.contract_cmd == "discover":
            return cmd_contract_discover(args)
        elif args.contract_cmd == "verify":
            return cmd_contract_verify(args)

    elif args.subcommand == "export-params":
        return cmd_export_params(args)
    elif args.subcommand in ("final-size", "audit-final-size"):
        return cmd_final_size(args)
    elif args.subcommand == "final-size-apply":
        return cmd_final_size_apply(args)
    elif args.subcommand == "plate":
        if args.plate_cmd == "audit":
            return cmd_plate_audit(args)
        elif args.plate_cmd == "compare":
            return cmd_plate_compare(args)
        elif args.plate_cmd == "unify":
            return cmd_plate_unify(args)
        elif args.plate_cmd == "receipt":
            return cmd_plate_receipt(args)
    elif args.subcommand == "ui":
        return cmd_ui(args)
    elif args.subcommand == "agent":
        return cmd_agent(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
