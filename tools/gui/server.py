"""figpact GUI 原型简易 HTTP 后端 (只使用 Python 标准库)。

启动命令:
    python tools/gui/server.py --port 8000
    或在 figpact 根目录下运行:
    python -X utf8 tools/gui/server.py
"""
import argparse
import http.server
import json
import socketserver
import sys
import time
import urllib.parse
import tempfile
from pathlib import Path
from typing import Any

import yaml

# 保证当前仓在 sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))

from figpact.params import export_params_catalog
from figpact.qa import diagnose, diagnostic_key
from figpact.preview import preview, revision, load_plot
from figpact.cli import _run_script_strict
from figpact.patch import apply_patch_text, config_revision, commit_changes, undo_changes, RevisionConflict

BASELINES = {}
UNDOS = {}
OUTPUT_STEMS = {
    "ftir": ("Fig2_FTIR_transmittance_stacked", "Fig2_FTIR_transmittance_stacked_annotated",
             "Fig2_FTIR_transmittance_raw_processed"),
    "nmr": ("Fig2_NMR_pure_stacked",),
}


def baseline_preview(info, scope):
    key = (str(info["script"]), scope)
    rev = revision(info["script"], info["config"])
    cached = BASELINES.get(key)
    if cached is None or cached["revision"] != rev:
        cached = preview(**info, scope=scope)
        BASELINES[key] = cached
    return cached




def _validate_scope(name: str, scope: str) -> None:
    scopes = {"ftir": ("main", "annotated", "compare_raw", "compare_processed"),
              "nmr": ("main",)}
    if name not in scopes or scope not in scopes[name]:
        raise ValueError(f"无效图表或 scope：{name}/{scope}")


def _get_preset_figure_info(name: str) -> dict[str, Path]:
    if name == "nmr":
        return {
            "script": ROOT_DIR / "examples" / "nmr" / "08 NMR.py",
            "config": ROOT_DIR / "examples" / "nmr" / "nmr.yaml",
        }
    if name != "ftir":
        raise ValueError(f"未知图表：{name}")
    return {
        "script": ROOT_DIR / "examples" / "ftir" / "plot_ftir.py",
        "config": ROOT_DIR / "examples" / "ftir" / "ftir.yaml",
    }
def save_candidate(info, figure, scope, patch, expected, mode):
    started = time.perf_counter()
    config = info["config"]
    if config_revision(config) != expected:
        raise RevisionConflict("配置已更新，请重新加载；你的磁盘修改未被覆盖")
    catalog = export_params_catalog(info["script"], config)
    source = config.read_bytes().decode("utf8")
    text = apply_patch_text(source, patch, catalog)
    if mode not in ("draft", "publish"):
        raise ValueError("保存模式必须是 draft 或 publish")
    with tempfile.TemporaryDirectory(prefix="figpact-save-") as td:
        candidate = Path(td) / config.name
        candidate.write_bytes(text.encode("utf8"))
        load_plot(info["script"], candidate)  # Validate config without constructing a Figure.
        changes = {config: candidate.read_bytes()}
        saved_revision = config_revision(candidate)
        if mode == "publish":
            outputs = Path(td) / "outputs"
            outputs.mkdir()
            code, qa = _run_script_strict(info["script"], candidate, outputs)
            if code:
                return {"state": "publish_failed", "qa_kind": "publish_strict", "qa": qa,
                        "message": f"正式验收失败（退出码 {code}）；配置与正式图均未修改",
                        "config_revision": config_revision(config), "seconds": time.perf_counter()-started}
            for stem in OUTPUT_STEMS[figure]:
                for extension in ("svg", "pdf", "png", "tiff"):
                    path = outputs / f"{stem}.{extension}"
                    if not path.is_file():
                        raise ValueError(f"缺少正式图件 {path.name}，拒绝更新配置和图件")
                    changes[config.parent / path.name] = path.read_bytes()
        try:
            result = preview(script=info["script"], config=candidate, scope=scope)
            current_qa, png = result["qa"], result["png"]
        except Exception as error:
            if mode == "publish":
                raise
            current_qa, png = [f"候选图无法构建：{error}"], None
        UNDOS[figure] = commit_changes(config, expected, changes)
    for key in list(BASELINES):
        if key[0] == str(info["script"]):
            del BASELINES[key]
    message = ("完整 strict 通过，配置和全部正式图已发布" if mode == "publish" else
               "草稿已保存；当前 scope 有阻断，不可发布" if current_qa else
               "草稿已保存；尚未执行完整 strict，未发布正式图")
    return {"state": "published" if mode == "publish" else "draft",
            "qa_kind": "publish_strict" if mode == "publish" else "preview_qa",
            "qa": qa if mode == "publish" else current_qa, "new_png": png, "message": message,
            "config_revision": saved_revision, "seconds": time.perf_counter()-started}




