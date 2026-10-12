#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""G6 引擎级分母：冻结 NMR 场景的配对采样。

**这是什么**：把 `examples/nmr/08 NMR.py` + `nmr.yaml` 的**真实** IntentSession 流程
（evaluate → accept → undo）冻结下来，跑 n 次配对采样，把每个阶段的**引擎级分母**
如实记录成 JSON：会话冷构造 / evaluate / accept / undo 的墙钟，以及真实包装计数器
（`matplotlib.figure.Figure.draw`、`FigureSession.build_candidate`、`figpact.qa`
公开函数）给出的调用次数与耗时，外加 history 检查点数量与 state 目录字节数。

**这不是什么**（读到这里的引用方请注意）：

* **不是三臂 Agent 盲测**。这里没有任何人、没有 Agent 会话、没有对照组、没有臂间
  随机化；每个样本只是同一台机器上的同一个冻结场景。
* **不能拿来宣称端到端提速**。分母只覆盖「引擎在一次意图往返里实际做了什么」，
  不含 Agent 的读图/思考/工具往返/重试，也不含真人判断。README 里的 ~4.1% 那类
  对照口径与这里的数字**不可混算**。
* **热几何函数 ≠ 完整 Agent 任务**。这里连「完整会话往返」都只是一部分，别把
  `undo` 的 7 秒当成「Agent 帮用户改一张图要 7 秒」。

**为什么一个样本一个进程**：`examples/nmr/08 NMR.py` 的 `_BASELINE_SCENES` 是模块级
缓存、`layout_contract` 复用该缓存构建的基线；同一个解释器里第二次构造顶层
`IntentSession` 会以 `ContractError: Dangling parameter objects` 失败（已实测）。所以
每个样本各自冷起一个进程（这也让"冷构造"是名副其实的冷路径），脚本**不修改任何
产品代码**，只是在自己进程里运行时包装真实方法。

用法：

    python -X utf8 tests/benchmarks/nmr_engine_denominators.py            # n=5，写 g6-bench JSON
    python -X utf8 tests/benchmarks/nmr_engine_denominators.py --n 3
    python -X utf8 tests/benchmarks/nmr_engine_denominators.py --self-check   # 秒级，不建图

产物：`I:/figpact-test-archive/g6-bench/engine_denominators.json`（含环境、时间戳、
n、每样本原始记录、每阶段均值/最小/最大值）。只读 examples、只写 g6-* 归档目录。
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import statistics
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:  # 子进程里 figpact 必须可导入（脚本目录不在 repo 根）
    sys.path.insert(0, str(ROOT))
DEFAULT_ARCHIVE = Path("I:/figpact-test-archive")
DEFAULT_OUT = "g6-bench/engine_denominators.json"
DEFAULT_N = 5
PHASES = ("construct", "evaluate", "accept", "undo")

#: 冻结场景。改这里 = 换场景，不是调参。
SCENARIO = {
    "script": "examples/nmr/08 NMR.py",
    "config": "examples/nmr/nmr.yaml",
    "scope": "main",
    "dpi": 600,
    "target_gid": "fig2_nmr.main.peak.vancho.3p91",
    "delta_mm": [0.0, 0.15],
    "tolerance_mm": 0.01,
    "history": True,
    "operation": "translate",
}

NOT_A_CLAIM = {
    "is_engine_level_denominator": True,
    "is_three_arm_agent_blind_test": False,
    "claims_end_to_end_speedup": False,
    "counts_are_wrapped": True,
    "note": "引擎级分母（真实包装计数 + 墙钟分阶段），不是三臂 Agent 盲测，"
            "不得据此宣称端到端提速；热几何阶段 ≠ 完整 Agent 任务。",
}


