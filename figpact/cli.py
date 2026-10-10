"""figpact 命令行工具。"""
import argparse
import importlib.util
import json
import subprocess
import sys
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

from pathlib import Path
from typing import Optional
import yaml
from figpact.config import ConfigError, check_schema
from figpact.params import export_params_catalog, audit_artists_coverage


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


def cmd_inventory(args: argparse.Namespace) -> int:
    """转发 --inventory 给脚本，把 JSON 打印成人看的清单，支持生效检查。"""
    script = Path(args.script).expanduser().resolve()
    if not script.is_file():
        print(f"[错误] 脚本不存在：{script}", file=sys.stderr)
        return 1

    cmd = [sys.executable, "-X", "utf8", str(script), "--inventory"]
    if getattr(args, "check_effect", False):
        cmd.append("--check-effect")
    if args.config:
        cmd.extend(["--config", str(Path(args.config).expanduser().resolve())])

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
    effects = data.get("param_effects", {})

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

    if effects:
        print("\n=== 参数生效检查 (Effectiveness Check) ===")
        no_effect_list = []
        for p, info in effects.items():
            st = info.get("status", "UNKNOWN")
            cnt = info.get("bound_gids_count", 0)
            print(f"  • {p:<24} 状态: {st:<10} 关联图元数: {cnt}")
            if st == "NO_EFFECT":
                no_effect_list.append(p)
        if no_effect_list:
            print(f"\n[警告] 发现未生效参数 (NO_EFFECT): {', '.join(no_effect_list)}", file=sys.stderr)
        else:
            print("\n[OK] 所有被检查的绑定参数均通过扰动生效验证！")

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


def _run_script_inventory(script: Path, cfg_path: Path) -> dict:
    cmd = [sys.executable, "-X", "utf8", str(script), "--config", str(cfg_path), "--inventory"]
    res = subprocess.run(cmd, cwd=str(script.parent), capture_output=True, text=True, encoding="utf-8")
    text = res.stdout.strip()
    idx = text.find("{")
    if idx >= 0:
        try:
            return json.loads(text[idx:])
        except Exception:
            pass
    return {}


def _run_script_strict(script: Path, cfg_path: Path) -> tuple[int, list[str]]:
    cmd = [sys.executable, "-X", "utf8", str(script), "--config", str(cfg_path), "--strict"]
    res = subprocess.run(cmd, cwd=str(script.parent), capture_output=True, text=True, encoding="utf-8")
    qa_lines = []
    for line in (res.stdout + "\n" + res.stderr).splitlines():
        l = line.strip()
        if "[QA]" in l or "[验收]" in l or "[未豁免]" in l or "超出坐标框" in l or "压线" in l or "NO_FEASIBLE_SLOT" in l:
            qa_lines.append(l)
    return res.returncode, qa_lines


def cmd_try(args: argparse.Namespace) -> int:
    """把 patch/--set 在内存中合并到当前配置，试算位移、QA 差异与参数可行区间。"""
    import tempfile
    from figpact.qa import signature

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

        base_yaml.write_text(yaml.safe_dump(base_config), encoding="utf-8")
        patched_yaml.write_text(yaml.safe_dump(patched_config), encoding="utf-8")

        # 1. 运行 baseline 与 try 的 inventory
        inv_before = _run_script_inventory(script, base_yaml)
        inv_after = _run_script_inventory(script, patched_yaml)

        # 2. 运行 baseline 与 try 的 strict 检查
        code_before, qa_before = _run_script_strict(script, base_yaml)
        code_after, qa_after = _run_script_strict(script, patched_yaml)

        # 计算对象位移 (mm)
        print("=== 1. 对象位移 (Movement Delta) ===")
        snap_map_before = {it["gid"]: it.get("snapshot", {}) for it in inv_before.get("items", [])}
        snap_map_after = {it["gid"]: it.get("snapshot", {}) for it in inv_after.get("items", [])}
        moved_count = 0
        # 获取 dpi 用于像素转毫米
        px_per_mm = 300.0 / 25.4  # 标准 dpi
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

        # 计算 QA 差异
        print("\n=== 2. QA 差异 (QA Delta) ===")
        sig_before = {signature(q): q for q in qa_before}
        sig_after = {signature(q): q for q in qa_after}

        added_sigs = set(sig_after.keys()) - set(sig_before.keys())
        removed_sigs = set(sig_before.keys()) - set(sig_after.keys())

        if added_sigs:
            print("【新增阻断/警告】:")
            for s in sorted(added_sigs):
                print(f"  + {sig_after[s]}")
        else:
            print("【新增阻断/警告】: 无")

        if removed_sigs:
            print("【消除阻断/警告】:")
            for s in sorted(removed_sigs):
                print(f"  - {sig_before[s]}")
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
                c_ret, _ = _run_script_strict(script, cand_yaml)
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
    args = parser.parse_args(argv)

    if args.subcommand == "validate":
        return cmd_validate(args)
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
    elif args.subcommand == "try":
        return cmd_try(args)

    elif args.subcommand == "export-params":
        return cmd_export_params(args)
    elif args.subcommand == "audit-params":
        return cmd_audit_params(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
