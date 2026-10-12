"""python_native 端到端流程（G4）：计划 → 授权落地 → 另起进程实测 → 记录/恢复。

只测消费者可见的事实：未授权只给 ``PLANNED``，用户源码一个字节都不变（journal/blob
落在 ``state_home`` 里，不碰 history）；授权后磁盘字节**等于** after blob、目标 gid 的
独立重建实测位移在 0.01 mm 内、其余测量键一个毫米都不动；history 里有对应的
``source_change`` 检查点且 ``file_changes`` 的 before/after SHA 与磁盘一致；
``restore_layout_from_history``（授权）把源码恢复成历史 before 内容、产生**新的前向
journal**，旧检查点与旧 journal 未被改写；歧义脚本（同一 key 出现两次）被拒绝且零写入。
全部使用真实临时脚本、真实 state_home 与真实重建，不 mock 文件系统。

写入之后的负例单独一组：写盘**已成事实**时状态必须照实说，绝不许让调用方以为"修改
失败＝磁盘没变"。三条路径各按真实构造触发——①重建探针跑不完（脚本对超界位移抛错）；
②位移没走到位（脚本把 0.3 mm 钳成 0.05 mm）；③写盘完成但 History 提交前异常退出
（在 ``append_source_change`` 之前注入异常）。每条都断言 journal 的实际状态、磁盘真实
字节，以及后续能判定并恢复到 before 内容（新前向 journal）。
"""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import matplotlib

matplotlib.use("Agg", force=True)

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import matplotlib.pyplot as plt  # noqa: E402

from figpact.history import HistoryStore  # noqa: E402
from figpact.python_native import (  # noqa: E402
    COMMITTED_AND_VERIFIED,
    COMMITTED_BUT_UNVERIFIED,
    NOT_WRITTEN,
    edit_layout_and_verify,
    restore_layout_from_history,
)
from figpact.session import FigureSession, drawn_shapes  # noqa: E402
from figpact.source_writes import recover_pending, restore_project  # noqa: E402

SCOPE = "main"
TARGET = "probe.main.label.A"
OTHER = "probe.main.label.B"
CURVE = "probe.main.curve"
#: 请求写入源码的 A 位移（毫米），与 `tests/test_python_native_example.py` 同一容差约定。
SHIFT_MM = [0.0, 0.2]
TOL_MM = 0.01

SCRIPT = '''"""端到端夹具：一条曲线 + 两个标签，排版位移写在源码里（没有 YAML）。"""
import math

import matplotlib.pyplot as plt

from figpact import GidRegistry, apply_display_shift

SCOPES = ("main",)

LAYOUT_MM = {
    "probe.main.label.A": [0.0, 0.0],
    "probe.main.label.B": [0.0, 0.0],
}

LABELS = (
    ("probe.main.label.A", 2.0, 0.62, "A"),
    ("probe.main.label.B", 7.5, 0.62, "B"),
)


def load_science():
    """受保护的科研载荷：确定性解析曲线（不读文件、不引入随机/时间）。"""
    x = [index / 10.0 for index in range(101)]
    y = [math.exp(-((value - 5.0) ** 2) / 2.0) for value in x]
    return {"x": x, "y": y}


def build_scene(science, config, scope):
    fig = plt.figure(figsize=(60.0 / 25.4, 45.0 / 25.4), dpi=300)
    ax = fig.add_axes((0.18, 0.22, 0.76, 0.68))
    registry = GidRegistry(scope=scope)
    line, = ax.plot(science["x"], science["y"], color="#333333", linewidth=1.0)
    registry.register(line, "probe.main.curve", artist_type="Line2D",
                      science_policy="LOCKED_SCIENCE")
    for gid, point_x, point_y, text in LABELS:
        dx, dy = LAYOUT_MM.get(gid, (0.0, 0.0))
        label = ax.text(point_x, point_y, text, ha="center", va="bottom", fontsize=7.0)
        apply_display_shift(label, dx_mm=float(dx), dy_mm=float(dy))
        registry.register(label, gid, artist_type="Text", science_policy="LAYOUT")
    ax.set_xlabel("x (a.u.)")
    ax.set_ylabel("y (a.u.)")
    return fig, registry
'''

#: 同一 key 在 LAYOUT_MM 里出现两次：排版还是科学数据判不出来，只能拒绝。
AMBIGUOUS_SCRIPT = '''LAYOUT_MM = {
    "probe.main.label.A": [0.0, 0.0],
    "probe.main.label.A": [0.0, 0.15],
}
'''

