#!/usr/bin/env python3
"""端到端耗时记录：冷启动 / 连续预览 / QA / strict 发布，原生与旧脚本分开列。

只**记录**，不判定。耗时是机器状态，不是正确性——所以这里没有任何断言，
结果写进 JSON（`--json`）并且原样打印；测试套件不许拿这些数字当门槛。

    python -X utf8 tests/benchmarks/bench_vnext.py --json bench.json
    python -X utf8 tests/benchmarks/bench_vnext.py --lanes cold_import,warm_preview --repeat 3

路径（三类，互不混算）：
- `cold_*`：每次都在**新解释器**里跑（import + 构建 + 渲染），算的是冷路径；
- `warm_preview` / `warm_qa`：同一个进程里连续 N 次，算的是热路径；
- `legacy_*`：examples 里的真实旧脚本（它自己读 CSV、自己发布），冷路径对照。
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
FIXTURES_DIR = ROOT / "tests" / "fixtures"
NATIVE_FIXTURES = ("native_ftir", "native_nmr", "native_panels", "native_mixed")
LEGACY_FTIR = ROOT / "examples" / "ftir" / "plot_ftir.py"
DEFAULT_TIMEOUT_S = 900.0


# ── 采样 ────────────────────────────────────────────────────────────────────
def summarise(samples: list[float]) -> dict:
    """只做统计，不做判断（没有阈值、没有 pass/fail）。"""
    return {
        "n": len(samples),
        "samples_s": [round(v, 6) for v in samples],
        "min_s": round(min(samples), 6),
        "median_s": round(statistics.median(samples), 6),
        "mean_s": round(statistics.fmean(samples), 6),
        "max_s": round(max(samples), 6),
    }


def _python(code: str, cwd: Path, timeout: float) -> float:
    """新解释器里跑一段代码，返回墙钟秒数（失败直接抛，不吞）。"""
    started = time.perf_counter()
    proc = subprocess.run([sys.executable, "-X", "utf8", "-c", code], cwd=str(cwd),
                          capture_output=True, text=True, encoding="utf-8", timeout=timeout,
                          env={**os.environ, "MPLBACKEND": "Agg"})
    elapsed = time.perf_counter() - started
    if proc.returncode != 0:
        raise RuntimeError(f"子进程失败（rc={proc.returncode}）：\n{proc.stdout}\n{proc.stderr}")
    return elapsed


def _argv_once(argv: list[str], cwd: Path, timeout: float, env: dict | None = None) -> float:
    started = time.perf_counter()
    proc = subprocess.run(argv, cwd=str(cwd), capture_output=True, text=True, encoding="utf-8",
                          timeout=timeout, env={**os.environ, "MPLBACKEND": "Agg", **(env or {})})
    elapsed = time.perf_counter() - started
    if proc.returncode != 0:
        raise RuntimeError(f"命令失败（rc={proc.returncode}）：{' '.join(argv)}\n{proc.stderr[-2000:]}")
    return elapsed


def _import_prelude() -> str:
    return ("import sys, matplotlib; sys.path.insert(0, '.'); matplotlib.use('Agg'); "
            "import matplotlib.pyplot as plt, importlib; ")


# ── 冷路径 ──────────────────────────────────────────────────────────────────
def cold_import(name: str, timeout: float) -> list[float]:
    code = _import_prelude() + f"m = importlib.import_module('tests.fixtures.{name}'); assert m.SCOPES"
    return [_python(code, ROOT, timeout)]


def cold_build(name: str, timeout: float) -> list[float]:
    code = (_import_prelude() +
            f"m = importlib.import_module('tests.fixtures.{name}'); "
            "cfg = m.load_config(); sci = m.load_science(); "
            "[ (lambda f: (f[0].canvas.draw(), plt.close(f[0])))(m.build_scene(sci, cfg, s)) for s in m.SCOPES ]")
    return [_python(code, ROOT, timeout)]


def cold_preview(name: str, timeout: float, out_dir: Path) -> list[float]:
    target = (out_dir / f"cold_{name}.png").as_posix()
    code = (_import_prelude() +
            f"m = importlib.import_module('tests.fixtures.{name}'); "
            "cfg = m.load_config(); sci = m.load_science(); "
            "s = m.SCOPES[0]; fig, reg = m.build_scene(sci, cfg, s); "
            f"fig.savefig({target!r}, dpi=float(cfg['render_dpi'])); plt.close(fig)")
    return [_python(code, ROOT, timeout)]


def strict_cli(name: str, timeout: float, out_dir: Path) -> list[float]:
    script = FIXTURES_DIR / f"{name}.py"
    argv = [sys.executable, "-X", "utf8", str(script), "--strict", "--probe", str(out_dir / f"strict_{name}")]
    return [_argv_once(argv, script.parent, timeout)]


def legacy_cold_import(timeout: float) -> list[float]:
    code = ("import sys, matplotlib; sys.path.insert(0, '.'); matplotlib.use('Agg'); "
            "import importlib.util; "
            f"spec = importlib.util.spec_from_file_location('legacy_ftir', r'{LEGACY_FTIR}'); "
            "mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); "
            "assert mod.SCOPES")
    return [_python(code, ROOT, timeout)]


def legacy_strict_cli(timeout: float, out_dir: Path) -> list[float]:
    if not LEGACY_FTIR.is_file():
        raise FileNotFoundError(f"旧脚本不存在：{LEGACY_FTIR}")
    argv = [sys.executable, "-X", "utf8", str(LEGACY_FTIR), "--strict", "--probe", str(out_dir / "legacy_ftir")]
    return [_argv_once(argv, LEGACY_FTIR.parent, timeout)]


# ── 热路径（同进程连续）─────────────────────────────────────────────────────
def warm_preview(name: str, repeat: int, out_dir: Path) -> list[float]:
    import importlib

    module = importlib.import_module(f"tests.fixtures.{name}")
    cfg = module.load_config()
    science = module.load_science()
    scope = module.SCOPES[0]
    target = out_dir / f"warm_{name}.png"
    samples: list[float] = []
    for _ in range(repeat):
        started = time.perf_counter()
        fig, _reg = module.build_scene(science, cfg, scope)
        fig.savefig(target, dpi=float(cfg["render_dpi"]))
        plt.close(fig)
        samples.append(time.perf_counter() - started)
    return samples


def warm_qa(name: str, repeat: int) -> list[float]:
    import importlib

    from figpact import qa

    module = importlib.import_module(f"tests.fixtures.{name}")
    cfg = module.load_config()
    science = module.load_science()
    samples: list[float] = []
    for scope in module.SCOPES:
        for _ in range(repeat):
            started = time.perf_counter()
            fig, _reg = module.build_scene(science, cfg, scope)
            fig.canvas.draw()
            qa.blocking_problems(fig)
            plt.close(fig)
            samples.append(time.perf_counter() - started)
    return samples


# ── 驱动 ────────────────────────────────────────────────────────────────────
def lane_table(args) -> dict:
    """返回 {lane 名: 采样函数}（按 --lanes 过滤）。"""
    lanes: dict[str, object] = {}
    for name in args.fixtures:
        lanes[f"cold_import_{name}"] = lambda n=name: cold_import(n, args.timeout)
        lanes[f"cold_build_{name}"] = lambda n=name: cold_build(n, args.timeout)
        lanes[f"cold_preview_{name}"] = lambda n=name: cold_preview(n, args.timeout, args.work)
        lanes[f"strict_cli_{name}"] = lambda n=name: strict_cli(n, args.timeout, args.work)
        lanes[f"warm_preview_{name}"] = lambda n=name: warm_preview(n, args.repeat, args.work)
        lanes[f"warm_qa_{name}"] = lambda n=name: warm_qa(n, args.repeat)
    if "legacy" in args.lanes or "all" in args.lanes:
        lanes["legacy_cold_import"] = lambda: legacy_cold_import(args.timeout)
        lanes["legacy_strict_cli"] = lambda: legacy_strict_cli(args.timeout, args.work)
    if args.lanes and "all" not in args.lanes:
        wanted = set(args.lanes)
        lanes = {k: v for k, v in lanes.items() if k in wanted or any(k.startswith(w) for w in wanted)}
    return lanes


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    parser = argparse.ArgumentParser(prog=Path(__file__).name, allow_abbrev=False,
                                     description="记录冷启动/连续预览/QA/strict 的端到端墙钟耗时（只测不判）")
    parser.add_argument("--fixtures", nargs="*", default=list(NATIVE_FIXTURES),
                        help=f"原生夹具名（默认 {list(NATIVE_FIXTURES)}）")
    parser.add_argument("--lanes", nargs="*", default=["all"],
                        help="筛选用：all / legacy / cold_import / cold_build / cold_preview / "
                             "strict_cli / warm_preview / warm_qa / <具体 lane 名>")
    parser.add_argument("--repeat", type=int, default=5, help="热路径连续次数")
    parser.add_argument("--json", default=None, help="把结果写进这个 JSON 文件")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S, help="单条命令超时（秒）")
    args = parser.parse_args(argv)
    if args.repeat < 1:
        parser.error("--repeat 至少为 1")

    work = Path(tempfile.mkdtemp(prefix="figpact-bench-"))
    args.work = work
    lanes = lane_table(args)

    result = {
        "schema": "figpact.vnext.benchmark/1",
        "note": "wall-clock only; no thresholds are asserted anywhere in this repository's tests",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "machine": platform.machine(),
            "matplotlib": matplotlib.__version__,
            "dpi_default": float(matplotlib.rcParams["figure.dpi"]),
            "cpu_count": os.cpu_count(),
            "repeat": args.repeat,
        },
        "work_dir": str(work),
        "lanes": {},
    }
    print(f"[bench] 工作目录 {work}")
    print(f"{'lane':<32}{'n':>4}{'min':>10}{'median':>10}{'max':>10}")
    for lane, fn in lanes.items():
        samples = fn()
        block = summarise(list(samples))
        result["lanes"][lane] = block
        print(f"{lane:<32}{block['n']:>4}{block['min_s']:>10.3f}{block['median_s']:>10.3f}"
              f"{block['max_s']:>10.3f}")

    if args.json:
        target = Path(args.json).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[bench] 已写出 {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