# ── 运行时计数：包装真实方法，不估算 ─────────────────────────────────────────
class Probe:
    """`Figure.draw` / `FigureSession.build_candidate` / `figpact.qa` 公开函数的真实调用计数。

    耗时口径：`qa_seconds` 只累加**最外层** QA 调用的墙钟（`blocking_problems` 里面再调
    `check_text_overlap` 时，子调用的时间已经在父的 elapsed 里，不重复计）；每个函数的
    逐项 `qa_by_function` 则各算各的，父子会重叠——这是"哪个函数被调了几次"的账本，
    不是"QA 一共花了多久"的账本。
    """

    def __init__(self) -> None:
        self.draws = 0
        self.builds = 0
        self.qa: dict[str, dict] = {}
        self.qa_outer_calls = 0
        self.qa_outer_seconds = 0.0
        self._qa_depth = 0

    def snapshot(self) -> dict:
        return {"figure_draw_calls": self.draws, "build_candidate_calls": self.builds,
                "qa_calls": self.qa_outer_calls, "qa_seconds": self.qa_outer_seconds,
                "qa_by_function": {name: dict(entry) for name, entry in self.qa.items()}}

    @staticmethod
    def delta(before: dict, after: dict) -> dict:
        by_function = {}
        for name, entry in after["qa_by_function"].items():
            old = before["qa_by_function"].get(name, {"calls": 0, "seconds": 0.0})
            by_function[name] = {"calls": entry["calls"] - old["calls"],
                                 "seconds": entry["seconds"] - old["seconds"]}
        return {"figure_draw_calls": after["figure_draw_calls"] - before["figure_draw_calls"],
                "build_candidate_calls": after["build_candidate_calls"] - before["build_candidate_calls"],
                "qa_calls": after["qa_calls"] - before["qa_calls"],
                "qa_seconds": after["qa_seconds"] - before["qa_seconds"],
                "qa_by_function": by_function}


def install_probe() -> Probe:
    """包装真实方法（只在本进程内替换属性，产品源码一个字节不动）。"""
    probe = Probe()
    import matplotlib.figure
    from figpact import qa as qa_mod
    from figpact.session import FigureSession

    original_draw = matplotlib.figure.Figure.draw

    def count_draw(self, renderer):
        probe.draws += 1
        return original_draw(self, renderer)

    matplotlib.figure.Figure.draw = count_draw

    original_build = FigureSession.build_candidate

    def count_build_candidate(self, config_dict):
        probe.builds += 1
        return original_build(self, config_dict)

    FigureSession.build_candidate = count_build_candidate

    for name in dir(qa_mod):
        function = getattr(qa_mod, name)
        if name.startswith("_") or isinstance(function, type) or not callable(function):
            continue
        setattr(qa_mod, name, _wrap_qa(probe, name, function))
    return probe


def _wrap_qa(probe: Probe, name: str, function):
    import functools

    @functools.wraps(function)
    def wrapper(*args, **kwargs):
        outer = probe._qa_depth == 0
        probe._qa_depth += 1
        started = time.perf_counter()
        try:
            return function(*args, **kwargs)
        finally:
            elapsed = time.perf_counter() - started
            probe._qa_depth -= 1
            entry = probe.qa.setdefault(name, {"calls": 0, "seconds": 0.0})
            entry["calls"] += 1
            entry["seconds"] += elapsed
            if outer:
                probe.qa_outer_calls += 1
                probe.qa_outer_seconds += elapsed

    return wrapper


class Phase:
    """一个阶段：墙钟 + 阶段内真实计数增量（异常也照记）。"""

    def __init__(self, probe: Probe, name: str) -> None:
        self.probe, self.name = probe, name
        self.seconds = 0.0
        self.counters: dict = {}

    def __enter__(self) -> "Phase":
        self._before = self.probe.snapshot()
        self._started = time.perf_counter()
        return self

    def __exit__(self, *_exc) -> bool:
        self.seconds = time.perf_counter() - self._started
        self.counters = Probe.delta(self._before, self.probe.snapshot())
        return False

    def record(self) -> dict:
        return {"seconds": self.seconds, **self.counters}


