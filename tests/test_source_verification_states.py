"""P0a：`source_commit_state` 与 `figure_verification_state` 是**两个独立状态**。

被测的是 Hub 的写盘回执（真实回环 HTTP + 真实临时源码 + 真实 state_home + 真实重建）：

  * ``source_commit_state``（``NOT_WRITTEN`` / ``COMMITTED`` / ``RECOVERY_REQUIRED``）——
    源码是否安全提交；
  * ``figure_verification_state``（``NOT_RUN`` / ``PASS`` / ``FAIL`` / ``ERROR``）——写盘
    **之后**另起进程重建得到的图形验证结论，证据（脚本 sha256 / gid / scope / 实测残差 /
    科学指纹）绑在**这次提交的版本**上。

要守住的四条：

  1. 未写入 → ``NOT_WRITTEN`` + ``NOT_RUN``（写盘路径被拒时也一样，两个字段都不许含糊）；
  2. 写入且重建通过 → ``COMMITTED`` + ``PASS``，证据与磁盘逐字节对得上；
  3. 写入但重建失败/没跑完 → 仍是 ``COMMITTED`` + ``FAIL``/``ERROR``——**不得**说成未写入；
  4. 事后改盘 → 旧的 ``PASS`` 不再是当前文件的验证结果（证据绑定的 sha256 说话）。

``commit_state`` 作为**兼容字段**继续存在且语义不变（只表达写入语义）；本文件同时守这条
回归：它在 ``FAIL``/``ERROR`` 时仍是 ``COMMITTED_AND_VERIFIED``——正因为那个名字会被误读成
"科学也验过了"，才需要这两个新字段。

怎么跑::

    python -m pytest tests/test_source_verification_states.py -q
"""
from __future__ import annotations

import hashlib
import http.client
import json
import re
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import matplotlib  # noqa: E402

matplotlib.use("Agg", force=True)

import matplotlib.pyplot as plt  # noqa: E402

from figpact import python_native  # noqa: E402
from figpact.history import HistoryStore  # noqa: E402
from figpact.inspector_server import InspectorServer  # noqa: E402
from figpact.session import FigureSession, drawn_shapes  # noqa: E402

SCOPE = "main"
TARGET = "probe.main.label.A"
CURVE = "probe.main.curve"
TARGET_KEY = f"gid:{TARGET}"
#: 一次真的走得到位的位移（毫米）；重建实测与它只差远小于 ``VERIFY_TOL_MM`` 的量。
SHIFT_MM = [0.0, 0.2]
#: ② 的钳位负例：源码字面量改到位（0.3 mm），脚本自己截到 0.05 mm。
UNREACHED_MM = [0.0, 0.3]
CLAMP_MM = 0.05
#: ① 的探针陷阱：位移一过阈值，重建就抛错——"写盘已成事实、探针跑不完"是真实现象。
TRAP_MM = 0.25
TRAP_SHIFT_MM = [0.0, 1.0]
CLIENT_A = "p0a-client"
#: 线路上的契约名字（测试守协议本身，不引用实现常量）。
UI_HEADER = "X-Figpact-Ui"
CLIENT_HEADER = "X-Figpact-Client"
NO_BODY = object()

