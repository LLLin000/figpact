"""figpact 命令行工具。"""
import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Optional
import yaml
from figpact.config import ConfigError, check_schema


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
    """转发 --inventory 给脚本，把 JSON 打印成人看的清单。"""
    script = Path(args.script).expanduser().resolve()
    if not script.is_file():
        print(f"[错误] 脚本不存在：{script}", file=sys.stderr)
        return 1

    cmd = [sys.executable, "-X", "utf8", str(script), "--inventory"]
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

    # inventory --script <py> --config <yaml>
    p_inv = subparsers.add_parser("inventory", help="获取可见图元清点清单")
    p_inv.add_argument("--script", required=True, help="绘图脚本路径")
    p_inv.add_argument("--config", default=None, help="配置文件 YAML 路径")

    # inspect <gid> --script <py> --config <yaml>
    p_ins = subparsers.add_parser("inspect", help="检查特定 gid 的图元信息")
    p_ins.add_argument("gid", help="要检查的图元 gid")
    p_ins.add_argument("--script", required=True, help="绘图脚本路径")
    p_ins.add_argument("--config", default=None, help="配置文件 YAML 路径")

    # export --script <py> --config <yaml> (等价于 render --strict)
    p_exp = subparsers.add_parser("export", help="导出图表（等价于 render --strict）")
    p_exp.add_argument("--script", required=True, help="绘图脚本路径")
    p_exp.add_argument("--config", default=None, help="配置文件 YAML 路径")

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

    return 0


if __name__ == "__main__":
    sys.exit(main())