# ── 环境 ────────────────────────────────────────────────────────────────────
def apply_environment(archive: Path, state_home: Path) -> dict:
    """TEMP/TMP/TMPDIR/MPLCONFIGDIR/FIGPACT_STATE_HOME 全部指向 g6-*；强制 Agg。"""
    temp, mpl = archive / "g6-tmp", archive / "g6-mpl"
    for directory in (temp, mpl, state_home):
        directory.mkdir(parents=True, exist_ok=True)
    values = {"TEMP": temp, "TMP": temp, "TMPDIR": temp, "MPLCONFIGDIR": mpl,
              "FIGPACT_STATE_HOME": state_home, "MPLBACKEND": "Agg",
              "PYTHONDONTWRITEBYTECODE": "1"}
    for key, value in values.items():
        os.environ[key] = str(value)
    return {key: str(value) for key, value in values.items()}


def fresh_directory(path: Path, archive: Path) -> Path:
    """只清自己的归档目录：必须在 archive 下的 `g6-*` 子树里，别的手别伸。"""
    resolved, root = path.resolve(), archive.resolve()
    if root not in resolved.parents:
        raise SystemExit(f"拒绝清理归档根之外的目录：{resolved}")
    first = resolved.relative_to(root).parts[0]
    if not first.startswith("g6-"):
        raise SystemExit(f"拒绝清理非 g6-* 归档目录：{resolved}")
    shutil.rmtree(resolved, ignore_errors=True)
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


# ── 样本（子进程）────────────────────────────────────────────────────────────
def _request(session, operation_id: str) -> dict:
    frame = session.snapshot()
    scene = json.loads(frame["scene_json"])
    node = next(item for item in scene["nodes"] if item["gid"] == SCENARIO["target_gid"])
    guide = node.get("linked_guide_gid")
    return {"operation_id": operation_id, **frame["session"], "scope": SCENARIO["scope"],
            "target_gid": SCENARIO["target_gid"], "operation": SCENARIO["operation"],
            "delta_mm": list(SCENARIO["delta_mm"]), "tolerance_mm": SCENARIO["tolerance_mm"],
            "preserve": {"science": True, "follow_gids": [guide] if guide else [],
                         "fixed_gids": []},
            "demonstration": {"display_only": True}}


def _decision(session, operation_id: str, action: str) -> dict:
    return session.decide({"operation_id": operation_id, "decision": action,
                           **session.snapshot()["session"]})


def _history_state(session) -> dict:
    """公开 API 真实读一次 store，再 stat 一次 state 目录（都不是估算）。"""
    if session is None:
        return {"error": "no session"}
    started = time.perf_counter()
    records = session.history()
    read_seconds = time.perf_counter() - started
    frame = session.snapshot()
    entry = frame["session"].get("history") or {}
    directory = entry.get("directory")
    files = total = sqlite_bytes = blob_bytes = 0
    if directory:
        for path in Path(directory).rglob("*"):
            if not path.is_file():
                continue
            size = path.stat().st_size
            files += 1
            total += size
            if path.suffix == ".sqlite3":
                sqlite_bytes += size
            elif "blobs" in path.parts:
                blob_bytes += size
    return {"checkpoint_count": len(records), "status": entry.get("status"),
            "head": entry.get("head"), "last_kinds": [record["kind"] for record in records[-3:]],
            "accepted_operation_ids": list(frame["session"]["accepted_operation_ids"]),
            "frame_revision": frame["frame_revision"], "directory": directory,
            "files": files, "bytes": total, "sqlite_bytes": sqlite_bytes,
            "blob_bytes": blob_bytes, "read_seconds": read_seconds}