#: ② 的请求：源码字面量写成 0.3 mm，脚本自己把它钳到 0.05 mm——"改了点、没改到位"。
UNREACHED_MM = [0.0, 0.3]
CLAMP_MM = 0.05


def _derive(source: str, needle: str, replacement: str) -> str:
    """夹具变体：`needle` 必须真的在场——`.replace` 拼错会静默无操作，把负例变成假阳性。"""
    assert source.count(needle) == 1, needle
    return source.replace(needle, replacement)


#: ① 的探针陷阱：源码本身**合法**（写入随时成功），但重建时标签位移一超过阈值就抛错。
#: 于是"写盘已成事实、重建却测不出结果"是真实现象，不必伪造探针。
PROBE_TRAP_SCRIPT = _derive(
    _derive(SCRIPT, 'SCOPES = ("main",)',
            'SCOPES = ("main",)\n\n'
            '#: 探针陷阱阈值（夹具）：位移超过它就抛错，重建测不出结果。\n'
            'PROBE_TRAP_MM = 0.25'),
    '        apply_display_shift(label, dx_mm=float(dx), dy_mm=float(dy))\n',
    '        if float(dy) > PROBE_TRAP_MM:\n'
    '            raise RuntimeError("探针陷阱：位移越界")\n'
    '        apply_display_shift(label, dx_mm=float(dx), dy_mm=float(dy))\n')

#: ② 的钳位负例：源码字面量改到位（0.3 mm），脚本自己截到 0.05 mm。
CLAMPED_SCRIPT = _derive(
    _derive(SCRIPT, 'SCOPES = ("main",)',
            'SCOPES = ("main",)\n\n'
            '#: 位移上限（夹具）：超过就钳位，图上只走 CLAMP_MM。\n'
            'CLAMP_MM = 0.05'),
    '        apply_display_shift(label, dx_mm=float(dx), dy_mm=float(dy))\n',
    '        apply_display_shift(label, dx_mm=float(dx),\n'
    '                            dy_mm=min(float(dy), CLAMP_MM))\n')


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _tree(directory: Path) -> list[str]:
    """目录内容清单（`__pycache__` 是装载器的字节码缓存，不是脚本的副作用）。"""
    return sorted(str(path.relative_to(directory)) for path in directory.rglob("*")
                  if "__pycache__" not in path.parts)


def measured_geometry(script: Path, config: Path, scope: str = SCOPE) -> dict:
    """**本进程**里用现有会话机制真实重建一次 → `{测量键: [x0, y0, x1, y1]} (mm)`。

    与 `tests/test_python_native_example.py` 同一套约定：注册过的图元按 `gid:<gid>`
    记名，未注册的按「轴序号 + 类型 + 序号」记名——于是"只有 A 动了"这条断言覆盖图上
    全部可见几何，而不是只看两个已知 gid。这条路径与流程内的子进程探针**不同源**，
    用它来独立复核流程自报的实测值。
    """
    with FigureSession(script, config, scope) as session:
        fig, registry = session.build_candidate(session.candidate_config)
        try:
            shapes = drawn_shapes(fig, registry, include_frames=True)
        finally:
            plt.close(fig)
    return {key: list(record["bbox_mm"]) for key, record in shapes.items()
            if record.get("bbox_mm") is not None}


def read_journal(state_home: Path, journal_id: str) -> dict:
    path = state_home / "source-journals" / f"{journal_id}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def blob_bytes(state_home: Path, ref: str) -> bytes:
    return (state_home / ref).read_bytes()


class PythonNativeEditFlowTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="figpact-native-flow-")
        # 解析成规范路径：G3b/history 内部按 resolve() 记账，短名/链接会让比对失败。
        self.root = Path(self._tmp.name).resolve()
        # 脚本目录与状态目录必须是两个位置：历史拒绝把状态目录放在源码目录里面。
        self.work = self.root / "work"
        self.work.mkdir()
        self.state_home = self.root / "state"
        self.script = self.work / "plot.py"
        self.script.write_text(SCRIPT, encoding="utf8")
        # 会话机制按契约要求一个配置**路径**（YAML）；本夹具自身不含 YAML。
        self.config = self.work / "plot.yaml"
        self.config.write_text("{}\n", encoding="utf8")

    def tearDown(self):
        plt.close("all")
        self._tmp.cleanup()

    # ------------------------------------------------------------- 工具

    def _edit(self, authorized: bool, reason: str = "把 A 右移", value=None) -> dict:
        return edit_layout_and_verify(self.script, TARGET, SHIFT_MM if value is None else value,
                                      state_home=self.state_home, config=self.config,
                                      scope=SCOPE, authorized=authorized, reason=reason)

    def _restore(self, commit_id: str, authorized: bool) -> dict:
        return restore_layout_from_history(commit_id, script=self.script, config=self.config,
                                           scope=SCOPE, state_home=self.state_home,
                                           authorized=authorized, reason="恢复 A 的位移")

    # ------------------------------------------------------------- 未授权

    def test_unauthorized_plan_writes_nothing_to_user_source(self):
        before = self.script.read_bytes()
        tree_before = _tree(self.work)

        answer = self._edit(authorized=False)

        self.assertEqual(answer["status"], "PLANNED", answer)
        self.assertFalse(answer["written"])
        self.assertEqual(answer["commit_state"], NOT_WRITTEN, "未授权时磁盘一个字节没变")
        self.assertEqual(self.script.read_bytes(), before, "未授权不许碰用户源码")
        self.assertEqual(_tree(self.work), tree_before, "未授权不许在源码目录里留下任何东西")
        self.assertFalse((self.state_home / "workspaces").exists(), "未授权不许碰 history")

        journal = read_journal(self.state_home, answer["journal_id"])
        self.assertEqual(journal["status"], "PREPARED", "计划只写 PREPARED journal")
        self.assertEqual(journal["files"][0]["before_sha256"], sha256_hex(before))
        self.assertEqual(journal["files"][0]["after_sha256"], answer["after_sha256"])
        self.assertNotEqual(answer["after_sha256"], sha256_hex(before), "计划必须真的改到点东西")

    # ------------------------------------------------------------- 授权

    def test_authorized_edit_writes_after_blob_and_records_history(self):
        original = self.script.read_bytes()
        baseline = measured_geometry(self.script, self.config)

        answer = self._edit(authorized=True)

        self.assertEqual(answer["status"], "OK", answer.get("problems"))
        self.assertEqual(answer["problems"], [])
        self.assertTrue(answer["written"])

        journal = read_journal(self.state_home, answer["journal_id"])
        self.assertEqual(journal["status"], "COMMITTED")
        entry = journal["files"][0]
        self.assertEqual(len(journal["files"]), 1, "只许写这一个文件")
        self.assertEqual(Path(entry["path"]), self.script.resolve())
        self.assertEqual(entry["before_sha256"], sha256_hex(original))
        self.assertEqual(self.script.read_bytes(), blob_bytes(self.state_home, entry["after_blob"]),
                         "磁盘字节必须等于 after blob")
        self.assertEqual(entry["after_sha256"], sha256_hex(self.script.read_bytes()))
        self.assertNotEqual(self.script.read_bytes(), original)

        # 独立重建（本进程、与流程内的子进程探针不同源）：只有 A 按请求位移移动。
        after = measured_geometry(self.script, self.config)
        self.assertEqual(sorted(after), sorted(baseline), "可见几何的键集合必须一致")
        for gid in (CURVE, TARGET, OTHER):
            self.assertIn(f"gid:{gid}", baseline, f"{gid} 必须在基线里被测到")
        moved = [after[f"gid:{TARGET}"][index] - baseline[f"gid:{TARGET}"][index]
                 for index in (0, 1)]
        for index, (want, got) in enumerate(zip(SHIFT_MM, moved)):
            self.assertAlmostEqual(got, want, delta=TOL_MM,
                                   msg=f"A 的 {'xy'[index]} 实测位移 {got} mm，请求 {want} mm")
            self.assertAlmostEqual(answer["measured_mm"][index], want, delta=TOL_MM,
                                   msg="流程自报的实测位移必须落在同一条容差里")
        for key in sorted(baseline):
            if key == f"gid:{TARGET}":
                continue
            for index, (was, now) in enumerate(zip(baseline[key], after[key])):
                self.assertAlmostEqual(now - was, 0.0, delta=TOL_MM,
                                       msg=f"{key} 跟着 A 动了（{'xyxy'[index]}：{was} → {now}）")

        # history：一条 source_change，file_changes 的 before/after SHA 与磁盘一致。
        with HistoryStore(self.script, self.config, SCOPE, state_home=self.state_home) as store:
            records = store.source_changes()
            self.assertEqual([record["id"] for record in records], [answer["checkpoint_id"]])
            changes = store.file_changes(answer["checkpoint_id"])
        self.assertEqual(len(changes), 1)
        change = changes[0]
        self.assertEqual(Path(change["path"]), self.script.resolve())
        self.assertEqual(change["before_sha256"], sha256_hex(original))
        self.assertEqual(change["after_sha256"], sha256_hex(self.script.read_bytes()))
        self.assertEqual(blob_bytes(self.state_home, change["before_blob"]), original)
        self.assertEqual(blob_bytes(self.state_home, change["after_blob"]),
                         self.script.read_bytes())

    # ------------------------------------------------------------- 恢复

    def test_restore_returns_before_content_as_a_new_forward_journal(self):
        original = self.script.read_bytes()
        edit = self._edit(authorized=True)
        self.assertEqual(edit["status"], "OK", edit.get("problems"))
        commit_id = edit["checkpoint_id"]
        shifted = self.script.read_bytes()
        self.assertNotEqual(shifted, original)
        journal_path = self.state_home / "source-journals" / f"{edit['journal_id']}.json"
        old_journal = journal_path.read_bytes()
        with HistoryStore(self.script, self.config, SCOPE, state_home=self.state_home) as store:
            old_payload = store.get(commit_id)["payload"]
            old_sha = store.get(commit_id)["payload_sha256"]

        denied = self._restore(commit_id, authorized=False)
        self.assertEqual(denied["status"], "UNAUTHORIZED")
        self.assertEqual(self.script.read_bytes(), shifted, "未授权恢复不许碰源码")

        answer = self._restore(commit_id, authorized=True)

        self.assertEqual(answer["status"], "COMMITTED", answer)
        self.assertEqual(self.script.read_bytes(), original, "恢复后必须等于历史 before 内容")
        self.assertNotEqual(answer["journal_id"], edit["journal_id"], "恢复必须是新 journal")

        restore_journal = read_journal(self.state_home, answer["journal_id"])
        self.assertEqual(restore_journal["status"], "COMMITTED")
        restored_entry = restore_journal["files"][0]
        self.assertEqual(restored_entry["before_sha256"], sha256_hex(shifted))
        self.assertEqual(restored_entry["after_sha256"], sha256_hex(original))
        self.assertEqual(blob_bytes(self.state_home, restored_entry["after_blob"]), original)

        # 旧 journal 与旧检查点一个字节都没改。
        self.assertEqual(journal_path.read_bytes(), old_journal)
        with HistoryStore(self.script, self.config, SCOPE, state_home=self.state_home) as store:
            self.assertEqual(store.get(commit_id)["payload"], old_payload)
            self.assertEqual(store.get(commit_id)["payload_sha256"], old_sha)
            records = store.source_changes()
            self.assertEqual([record["id"] for record in records],
                             [commit_id, answer["checkpoint_id"]])
            restored_changes = store.file_changes(answer["checkpoint_id"])
        self.assertEqual(restored_changes[0]["before_sha256"], sha256_hex(shifted))
        self.assertEqual(restored_changes[0]["after_sha256"], sha256_hex(original))

    # ------------------------------------------------------------- 歧义

    def test_ambiguous_binding_is_rejected_without_writing_even_when_authorized(self):
        self.script.write_text(AMBIGUOUS_SCRIPT, encoding="utf8")
        before = self.script.read_bytes()
        tree_before = _tree(self.work)

        answer = self._edit(authorized=True)

        self.assertEqual(answer["status"], "AMBIGUOUS", answer)
        self.assertFalse(answer["written"])
        self.assertEqual(answer["commit_state"], NOT_WRITTEN, "拒绝时磁盘一个字节没变")
        self.assertEqual(answer["plan"]["confidence"], "low")
        self.assertTrue(answer["plan"]["candidates"], "拒绝必须给出候选")
        self.assertEqual(self.script.read_bytes(), before, "拒绝时必须零写入")
        self.assertEqual(_tree(self.work), tree_before)
        self.assertFalse((self.state_home / "source-journals").exists(), "拒绝不许写 journal")
        self.assertFalse((self.state_home / "workspaces").exists(), "拒绝不许碰 history")

    # ------------------------------------------- 写入之后的负例：写盘事实 ≠ 修改失败

    def test_probe_failure_after_write_is_committed_but_unverified(self):
        """① 写入已成事实、重建探针却跑不完：状态必须承认写盘，且留下恢复到 before 的依据。"""
        original = self.script.read_bytes()
        self.script.write_text(PROBE_TRAP_SCRIPT, encoding="utf8")
        trapped = self.script.read_bytes()
        self.assertNotEqual(trapped, original, "夹具变体必须真的改到脚本")

        answer = self._edit(authorized=True, value=UNREACHED_MM, reason="探针异常负例")

        self.assertEqual(answer["status"], COMMITTED_BUT_UNVERIFIED, answer.get("problems"))
        self.assertEqual(answer["commit_state"], COMMITTED_BUT_UNVERIFIED)
        self.assertTrue(answer["written"], "写盘已成事实，written 不得为 False")
        self.assertIsNone(answer["measured_mm"], "探针没跑完就没有实测位移，不许编一个")
        self.assertTrue(any("探针陷阱" in problem for problem in answer["problems"]),
                        f"问题清单必须如实说重建子进程为什么失败：{answer['problems']}")

        journal = read_journal(self.state_home, answer["journal_id"])
        self.assertEqual(journal["status"], "COMMITTED", "journal 状态即磁盘事实")
        entry = journal["files"][0]
        self.assertNotEqual(self.script.read_bytes(), trapped, "源码必须真的被改写")
        self.assertEqual(self.script.read_bytes(), blob_bytes(self.state_home, entry["after_blob"]),
                         "磁盘真实字节必须等于 after blob")
        self.assertEqual(answer["disk_sha256"], sha256_hex(self.script.read_bytes()))
        self.assertEqual(blob_bytes(self.state_home, entry["before_blob"]), trapped)

        # 验证没通过也要在 history 里留下这条**事实**，否则"恢复到 before"没有依据。
        with HistoryStore(self.script, self.config, SCOPE, state_home=self.state_home) as store:
            self.assertEqual([record["id"] for record in store.source_changes()],
                             [answer["checkpoint_id"]])
            payload = store.get(answer["checkpoint_id"])["payload"]
            self.assertEqual(payload["commit_state"], COMMITTED_BUT_UNVERIFIED)
            self.assertEqual(payload["problems"], answer["problems"])

        restored = self._restore(answer["checkpoint_id"], authorized=True)

        self.assertEqual(restored["status"], "COMMITTED", restored)
        self.assertEqual(restored["commit_state"], COMMITTED_AND_VERIFIED)
        self.assertEqual(self.script.read_bytes(), trapped, "恢复后必须逐字节等于 before 内容")
        self.assertNotEqual(restored["journal_id"], answer["journal_id"], "恢复必须是新 journal")

    def test_unreached_shift_after_write_is_committed_but_unverified(self):
        """② 源码字面量改到位、图上没走到位（0.3 mm 被脚本钳成 0.05 mm）：不许报 OK。"""
        self.script.write_text(CLAMPED_SCRIPT, encoding="utf8")
        original = self.script.read_bytes()
        baseline = measured_geometry(self.script, self.config)

        answer = self._edit(authorized=True, value=UNREACHED_MM, reason="位移不符负例")

        self.assertEqual(answer["status"], COMMITTED_BUT_UNVERIFIED, answer.get("problems"))
        self.assertEqual(answer["commit_state"], COMMITTED_BUT_UNVERIFIED)
        self.assertTrue(answer["written"], "写盘已成事实，written 不得为 False")
        error_mm = [answer["measured_mm"][index] - UNREACHED_MM[index] for index in (0, 1)]
        self.assertGreater(abs(error_mm[1]), TOL_MM, "自报的实测位移必须与请求差出容差")
        mismatch = [problem for problem in answer["problems"] if f"gid:{TARGET}" in problem]
        self.assertTrue(mismatch, f"问题清单必须点名目标 gid：{answer['problems']}")
        self.assertIn(f"请求 {UNREACHED_MM[1]} mm", mismatch[0])

        # 独立重建（本进程，与子进程探针不同源）：改是真的改了，只是没走到请求的位置。
        after = measured_geometry(self.script, self.config)
        self.assertEqual(sorted(after), sorted(baseline), "可见几何的键集合必须一致")
        observed = [after[f"gid:{TARGET}"][index] - baseline[f"gid:{TARGET}"][index]
                    for index in (0, 1)]
        self.assertAlmostEqual(observed[0], 0.0, delta=TOL_MM)
        self.assertGreater(abs(observed[1] - UNREACHED_MM[1]), TOL_MM,
                           f"A 的 y 只走了 {observed[1]} mm，请求 {UNREACHED_MM[1]} mm")
        self.assertLess(observed[1], UNREACHED_MM[1], "错的是「没走到位」，不是走过头")
        self.assertGreaterEqual(observed[1], -TOL_MM, "钳位只会少走，不会往回走")
        self.assertAlmostEqual(observed[1], answer["measured_mm"][1], delta=TOL_MM,
                               msg="两条独立测量路径必须给出同一个位移")

        journal = read_journal(self.state_home, answer["journal_id"])
        self.assertEqual(journal["status"], "COMMITTED")
        entry = journal["files"][0]
        self.assertEqual(self.script.read_bytes(), blob_bytes(self.state_home, entry["after_blob"]))
        self.assertEqual(answer["disk_sha256"], entry["after_sha256"])
        self.assertEqual(blob_bytes(self.state_home, entry["before_blob"]), original)

        restored = self._restore(answer["checkpoint_id"], authorized=True)

        self.assertEqual(restored["status"], "COMMITTED", restored)
        self.assertEqual(self.script.read_bytes(), original, "恢复后必须逐字节等于 before 内容")
        self.assertNotEqual(restored["journal_id"], answer["journal_id"])
        self.assertEqual(recover_pending(self.state_home), [],
                         "两条 journal 都已提交：没有半截写入，恢复走的是前向 journal")

    def test_crash_before_history_commit_leaves_the_journal_as_the_only_evidence(self):
        """③ 写盘完成、History 提交前异常退出：崩溃那条 journal 自己就是恢复到 before 的依据。

        注入点选在 ``store.head()``：源码写入已经落地、``append_source_change`` 还没跑，
        等于"写入完成、历史提交前异常退出"。事后没有检查点，能断言的只有 journal 与磁盘。
        """
        original = self.script.read_bytes()
        boom = RuntimeError("模拟 History 提交前异常退出")
        with mock.patch.object(HistoryStore, "head", side_effect=boom):
            with self.assertRaises(RuntimeError) as raised:
                self._edit(authorized=True, reason="崩溃负例")
        self.assertIs(raised.exception, boom)

        with HistoryStore(self.script, self.config, SCOPE, state_home=self.state_home) as store:
            self.assertEqual(store.source_changes(), [], "崩在提交之前：没有检查点")

        journals = sorted((self.state_home / "source-journals").glob("*.json"))
        self.assertEqual(len(journals), 1, f"只该有这条写入的 journal：{journals}")
        crash_journal = journals[0].read_bytes()
        journal = json.loads(crash_journal.decode("utf-8"))
        self.assertEqual(journal["status"], "COMMITTED", "写盘是事实，journal 如实记着")
        entry = journal["files"][0]
        self.assertNotEqual(self.script.read_bytes(), original, "源码确实已被改写")
        self.assertEqual(self.script.read_bytes(), blob_bytes(self.state_home, entry["after_blob"]),
                         "磁盘真实字节必须等于 after blob")
        self.assertEqual(blob_bytes(self.state_home, entry["before_blob"]), original)

        # recover_pending 只说"没有半截写入"（这条 journal 已 COMMITTED），崩溃前的内容在
        # journal 自己身上，所以恢复由它的 before blob 生成**新的前向 journal**。
        self.assertEqual(recover_pending(self.state_home), [])

        restored = restore_project(
            [{"path": entry["path"], "after_blob": entry["before_blob"],
              "after_sha256": entry["before_sha256"]}],
            state_home=self.state_home, reason="崩溃后按 journal 的 before blob 前向恢复")

        self.assertEqual(restored["status"], "COMMITTED", restored)
        self.assertNotEqual(restored["id"], journal["id"], "恢复必须是新 journal")
        self.assertEqual(self.script.read_bytes(), original, "恢复后必须逐字节等于 before 内容")
        self.assertEqual(journals[0].read_bytes(), crash_journal, "崩溃那条 journal 不许被改写")


if __name__ == "__main__":
    unittest.main()
