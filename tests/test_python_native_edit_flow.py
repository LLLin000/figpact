"""python_native 端到端流程（G4）：计划 → 授权落地 → 另起进程实测 → 记录/恢复。

只测消费者可见的事实：未授权只给 ``PLANNED``，用户源码一个字节都不变（journal/blob
落在 ``state_home`` 里，不碰 history）；授权后磁盘字节**等于** after blob、目标 gid 的
独立重建实测位移在 0.01 mm 内、其余测量键一个毫米都不动；history 里有对应的
``source_change`` 检查点且 ``file_changes`` 的 before/after SHA 与磁盘一致；
``restore_layout_from_history``（授权）把源码恢复成历史 before 内容、产生**新的前向
journal**，旧检查点与旧 journal 未被改写；歧义脚本（同一 key 出现两次）被拒绝且零写入。
全部使用真实临时脚本、真实 state_home 与真实重建，不 mock 文件系统。
"""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

import matplotlib

matplotlib.use("Agg", force=True)

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import matplotlib.pyplot as plt  # noqa: E402

from figpact.history import HistoryStore  # noqa: E402
from figpact.python_native import (  # noqa: E402
    edit_layout_and_verify,
    restore_layout_from_history,
)
from figpact.session import FigureSession, drawn_shapes  # noqa: E402

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
        self.assertEqual(answer["plan"]["confidence"], "low")
        self.assertTrue(answer["plan"]["candidates"], "拒绝必须给出候选")
        self.assertEqual(self.script.read_bytes(), before, "拒绝时必须零写入")
        self.assertEqual(_tree(self.work), tree_before)
        self.assertFalse((self.state_home / "source-journals").exists(), "拒绝不许写 journal")
        self.assertFalse((self.state_home / "workspaces").exists(), "拒绝不许碰 history")


if __name__ == "__main__":
    unittest.main()