def _step(record: dict, probe: Probe, session_holder: list, name: str, action) -> object:
    """跑一个阶段：记墙钟 + 计数；阶段外再做一次 history 读取（不污染阶段耗时）。"""
    phase = Phase(probe, name)
    result = None
    try:
        with phase:
            result = action()
    except BaseException as error:  # 记录不吞掉结论：错误进 JSON，样本标 unusable
        record["errors"].append({"phase": name, "error": f"{type(error).__name__}: {error}"})
    record["phases"][name] = phase.record()
    record["history_after"][name] = _history_state(session_holder[0])
    return result


def worker_sample(index: int, state_home: Path, archive: Path) -> dict:
    from figpact.intents import IntentSession
    from figpact.session import loader_counters

    apply_environment(archive, state_home)
    probe = install_probe()
    record: dict = {"role": "sample", "index": index, "state_home": str(state_home),
                    "phases": {}, "history_after": {}, "errors": [],
                    "loader_counters_before": loader_counters()}
    session_holder: list = [None]
    operation_id = uuid.uuid4().hex

    def construct():
        session_holder[0] = IntentSession(
            script=ROOT / SCENARIO["script"], config=ROOT / SCENARIO["config"],
            scope=SCENARIO["scope"], dpi=SCENARIO["dpi"], history=SCENARIO["history"],
            state_home=state_home)
        return session_holder[0]

    session = _step(record, probe, session_holder, "construct", construct)
    if session is None:
        record["usable"] = False
        record["loader_counters_after"] = loader_counters()
        return record

    frame = session.snapshot()
    record["baseline"] = {"frame_revision": frame["frame_revision"],
                          "scene_revision": frame["session"]["scene_revision"]}
    record["construct_session"] = frame["session"]

    evaluation = _step(record, probe, session_holder, "evaluate",
                       lambda: session.evaluate(_request(session, operation_id)))
    record["evaluate"] = {key: (evaluation or {}).get(key) for key in
                          ("status", "evaluation_state", "verification_level", "message",
                           "target_delta_mm", "measured_delta_mm", "error_mm")}
    if isinstance(evaluation, dict) and evaluation.get("checks") is not None:
        record["evaluate"]["checks"] = [{"check": check.get("check"), "status": check.get("status")}
                                        for check in evaluation["checks"]]

    decision = _step(record, probe, session_holder, "accept",
                     lambda: _decision(session, operation_id, "accept"))
    record["accept"] = {key: (decision or {}).get(key) for key in
                        ("status", "persistence_state", "verification_level",
                         "measured_delta_mm", "error_mm")}

    undo = _step(record, probe, session_holder, "undo",
                 lambda: _decision(session, operation_id, "undo"))
    record["undo"] = {key: (undo or {}).get(key) for key in
                      ("status", "persistence_state", "verification_level")}

    final = session.snapshot()
    record["restored"] = {
        "accepted_operation_ids": list(final["session"]["accepted_operation_ids"]),
        "frame_revision_matches_baseline": final["frame_revision"] == record["baseline"]["frame_revision"],
        "baseline_frame_revision": record["baseline"]["frame_revision"],
        "final_frame_revision": final["frame_revision"]}
    record["loader_counters_after"] = loader_counters()
    record["totals"] = _totals(record)
    record["usable"] = bool(
        record["evaluate"].get("status") == "OK"
        and record["accept"].get("status") == "OK"
        and record["undo"].get("status") == "OK"
        and not record["restored"]["accepted_operation_ids"]
        and record["restored"]["frame_revision_matches_baseline"])
    try:
        session.close()
    except BaseException as error:
        record["errors"].append({"phase": "close", "error": f"{type(error).__name__}: {error}"})
    return record


def _totals(record: dict) -> dict:
    """样本内各阶段之和。**不含解释器启动**，也不是 Agent 往返。"""
    total = {"seconds": 0.0, "figure_draw_calls": 0, "build_candidate_calls": 0,
             "qa_calls": 0, "qa_seconds": 0.0, "history_read_seconds": 0.0}
    for name in PHASES:
        phase = record["phases"].get(name) or {}
        for key in ("seconds", "figure_draw_calls", "build_candidate_calls", "qa_calls",
                    "qa_seconds"):
            total[key] += phase.get(key, 0)
    for entry in record["history_after"].values():
        if isinstance(entry, dict):
            total["history_read_seconds"] += entry.get("read_seconds", 0.0)
    return total