class FigpactGuiHandler(http.server.SimpleHTTPRequestHandler):
    """处理前端 API 与静态资源的轻量 Handler。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT_DIR / "tools" / "gui"), **kwargs)

    def _origin_allowed(self) -> bool:
        """只接受本机来源。这个服务能执行本地绘图脚本，不能对任意网页开放。

        没带 Origin 的请求（curl / 同源导航 / 文件直开）放行——它们不是浏览器
        的跨站请求；带了 Origin 的必须是本机同端口，否则拒。
        """
        origin = self.headers.get("Origin")
        if not origin:
            return True
        port = self.server.server_address[1]
        return origin in {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}

    def _reject_foreign_origin(self) -> bool:
        """返回 True 表示已拒绝并回过响应，调用方直接 return。"""
        if self._origin_allowed():
            return False
        self._send_error_json("来源不被允许：本服务只接受 127.0.0.1 的本机页面", 403)
        return True

    def do_GET(self):
        if self._reject_foreign_origin():
            return
        url_parts = urllib.parse.urlparse(self.path)
        path = url_parts.path
        query = urllib.parse.parse_qs(url_parts.query)

        if path == "/api/figures":
            data = [
                {"id": "ftir", "name": "Fig.2 FTIR (红外光谱面板)", "script": "examples/ftir/plot_ftir.py", "config": "examples/ftir/ftir.yaml"},
                {"id": "nmr", "name": "Fig.2 NMR (核磁共振叠谱)", "script": "examples/nmr/08 NMR.py", "config": "examples/nmr/nmr.yaml"},
            ]
            self._send_json(data)
            return

        if path in ("/api/params", "/api/baseline"):
            fig_name = query.get("figure", ["ftir"])[0]
            scope = query.get("scope", ["annotated" if fig_name == "ftir" else "main"])[0]
            try:
                _validate_scope(fig_name, scope)
                info = _get_preset_figure_info(fig_name)
                config_rev = config_revision(info["config"])
                baseline = baseline_preview(info, scope)
                catalog = export_params_catalog(info["script"], info["config"]) if path == "/api/params" else {}
                if config_revision(info["config"]) != config_rev:
                    raise RevisionConflict("加载期间配置发生变化，请重新加载")
                catalog.update(current_png=baseline["png"], scope=scope, revision=baseline["revision"],
                               config_revision=config_rev, can_undo=fig_name in UNDOS, qa=baseline["qa"])
            except Exception as exc:
                self._send_error_json(str(exc))
                return
            self._send_json(catalog)
            return

        super().do_GET()

    def do_POST(self):
        if self._reject_foreign_origin():
            return
        url_parts = urllib.parse.urlparse(self.path)
        path = url_parts.path
        if path in ("/api/save", "/api/undo"):
            try:
                payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                figure, scope = payload["figure"], payload["scope"]
                _validate_scope(figure, scope)
                info = _get_preset_figure_info(figure)
                expected = payload["config_revision"]
                if path == "/api/undo":
                    if figure not in UNDOS:
                        raise ValueError("当前会话没有可撤销的保存")
                    record = UNDOS[figure]
                    restored = undo_changes(info["config"], expected, record)
                    del UNDOS[figure]
                    for key in list(BASELINES):
                        if key[0] == str(info["script"]):
                            del BASELINES[key]
                    response = {"state": "undone",
                                "message": "上次保存已撤销" + ("，正式图也已恢复" if len(record["before"]) > 1 else "；正式图未改动"),
                                "config_revision": restored["after"][info["config"]]}
                else:
                    patch = yaml.safe_load(payload.get("patch_yaml", "")) or {}
                    response = save_candidate(info, figure, scope, patch, expected, payload["mode"])
            except RevisionConflict as error:
                self._send_error_json(str(error), 409)
                return
            except Exception as error:
                self._send_error_json(str(error))
                return
            self._send_json(response)
            return


        if path == "/api/try":
            started = time.perf_counter()
            try:
                payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                fig_name, scope = payload["figure"], payload["scope"]
                _validate_scope(fig_name, scope)
                patch = yaml.safe_load(payload.get("patch_yaml", "")) or {}
                if not isinstance(patch, dict):
                    raise ValueError("Patch YAML 必须是映射")
                info = _get_preset_figure_info(fig_name)
                rev = revision(**info)
                before = BASELINES.get((str(info["script"]), scope))
                if before and before["revision"] != rev:
                    before = None
                after = preview(**info, scope=scope, patch=patch) if patch or before is None else before
                old_qa = before["qa"] if before else []
                old_keys = {diagnostic_key(diagnose(q)): q for q in old_qa}
                new_keys = {diagnostic_key(diagnose(q)): q for q in after["qa"]}
                movements = []
                if before:
                    a = before["inventory"]
                    b = after["inventory"]
                    old_boxes = {it["gid"]: it["snapshot"].get("bbox") for it in a["items"]}
                    for item in b["items"]:
                        bb0, bb1 = old_boxes.get(item["gid"]), item["snapshot"].get("bbox")
                        if not bb0 or not bb1:
                            continue
                        c0 = [(bb0[i]+bb0[i+2])*12.7/a["figure_dpi"] for i in (0, 1)]
                        c1 = [(bb1[i]+bb1[i+2])*12.7/b["figure_dpi"] for i in (0, 1)]
                        dx, dy = (c1[i]-c0[i] for i in (0, 1))
                        if max(abs(dx), abs(dy)) > 0.05:
                            movements.append({"gid": item["gid"], "dx_mm": dx, "dy_mm": dy,
                                              "text": f"dx={dx:+.2f} mm, dy={dy:+.2f} mm"})
                response = {
                    "figure": fig_name, "scope": scope, "revision": rev,
                    "new_png": after["png"], "inventory": after["inventory"],
                    "relations": after["relations"], "space": after["space"],
                    "movements": movements, "qa": after["qa"], "qa_kind": "preview_qa",
                    "qa_delta": {
                        "added": [new_keys[k] for k in sorted(new_keys.keys()-old_keys.keys())],
                        "removed": [old_keys[k] for k in sorted(old_keys.keys()-new_keys.keys())],
                        "code_before": int(bool(old_qa)), "code_after": int(bool(after["qa"])),
                        "status_text": "当前 scope 有阻断，不可发布" if after["qa"] else "当前 scope 通过；尚未正式发布",
                    },
                    "feasible_intervals": [], "seconds": time.perf_counter()-started,
                }
            except Exception as exc:
                self._send_error_json(str(exc))
                return
            self._send_json(response)
            return

        self._send_error_json(f"未知接口: {path}")

    def _send_json(self, data: Any):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        # 不回显 `*`：只把请求方自己的 Origin 回显给它（闸门已保证是本机）
        _origin = self.headers.get("Origin")
        if _origin:
            self.send_header("Access-Control-Allow-Origin", _origin)
        self.end_headers()
        self.wfile.write(body)

    def _send_error_json(self, message: str, code: int = 400):
        body = json.dumps({"error": message}, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    parser = argparse.ArgumentParser(description="figpact GUI 原型 HTTP 服务")
    parser.add_argument("--port", type=int, default=8000, help="监听端口 (默认 8000)")
    args = parser.parse_args()

    addr = ("127.0.0.1", args.port)  # 只监听本机：这个服务能执行本地绘图脚本
    with socketserver.TCPServer(addr, FigpactGuiHandler) as httpd:
        print(f"[figpact GUI 原型服务已启动]")
        print(f"  地址: http://127.0.0.1:{args.port}")
        print(f"  按 Ctrl+C 停止服务\n")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n[服务已停止]")


if __name__ == "__main__":
    main()