SCRIPT = '''"""P0a 夹具：一条曲线 + 两个标签，排版位移写在源码里（没有 YAML）。"""
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


def _derive(source: str, needle: str, replacement: str) -> str:
    """夹具变体：`needle` 必须真的在场——`.replace` 拼错会静默无操作，把负例变成假阳性。"""
    assert source.count(needle) == 1, needle
    return source.replace(needle, replacement)


#: ① 写盘成功、重建跑不完：位移一过阈值就抛错（源码本身完全合法，写入不受影响）。
TRAP_SCRIPT = _derive(
    SCRIPT, "SCOPES = (\"main\",)",
    "SCOPES = (\"main\",)\n\n"
    "#: 探针陷阱阈值（夹具）：位移超过它就抛错，重建测不出结果。\n"
    f"PROBE_TRAP_MM = {TRAP_MM}")


def _trap_body(source: str) -> str:
    return _derive(
        source,
        "        apply_display_shift(label, dx_mm=float(dx), dy_mm=float(dy))\n",
        "        if float(dy) > PROBE_TRAP_MM:\n"
        "            raise RuntimeError(\"探针陷阱：位移越界\")\n"
        "        apply_display_shift(label, dx_mm=float(dx), dy_mm=float(dy))\n")


#: ② 写盘成功、位移没走到位：脚本自己把超过上限的位移钳掉。
CLAMPED_SCRIPT = _derive(
    SCRIPT, "SCOPES = (\"main\",)",
    "SCOPES = (\"main\",)\n\n"
    "#: 位移上限（夹具）：超过就钳位，图上只走 CLAMP_MM。\n"
    f"CLAMP_MM = {CLAMP_MM}")


def _clamp_body(source: str) -> str:
    return _derive(
        source,
        "        apply_display_shift(label, dx_mm=float(dx), dy_mm=float(dy))\n",
        "        apply_display_shift(label, dx_mm=float(dx),\n"
        "                            dy_mm=min(float(dy), CLAMP_MM))\n")


def http_json(port, method, path, body=NO_BODY, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    try:
        data, sent = None, dict(headers or {})
        if body is not NO_BODY:
            data = json.dumps(body)
            sent["Content-Type"] = "application/json"
        conn.request(method, path, data, sent)
        response = conn.getresponse()
        return response.status, json.loads(response.read())
    finally:
        conn.close()


def http_text(port, path):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    try:
        conn.request("GET", path, None, {})
        response = conn.getresponse()
        return response.status, response.read().decode("utf-8")
    finally:
        conn.close()


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def measured_geometry(script: Path, config: Path, scope: str = SCOPE) -> dict:
    """**本进程**里用现有会话机制重建一次 → `{测量键: [x0, y0, x1, y1]} (mm)`。

    与流程内的子进程探针**不同源**：流程自报的实测位移由它独立复核。
    """
    with FigureSession(script, config, scope) as session:
        fig, registry = session.build_candidate(session.candidate_config)
        try:
            shapes = drawn_shapes(fig, registry, include_frames=True)
        finally:
            plt.close(fig)
    return {key: list(record["bbox_mm"]) for key, record in shapes.items()
            if record.get("bbox_mm") is not None}


class _FakeSession:
    """计划路由不读会话；这里只满足 InspectorServer 对既有路由的构造需求。"""

    def snapshot(self):
        return {"frame_revision": "scene-1", "session": {"session_id": "s-1"}}

    def evaluate(self, request):
        return {"status": "OK"}

    def decide(self, request):
        return {"status": "OK"}

    def set_quality(self, request):
        return {"status": "OK"}


class _StatesCase(unittest.TestCase):
    """一条用例一个临时工程 + 一个临时 state_home + 一个真实回环服务器。"""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="figpact-p0a-")).resolve()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        # 脚本目录与状态目录是**两个**位置：history 拒绝把状态目录放在源码目录里。
        self.work = self.root / "work"
        self.work.mkdir()
        self.state = self.root / "state"
        self.script = self.work / "plot.py"
        self.config = self.work / "plot.yaml"
        self.config.write_text("{}\n", encoding="utf8")
        self.arm(SCRIPT)
        # 磁盘上此刻的字节（写盘的换行翻译由平台决定，断言只认磁盘事实）。
        self.original_bytes = self.script.read_bytes()
        self.server, self.port, self.token = None, None, None

    def tearDown(self):
        plt.close("all")

    def arm(self, script_text: str):
        """把夹具写进临时工程；每个用例在**铸造计划之前**只 arm 一次。"""
        self.script.write_text(script_text, encoding="utf8")
        return self.script

    def start(self, *, source=True):
        """起一个真实回环服务器；``source=False`` 表示服务端不知道工作区身份（config）。"""
        identity = {"script": str(self.script), "config": str(self.config), "scope": SCOPE} \
            if source else None
        server = InspectorServer(_FakeSession(), ("127.0.0.1", 0), state_home=self.state,
                                 source=identity)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        # addCleanup 是后进先出：shutdown → join → close。
        self.addCleanup(server.server_close)
        self.addCleanup(lambda: thread.join(5))
        self.addCleanup(server.shutdown)
        self.server, self.port = server, server.server_address[1]
        status, text = http_text(self.port, "/frame.js")
        self.assertEqual(status, 200)
        match = re.search(r"window\.FIGPACT_UI_TOKEN=(\"(?:[^\"\\]|\\.)*\");", text)
        self.assertIsNotNone(match, text)
        self.token = json.loads(match.group(1))
        self.assertEqual(self.token, self.server.ui_token)
        return server

    # ------------------------------------------------------------- 路由的薄封装

    def mint_raw(self, *, value=None, gid=TARGET, client=CLIENT_A):
        return http_json(self.port, "POST", "/api/plans", {
            "client_id": client, "kind": "layout_edit", "script": str(self.script),
            "gid": gid, "value": list(SHIFT_MM if value is None else value),
            "reason": "P0a 用例：把标签移到位"})

    def mint(self, **kwargs):
        status, payload = self.mint_raw(**kwargs)
        self.assertEqual((status, payload["status"]), (200, "OK"), payload)
        return payload["plan"]

    def authorize(self, plan_id):
        return http_json(self.port, "POST", f"/api/plans/{plan_id}/authorize", NO_BODY,
                         {UI_HEADER: self.token})

    def apply_plan(self, plan_id, *, client=CLIENT_A, body=NO_BODY):
        headers = {} if client is None else {CLIENT_HEADER: client}
        return http_json(self.port, "POST", f"/api/plans/{plan_id}/apply", body, headers)

    def plans(self):
        status, payload = http_json(self.port, "GET", "/api/plans")
        self.assertEqual((status, payload["status"]), (200, "OK"), payload)
        return payload["plans"]

    def plan(self, plan_id):
        return next(plan for plan in self.plans() if plan["plan_id"] == plan_id)

    def checkpoints(self):
        store = HistoryStore(self.script, self.config, SCOPE, state_home=self.state)
        try:
            return store.source_changes()
        finally:
            store.close()

    def commit_and_verify(self, *, value=None):
        """铸造 → 页面授权 → 客户端 apply；返回 (HTTP 状态, 回执)。"""
        plan = self.mint(value=value)
        self.assertEqual(self.authorize(plan["plan_id"])[0], 200)
        status, payload = self.apply_plan(plan["plan_id"])
        return plan, status, payload


class NotWrittenCases(_StatesCase):
    """未写入：两个状态都必须是"没发生"，一个字节都不许动。"""

    def test_minted_plan_is_not_written_and_not_verified(self):
        self.start()
        plan = self.mint()
        self.assertEqual(plan["source_commit_state"], python_native.SOURCE_NOT_WRITTEN)
        self.assertEqual(plan["figure_verification_state"], python_native.FIGURE_NOT_RUN)
        self.assertIsNone(plan["figure_verification"])

        # 页面读的也是同一个真相：铸造没有写盘，也没有跑过任何验证。
        public = self.plan(plan["plan_id"])
        self.assertEqual(public["state"], "PENDING")
        self.assertEqual(public["source_commit_state"], python_native.SOURCE_NOT_WRITTEN)
        self.assertEqual(public["figure_verification_state"], python_native.FIGURE_NOT_RUN)
        self.assertIs(public["figure_verification_stale"], False)
        self.assertEqual(self.script.read_bytes(), self.original_bytes)

    def test_refused_apply_says_not_written_and_not_run(self):
        self.start()
        plan = self.mint()
        # 没有页面同意就 apply：拒绝，且两个字段都说"什么都没发生"。
        status, payload = self.apply_plan(plan["plan_id"])
        self.assertEqual((status, payload["status"]), (409, "PLAN_NOT_PENDING"), payload)
        self.assertEqual(payload["source_commit_state"], "NOT_WRITTEN")
        self.assertEqual(payload["figure_verification_state"], "NOT_RUN")
        self.assertEqual(payload["commit_state"], "NOT_WRITTEN", "兼容字段语义不变")
        self.assertIsNone(payload["figure_verification"])

        # 取消之后同样：零写入 → NOT_WRITTEN + NOT_RUN。
        status, cancelled = http_json(self.port, "POST",
                                      f"/api/plans/{plan['plan_id']}/cancel", NO_BODY, {})
        self.assertEqual((status, cancelled["state"]), (200, "CANCELLED"), cancelled)
        status, payload = self.apply_plan(plan["plan_id"])
        self.assertEqual((status, payload["status"]), (409, "PLAN_CANCELLED"), payload)
        self.assertEqual(payload["source_commit_state"], "NOT_WRITTEN")
        self.assertEqual(payload["figure_verification_state"], "NOT_RUN")
        self.assertEqual(self.script.read_bytes(), self.original_bytes, "拒绝时必须零写入")
        self.assertEqual(self.checkpoints(), [])


class CommittedAndVerifiedCases(_StatesCase):
    """写入且重建通过：``COMMITTED`` + ``PASS``，证据与磁盘逐字节对得上。"""

    def test_commit_with_a_passing_rebuild_is_committed_and_pass(self):
        self.start()
        original = self.root / "original.py"
        original.write_bytes(SCRIPT.encode("utf8"))
        plan, status, payload = self.commit_and_verify()
        self.assertEqual((status, payload["status"]), (200, "OK"), payload)
        self.assertEqual(payload["source_commit_state"], "COMMITTED")
        self.assertEqual(payload["figure_verification_state"], "PASS")
        self.assertEqual(payload["problems"], [])
        # 兼容字段照旧：journal + 逐文件字节核对通过。
        self.assertEqual(payload["commit_state"], "COMMITTED_AND_VERIFIED")

        written = self.script.read_bytes()
        self.assertEqual(sha256_hex(written), plan["files"][0]["after_sha256"])
        self.assertNotEqual(sha256_hex(written), sha256_hex(self.original_bytes))

        evidence = payload["figure_verification"]
        self.assertEqual(evidence["state"], "PASS")
        self.assertEqual(evidence["script_sha256"], sha256_hex(written),
                         "证据必须绑定这次提交的字节")
        self.assertEqual(evidence["gid"], TARGET)
        self.assertEqual(evidence["scope"], SCOPE)
        self.assertEqual(evidence["requested_mm"], SHIFT_MM)
        self.assertEqual(evidence["tolerance_mm"], python_native.VERIFY_TOL_MM)
        self.assertIsNotNone(evidence["measured_mm"])
        max_residual = max(abs(value) for value in evidence["residual_mm"])
        self.assertLessEqual(max_residual, python_native.VERIFY_TOL_MM,
                             f"实测残差 {evidence['residual_mm']} 必须落在容差内")
        self.assertEqual(evidence["science_sha256"], evidence["science_sha256_before"],
                         "科学指纹必须一动不动")
        self.assertGreater(evidence["geometry_keys"], 0)
        self.assertIn(TARGET, evidence["gids"])

        # 复核自报的实测位移：本进程用同一套会话机制另量一次（与子进程探针不同源）。
        before = measured_geometry(original, self.config)
        after = measured_geometry(self.script, self.config)
        delta = [after[TARGET_KEY][axis] - before[TARGET_KEY][axis] for axis in (0, 1)]
        for axis in (0, 1):
            self.assertAlmostEqual(delta[axis], SHIFT_MM[axis],
                                   delta=python_native.VERIFY_TOL_MM)
            self.assertAlmostEqual(delta[axis], payload["measured_mm"][axis],
                                   delta=python_native.VERIFY_TOL_MM,
                                   msg=f"自报位移 {payload['measured_mm']} 与独立重建不符")
        for key in before:
            if key == TARGET_KEY:
                continue
            for axis in range(4):
                self.assertAlmostEqual(after[key][axis], before[key][axis],
                                       delta=python_native.VERIFY_TOL_MM,
                                       msg=f"{key} 不应跟着动")

        # 页面读的是同一个真相。
        public = self.plan(plan["plan_id"])
        self.assertEqual(public["state"], "APPLIED")
        self.assertEqual(public["source_commit_state"], "COMMITTED")
        self.assertEqual(public["figure_verification_state"], "PASS")
        self.assertIs(public["figure_verification_stale"], False)

        # 历史回执同样带两个字段与证据：写盘是事实，验证结论跟着这次提交走。
        checkpoints = self.checkpoints()
        self.assertEqual(len(checkpoints), 1, checkpoints)
        recorded = checkpoints[0]["payload"]
        self.assertEqual(recorded["source_commit_state"], "COMMITTED")
        self.assertEqual(recorded["figure_verification_state"], "PASS")
        self.assertEqual(recorded["commit_state"], "COMMITTED_AND_VERIFIED")
        self.assertEqual(recorded["figure_verification"]["script_sha256"],
                         sha256_hex(self.script.read_bytes()))
        self.assertEqual(recorded["file_changes"][0]["after_sha256"], sha256_hex(written))


class CommittedButUnverifiedCases(_StatesCase):
    """写入但验证没过/没跑完：源码**已提交**是事实，验证如实报 FAIL / ERROR。"""

    def test_rebuild_that_cannot_finish_is_committed_error_not_not_written(self):
        self.arm(_trap_body(TRAP_SCRIPT))
        self.start()
        plan, status, payload = self.commit_and_verify(value=TRAP_SHIFT_MM)
        self.assertEqual((status, payload["status"]), (200, "OK"), payload)
        self.assertEqual(payload["source_commit_state"], "COMMITTED", payload)
        self.assertEqual(payload["figure_verification_state"], "ERROR", payload)
        # 写盘是事实：字节按计划改了，兼容字段也照旧。
        self.assertEqual(sha256_hex(self.script.read_bytes()),
                         plan["files"][0]["after_sha256"])
        self.assertEqual(payload["commit_state"], "COMMITTED_AND_VERIFIED")
        self.assertIsNone(payload["measured_mm"], "探针没跑完就不许编一个实测值")
        self.assertTrue(any("重建" in problem for problem in payload["problems"]),
                        payload["problems"])
        self.assertEqual(payload["figure_verification"]["script_sha256"],
                         sha256_hex(self.script.read_bytes()))
        self.assertEqual(payload["figure_verification"]["state"], "ERROR")
        # 事后状态照实说，history 也留着这条写入事实。
        self.assertNotEqual(self.plan(plan["plan_id"])["figure_verification_state"], "PASS")
        self.assertEqual(len(self.checkpoints()), 1)

    def test_rebuild_that_shows_an_unreached_shift_is_committed_fail(self):
        self.arm(_clamp_body(CLAMPED_SCRIPT))
        self.start()
        plan, status, payload = self.commit_and_verify(value=UNREACHED_MM)
        self.assertEqual((status, payload["status"]), (200, "OK"), payload)
        self.assertEqual(payload["source_commit_state"], "COMMITTED", payload)
        self.assertEqual(payload["figure_verification_state"], "FAIL", payload)
        self.assertEqual(sha256_hex(self.script.read_bytes()),
                         plan["files"][0]["after_sha256"], "写盘已成事实，不得说成未写入")
        self.assertEqual(payload["commit_state"], "COMMITTED_AND_VERIFIED",
                         "兼容字段只说写入语义；科学/几何结论看上面两个独立字段")
        self.assertAlmostEqual(payload["measured_mm"][1], CLAMP_MM, delta=0.01)
        self.assertGreater(abs(payload["figure_verification"]["residual_mm"][1]),
                           python_native.VERIFY_TOL_MM)
        self.assertTrue(any("实测位移" in problem for problem in payload["problems"]),
                        payload["problems"])
        self.assertEqual(self.plan(plan["plan_id"])["figure_verification_state"], "FAIL")
        self.assertEqual(len(self.checkpoints()), 1)

    def test_unknown_workspace_identity_still_says_committed(self):
        """服务端不知道 config/scope：写盘照样是事实，验证只能报 ERROR（不许含糊成"未写"）。"""
        self.start(source=False)
        plan, status, payload = self.commit_and_verify()
        self.assertEqual((status, payload["status"]), (200, "OK"), payload)
        self.assertEqual(payload["source_commit_state"], "COMMITTED")
        self.assertEqual(payload["figure_verification_state"], "ERROR")
        self.assertEqual(payload["commit_state"], "COMMITTED_AND_VERIFIED")
        self.assertEqual(sha256_hex(self.script.read_bytes()),
                         plan["files"][0]["after_sha256"])
        self.assertEqual(payload["checkpoint_id"], None)
        self.assertEqual(payload["history_error"], "SOURCE_IDENTITY_UNKNOWN")


class VerificationEvidenceLifetimeCases(_StatesCase):
    """证据绑定提交版本：源码事后再变，旧的 PASS 就不再是当前文件的验证结果。"""

    def test_an_old_pass_stops_counting_after_the_source_changes(self):
        self.start()
        plan, status, payload = self.commit_and_verify()
        self.assertEqual((status, payload["figure_verification_state"]), (200, "PASS"), payload)
        evidence = payload["figure_verification"]
        self.assertTrue(python_native.verification_is_current(evidence, self.script))

        # 事后（绕过 Hub）改盘：这份 PASS 绑定的字节已经不是磁盘上的字节。
        self.script.write_bytes(self.script.read_bytes() + "# 事后改动\n".encode("utf-8"))
        self.assertFalse(python_native.verification_is_current(evidence, self.script))

        public = self.plan(plan["plan_id"])
        self.assertEqual(public["source_commit_state"], "COMMITTED",
                         "当时确实写盘了，这条历史事实不因事后改动而消失")
        self.assertIs(public["figure_verification_stale"], True)
        self.assertEqual(public["figure_verification_stale_reason"], "SOURCE_CHANGED")
        self.assertEqual(public["figure_verification_state"], python_native.FIGURE_NOT_RUN,
                         "旧 PASS 不得继续显示成当前文件的验证结果")
        self.assertEqual(public["figure_verification"]["state"], "PASS",
                         "旧证据原样留档：它说的是**当时那一版**通过过")
        self.assertEqual(public["figure_verification"]["script_sha256"],
                         evidence["script_sha256"])


class CompatibilityCases(_StatesCase):
    """兼容回归：``commit_state`` 仍在，且只表达写入语义。"""

    def test_commit_state_maps_to_source_state_without_any_verdict(self):
        mapping = [(python_native.COMMITTED_AND_VERIFIED, "COMMITTED"),
                   (python_native.COMMITTED_BUT_UNVERIFIED, "COMMITTED"),
                   (python_native.RECOVERY_REQUIRED, "RECOVERY_REQUIRED"),
                   (python_native.NOT_WRITTEN, "NOT_WRITTEN")]
        for commit_state, expected in mapping:
            with self.subTest(commit_state=commit_state):
                self.assertEqual(python_native.source_commit_state_of(commit_state), expected)
        # 翻译出来的只有写入语义：没有任何输入能翻出 PASS。
        self.assertNotIn("PASS", [python_native.source_commit_state_of(state)
                                  for state, _ in mapping])

    def test_evidence_from_another_version_is_not_current(self):
        digest = sha256_hex(b"another version")
        other = self.root / "other.py"
        other.write_bytes(b"another version")
        self.assertTrue(python_native.verification_is_current(
            {"script_sha256": digest}, other))
        self.assertFalse(python_native.verification_is_current(
            {"script_sha256": sha256_hex(b"x")}, other))
        self.assertFalse(python_native.verification_is_current(None, other))
        self.assertFalse(python_native.verification_is_current({"script_sha256": digest},
                                                               self.root / "missing.py"))


if __name__ == "__main__":
    unittest.main()