def worker_construct_only(role: str, state_home: Path, archive: Path) -> dict:
    """一次性构造测量：`cold_start`（全新 state）与 `session_reopen`（已有 history）。"""
    from figpact.intents import IntentSession
    from figpact.session import loader_counters

    apply_environment(archive, state_home)
    probe = install_probe()
    record: dict = {"role": role, "state_home": str(state_home), "phases": {},
                    "history_after": {}, "errors": [],
                    "loader_counters_before": loader_counters()}
    holder: list = [None]

    def construct():
        holder[0] = IntentSession(
            script=ROOT / SCENARIO["script"], config=ROOT / SCENARIO["config"],
            scope=SCENARIO["scope"], dpi=SCENARIO["dpi"], history=SCENARIO["history"],
            state_home=state_home)
        return holder[0]

    session = _step(record, probe, holder, "construct", construct)
    if session is not None:
        record["session"] = session.snapshot()["session"]
        record["evaluate_allowed"] = bool(session.snapshot()["session"]["can_evaluate"])
        try:
            session.close()
        except BaseException as error:
            record["errors"].append({"phase": "close",
                                     "error": f"{type(error).__name__}: {error}"})
    record["usable"] = session is not None
    record["loader_counters_after"] = loader_counters()
    return record


# ── 驱动（父进程）────────────────────────────────────────────────────────────
def run_child(mode: str, archive: Path, state_home: Path, out_path: Path,
              index: int | None, timeout: float) -> dict:
    argv = [sys.executable, "-X", "utf8", str(Path(__file__).resolve()),
            f"--worker-{mode}", "--archive-root", str(archive),
            "--state-home", str(state_home), "--worker-out", str(out_path)]
    if index is not None:
        argv += ["--index", str(index)]
    started = time.perf_counter()
    process = subprocess.run(argv, cwd=str(ROOT), capture_output=True, text=True,
                             encoding="utf8", errors="replace", timeout=timeout)
    wall = time.perf_counter() - started
    payload = json.loads(out_path.read_text(encoding="utf8")) if out_path.is_file() else {}
    payload.setdefault("errors", [])
    payload.setdefault("usable", False)
    if process.returncode:
        payload["errors"].append({"phase": "child", "error": f"exit code {process.returncode}"})
        payload["child_stderr_tail"] = (process.stderr or "")[-2000:]
    payload["process_exit_code"] = process.returncode
    payload["process_wall_seconds"] = wall  # 含解释器启动，**不并入阶段分母**
    return payload


def summarise(values: list[float]) -> dict:
    """只做统计，不判定（没有阈值、没有 pass/fail）。"""
    clean = [value for value in values if isinstance(value, (int, float))]
    if not clean:
        return {"n": 0, "mean": None, "min": None, "max": None}
    return {"n": len(clean), "mean": statistics.fmean(clean), "min": min(clean),
            "max": max(clean)}


def aggregate(samples: list[dict]) -> dict:
    def phases_of(sample: dict) -> dict:
        return sample.get("phases") or {}

    def history_of(sample: dict) -> dict:
        return sample.get("history_after") or {}

    phases = {}
    for name in PHASES:
        phases[name] = {
            "seconds": summarise([(phases_of(sample).get(name) or {}).get("seconds")
                                  for sample in samples]),
            "figure_draw_calls": summarise([(phases_of(sample).get(name) or {}).get("figure_draw_calls", 0)
                                            for sample in samples]),
            "build_candidate_calls": summarise([(phases_of(sample).get(name) or {}).get("build_candidate_calls", 0)
                                                for sample in samples]),
            "qa_calls": summarise([(phases_of(sample).get(name) or {}).get("qa_calls", 0)
                                   for sample in samples]),
            "qa_seconds": summarise([(phases_of(sample).get(name) or {}).get("qa_seconds", 0.0)
                                     for sample in samples])}
    totals = {key: summarise([(sample.get("totals") or {}).get(key) for sample in samples])
              for key in ("seconds", "figure_draw_calls", "build_candidate_calls", "qa_calls",
                          "qa_seconds", "history_read_seconds")}
    history = {}
    for name in PHASES:
        entries = [history_of(sample).get(name) or {} for sample in samples]
        history[name] = {"checkpoint_count": summarise([entry.get("checkpoint_count") for entry in entries]),
                         "bytes": summarise([entry.get("bytes") for entry in entries]),
                         "files": summarise([entry.get("files") for entry in entries])}
    qa_by_function: dict[str, list] = {}
    for sample in samples:
        for name, entry in (phases_of(sample).get("evaluate") or {}).get("qa_by_function", {}).items():
            qa_by_function.setdefault(name, []).append(entry.get("calls", 0))
    evaluations = [(sample.get("evaluate") or {}) for sample in samples]
    deltas = [evaluation.get("measured_delta_mm") for evaluation in evaluations]
    errors = [evaluation.get("error_mm") if evaluation.get("error_mm") is not None
              else float("inf") for evaluation in evaluations]
    return {"phases": phases, "sample_totals": totals, "history": history,
            "evaluate_guardrails": {
                "statuses": [evaluation.get("status") for evaluation in evaluations],
                "verification_levels": [evaluation.get("verification_level") for evaluation in evaluations],
                "measured_delta_mm_upper": [None if delta is None else delta[1] for delta in deltas],
                "error_mm": errors,
                "max_abs_error_mm": max(errors) if errors else None,
                "usable_samples": sum(1 for sample in samples if sample.get("usable"))},
            "qa_calls_by_function": {name: summarise(counts) for name, counts in
                                     qa_by_function.items()}}


def environment_block(archive: Path, env_values: dict) -> dict:
    import matplotlib
    import numpy

    version = "unknown"
    pyproject = ROOT / "pyproject.toml"
    if pyproject.is_file():
        for line in pyproject.read_text(encoding="utf8").splitlines():
            if line.startswith("version"):
                version = line.split("=", 1)[1].strip().strip('"')
                break

    return {"timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "python": sys.version.split()[0], "executable": sys.executable,
            "platform": platform.platform(), "machine": platform.machine(),
            "processor": platform.processor(), "cwd": str(Path.cwd()),
            "figpact_version": version, "matplotlib": matplotlib.__version__,
            "numpy": numpy.__version__, "archive_root": str(archive),
            "env": env_values}


def scenario_block() -> dict:
    script, config = ROOT / SCENARIO["script"], ROOT / SCENARIO["config"]
    return {**SCENARIO,

            "script_path": str(script), "config_path": str(config),
            "script_bytes": script.stat().st_size, "config_bytes": config.stat().st_size}


def print_report(payload: dict) -> None:
    print("=" * 78)
    print("G6 引擎级分母（engine-level denominators）—— 不是三臂 Agent 盲测")
    print("不能据此宣称端到端提速；热几何阶段 ≠ 完整 Agent 任务。")
    print("=" * 78)
    print(f"场景 : {payload['scenario']['script_path']}")
    print(f"       目标 {payload['scenario']['target_gid']} 上移 {payload['scenario']['delta_mm'][1]} mm"
          f" @ {payload['scenario']['dpi']} DPI, scope={payload['scenario']['scope']}")
    print(f"n    : {payload['n']}   样本可用: {payload['aggregate']['evaluate_guardrails']['usable_samples']}")
    print("-" * 78)
    header = f"{'阶段':<10}{'n':>3}{'mean/s':>10}{'min/s':>10}{'max/s':>10}{'draw':>8}{'build':>8}{'qa':>6}"
    print(header)
    for name in PHASES:
        entry = payload["aggregate"]["phases"][name]
        print(f"{name:<10}{entry['seconds']['n']:>3}{entry['seconds']['mean']:>10.3f}"
              f"{entry['seconds']['min']:>10.3f}{entry['seconds']['max']:>10.3f}"
              f"{entry['figure_draw_calls']['mean']:>8.1f}"
              f"{entry['build_candidate_calls']['mean']:>8.1f}"
              f"{entry['qa_calls']['mean']:>6.1f}")
    print("-" * 78)
    guard = payload["aggregate"]["evaluate_guardrails"]
    print(f"护栏 : status={guard['statuses']}   最大误差={guard['max_abs_error_mm']!r} mm"
          f"   实测位移={guard['measured_delta_mm_upper']}")
    for role in ("cold_start", "session_reopen"):
        entry = payload.get(role) or {}
        seconds = ((entry.get("phases") or {}).get("construct") or {}).get("seconds")
        print(f"{role:<16}: construct={seconds!r} s   usable={entry.get('usable')}"
              f"   process_wall={entry.get('process_wall_seconds')!r} s")
    print("-" * 78)
    print(f"JSON : {payload['output']}")


def self_check() -> int:
    """秒级自检：只验统计/计数差值/字节归类的算术，不建图、不读产品数据。"""
    assert summarise([1.0, 3.0]) == {"n": 2, "mean": 2.0, "min": 1.0, "max": 3.0}
    assert summarise([]) == {"n": 0, "mean": None, "min": None, "max": None}
    before = {"figure_draw_calls": 2, "build_candidate_calls": 1, "qa_calls": 1, "qa_seconds": 0.5,
              "qa_by_function": {"blocking_problems": {"calls": 1, "seconds": 0.5}}}
    after = {"figure_draw_calls": 5, "build_candidate_calls": 4, "qa_calls": 3, "qa_seconds": 1.2,
             "qa_by_function": {"blocking_problems": {"calls": 2, "seconds": 0.9},
                                "check_text_overlap": {"calls": 3, "seconds": 0.4}}}
    delta = Probe.delta(before, after)
    assert (delta["figure_draw_calls"], delta["build_candidate_calls"]) == (3, 3)
    assert (delta["qa_calls"], round(delta["qa_seconds"], 6)) == (2, 0.7)
    assert delta["qa_by_function"]["check_text_overlap"]["calls"] == 3
    record = {"phases": {name: {"seconds": 1.0, "figure_draw_calls": 2, "build_candidate_calls": 1,
                                "qa_calls": 1, "qa_seconds": 0.1} for name in PHASES},
              "history_after": {"construct": {"read_seconds": 0.01}, "evaluate": {"read_seconds": 0.02}}}
    totals = _totals(record)
    assert (totals["seconds"], totals["figure_draw_calls"], totals["build_candidate_calls"]) == (4.0, 8, 4)
    assert round(totals["history_read_seconds"], 6) == 0.03
    print("self-check OK（统计/计数差值/history 读取累加的算术）")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--n", type=int, default=DEFAULT_N, help="配对采样次数（默认 5）")
    parser.add_argument("--archive-root", default=str(DEFAULT_ARCHIVE))
    parser.add_argument("--out", default=None, help=f"JSON 输出（默认 <archive>/{DEFAULT_OUT}）")
    parser.add_argument("--timeout", type=float, default=3600.0, help="单个子进程超时（秒）")
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument("--worker-sample", action="store_true", help="内部：单个样本子进程")
    parser.add_argument("--worker-cold-start", action="store_true", help="内部：冷构造子进程")
    parser.add_argument("--worker-reopen", action="store_true", help="内部：会话重开子进程")
    parser.add_argument("--index", type=int, default=None)
    parser.add_argument("--state-home", default=None)
    parser.add_argument("--worker-out", default=None)
    args = parser.parse_args(argv)

    if args.self_check:
        return self_check()
    archive = Path(args.archive_root)
    if args.worker_sample or args.worker_cold_start or args.worker_reopen:
        mode = ("sample" if args.worker_sample else
                "cold-start" if args.worker_cold_start else "reopen")
        state_home = Path(args.state_home) if args.state_home else archive / "g6-state"
        record = (worker_sample(args.index or 0, state_home, archive) if mode == "sample"
                  else worker_construct_only("cold_start" if mode == "cold-start" else "session_reopen",
                                             state_home, archive))
        Path(args.worker_out).write_text(json.dumps(record, ensure_ascii=False, indent=2,
                                                    default=str), encoding="utf8")
        return 0 if record.get("usable") else 1

    out_path = Path(args.out) if args.out else archive / DEFAULT_OUT
    out_path.parent.mkdir(parents=True, exist_ok=True)
    state_root = archive / "g6-state"
    env_values = apply_environment(archive, state_root)  # 父进程也先落环境，子进程继承
    print(f"[g6] 归档 {archive}；样本数 n={args.n}；输出 {out_path}")
    print("[g6] 引擎级分母，不是三臂 Agent 盲测；不得宣称端到端提速。")

    cold_record = run_child("cold-start", archive, fresh_directory(state_root / "cold-start", archive),
                            archive / "g6-tmp/cold-start.json", None, args.timeout)
    samples = []
    states = []
    for index in range(1, args.n + 1):
        state_home = fresh_directory(state_root / f"sample-{index:02d}", archive)
        record = run_child("sample", archive, state_home,
                           archive / f"g6-tmp/sample-{index:02d}.json", index, args.timeout)
        samples.append(record)
        states.append(state_home)
        phases = record.get("phases") or {}
        print(f"[g6] sample {index}: construct={((phases.get('construct') or {}).get('seconds', 0)):.3f}s "
              f"evaluate={((phases.get('evaluate') or {}).get('seconds', 0)):.3f}s "
              f"status={(record.get('evaluate') or {}).get('status')} usable={record.get('usable')}")
    reopen_record = run_child("reopen", archive, states[0],
                              archive / "g6-tmp/reopen.json", None, args.timeout)

    payload = {"schema": "figpact.g6.engine-denominators/1",
               "n": args.n, "output": str(out_path), "scenario": scenario_block(),
               "environment": environment_block(archive, env_values), "not_a_claim": NOT_A_CLAIM,
               "counters": {
                   "figure_draw_calls": "包装 matplotlib.figure.Figure.draw 的真实调用次数"
                                        "（含 QA 内部 fig.canvas.draw() 触发的那几次）",
                   "build_candidate_calls": "包装 figpact.session.FigureSession.build_candidate"
                                            " 的真实调用次数（基线构建走 _call_builder，不计入）",
                   "qa_calls/qa_seconds": "包装 figpact.qa 的全部公开函数；耗时只累加最外层调用"
                                          "（父子不重复计）",
                   "qa_by_function": "每个被包装函数的逐项调用次数（父子会重叠，是『谁被调了』"
                                     "的账本）",
                   "history": "session.history() 公开读 + state 目录 stat；非估算",
                   "process_wall_seconds": "子进程整墙钟（含解释器启动），单列，不并入阶段分母"},
               "samples": samples, "aggregate": aggregate(samples),
               "cold_start": cold_record, "session_reopen": reopen_record,
               "disclaimer": ("引擎级分母；不是三臂 Agent 盲测，不能宣称端到端提速；"
                              "热几何阶段 ≠ 完整 Agent 任务。样本为每样本一个全新进程 + "
                              "全新 state 目录，脚本未修改任何产品代码。")}
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str),
                        encoding="utf8")
    print_report(payload)
    usable = payload["aggregate"]["evaluate_guardrails"]["usable_samples"]
    return 0 if usable == args.n else 1


if __name__ == "__main__":
    raise SystemExit(main())
