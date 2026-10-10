"""figpact GUI 原型简易 HTTP 后端 (只使用 Python 标准库)。

启动命令:
    python tools/gui/server.py --port 8000
    或在 figpact 根目录下运行:
    python -X utf8 tools/gui/server.py
"""
import argparse
import base64
import http.server
import importlib.util
import io
import json
import os
import socketserver
import subprocess
import sys
import tempfile
import urllib.parse
from pathlib import Path
from typing import Any, Optional

import yaml

# 保证当前仓在 sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))

from figpact.cli import (
    _deep_merge_dict,
    _run_script_inventory,
    _run_script_strict,
)
from figpact.params import export_params_catalog
from figpact.qa import signature


def _render_script_png_base64(script_path: Path, config_path: Path) -> Optional[str]:
    """通过子进程以 Agg 后端静默渲染图表并返回 PNG base64 字符串。"""
    code = """import sys, base64, io, importlib.util
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

script_p = Path(sys.argv[1]).resolve()
cfg_p = Path(sys.argv[2]).resolve()

spec = importlib.util.spec_from_file_location('script_mod', script_p)
mod = importlib.util.module_from_spec(spec)
sys.argv = [script_p.name, '--config', str(cfg_p), '--inventory']
try:
    spec.loader.exec_module(mod)
except SystemExit:
    pass

fig = getattr(mod, 'fig', None)
if fig is None and hasattr(mod, 'build_figure_and_registry'):
    fig, _ = mod.build_figure_and_registry('annotated')

if fig is not None:
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=150, bbox_inches='tight')
    plt.close(fig)
    print('PNG_B64_DATA:' + base64.b64encode(buf.getvalue()).decode('ascii'))
"""
    try:
        res = subprocess.run(
            [sys.executable, "-X", "utf8", "-c", code, str(script_path), str(config_path)],
            cwd=str(script_path.parent),
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        for line in res.stdout.splitlines():
            if line.startswith("PNG_B64_DATA:"):
                return line[len("PNG_B64_DATA:"):].strip()
    except Exception as e:
        print(f"[渲染错误] {e}", file=sys.stderr)
    return None


def _get_preset_figure_info(name: str) -> dict[str, Path]:
    if name == "nmr":
        return {
            "script": ROOT_DIR / "examples" / "nmr" / "08 NMR.py",
            "config": ROOT_DIR / "examples" / "nmr" / "nmr.yaml",
        }
    return {
        "script": ROOT_DIR / "examples" / "ftir" / "plot_ftir.py",
        "config": ROOT_DIR / "examples" / "ftir" / "ftir.yaml",
    }


class FigpactGuiHandler(http.server.SimpleHTTPRequestHandler):
    """处理前端 API 与静态资源的轻量 Handler。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT_DIR / "tools" / "gui"), **kwargs)

    def do_GET(self):
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

        if path == "/api/params":
            fig_name = query.get("figure", ["ftir"])[0]
            info = _get_preset_figure_info(fig_name)
            catalog = export_params_catalog(info["script"], info["config"])
            # 渲染当前基线 PNG
            current_png_b64 = _render_script_png_base64(info["script"], info["config"])
            catalog["current_png"] = current_png_b64
            self._send_json(catalog)
            return

        super().do_GET()

    def do_POST(self):
        url_parts = urllib.parse.urlparse(self.path)
        path = url_parts.path

        if path == "/api/try":
            content_length = int(self.headers.get("Content-Length", 0))
            body_bytes = self.rfile.read(content_length)
            try:
                payload = json.loads(body_bytes.decode("utf-8"))
            except Exception as e:
                self._send_error_json(f"JSON 解析失败: {e}")
                return

            fig_name = payload.get("figure", "ftir")
            patch_yaml_str = payload.get("patch_yaml", "")
            run_bisection = payload.get("bisection", False)

            info = _get_preset_figure_info(fig_name)
            script = info["script"]
            base_yaml_path = info["config"]

            base_config = yaml.safe_load(base_yaml_path.read_text(encoding="utf-8")) or {}
            patched_config = yaml.safe_load(base_yaml_path.read_text(encoding="utf-8")) or {}
            try:
                patch_dict = yaml.safe_load(patch_yaml_str) or {}
                if isinstance(patch_dict, dict):
                    _deep_merge_dict(patched_config, patch_dict)
            except Exception as e:
                self._send_error_json(f"Patch YAML 解析错误: {e}")
                return

            with tempfile.TemporaryDirectory(prefix="figpact-try-gui-") as tmp_dir:
                td = Path(tmp_dir)
                patched_yaml = td / "patched.yaml"
                patched_yaml.write_text(yaml.safe_dump(patched_config), encoding="utf-8")

                # 1. 运行 inventory 并计算位移
                inv_before = _run_script_inventory(script, base_yaml_path)
                inv_after = _run_script_inventory(script, patched_yaml)

                snap_map_before = {it["gid"]: it.get("snapshot", {}) for it in inv_before.get("items", [])}
                snap_map_after = {it["gid"]: it.get("snapshot", {}) for it in inv_after.get("items", [])}
                movements = []
                px_per_mm = 300.0 / 25.4

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
                            movements.append({
                                "gid": gid,
                                "dx_mm": round(dx_mm, 2),
                                "dy_mm": round(dy_mm, 2),
                                "dist_mm": round(dist_mm, 2),
                                "text": f"dx={dx_mm:+.2f} mm, dy={dy_mm:+.2f} mm (位移 {dist_mm:.2f} mm)",
                            })

                # 2. 运行 baseline 与 try 的 strict 检查计算 QA 差异
                code_before, qa_before = _run_script_strict(script, base_yaml_path)
                code_after, qa_after = _run_script_strict(script, patched_yaml)

                sig_before = {signature(q): q for q in qa_before}
                sig_after = {signature(q): q for q in qa_after}

                added_sigs = sorted(set(sig_after.keys()) - set(sig_before.keys()))
                removed_sigs = sorted(set(sig_before.keys()) - set(sig_after.keys()))

                qa_delta = {
                    "added": [sig_after[s] for s in added_sigs],
                    "removed": [sig_before[s] for s in removed_sigs],
                    "code_before": code_before,
                    "code_after": code_after,
                    "status_text": "通过 (PASS)" if code_after == 0 else f"阻断 (EXIT {code_after})",
                }

                # 3. 实时渲染新图 PNG
                new_png_b64 = _render_script_png_base64(script, patched_yaml)

                # 4. 可选二分可行区间
                feasible_intervals = []
                if run_bisection and patch_dict:
                    # 获取首个修改的标量数字键
                    mod_keys = [k for k in patch_dict.keys() if isinstance(patch_dict[k], (int, float)) and not isinstance(patch_dict[k], bool)]
                    for p_key in mod_keys[:2]:  # 最多二分试算前2个，保证交互响应
                        val_now = patch_dict[p_key]
                        val_orig = base_config.get(p_key, 0.0)

                        def test_candidate(v_test: float) -> bool:
                            c_test = yaml.safe_load(yaml.safe_dump(base_config))
                            c_test[p_key] = v_test
                            cand_yaml = td / "cand.yaml"
                            cand_yaml.write_text(yaml.safe_dump(c_test), encoding="utf-8")
                            c_ret, _ = _run_script_strict(script, cand_yaml)
                            return c_ret == 0

                        v_orig_val = float(val_orig)
                        low = v_orig_val - max(abs(float(val_now) - v_orig_val) * 3.0, 5.0)
                        high = v_orig_val
                        iters_low = 0
                        if test_candidate(high):
                            while high - low > 0.05 and iters_low < 8:
                                mid = (low + high) / 2.0
                                iters_low += 1
                                if test_candidate(mid):
                                    high = mid
                                else:
                                    low = mid
                            f_min = high
                        else:
                            f_min = v_orig_val

                        low_u = v_orig_val
                        high_u = v_orig_val + max(abs(float(val_now) - v_orig_val) * 3.0, 5.0)
                        iters_high = 0
                        if test_candidate(low_u):
                            while high_u - low_u > 0.05 and iters_high < 8:
                                mid = (low_u + high_u) / 2.0
                                iters_high += 1
                                if test_candidate(mid):
                                    low_u = mid
                                else:
                                    high_u = mid
                            f_max = low_u
                        else:
                            f_max = v_orig_val

                        feasible_intervals.append({
                            "key": p_key,
                            "interval": [round(f_min, 2), round(f_max, 2)],
                            "iterations": iters_low + iters_high,
                        })

                response_data = {
                    "figure": fig_name,
                    "movements": movements,
                    "qa_delta": qa_delta,
                    "new_png": new_png_b64,
                    "feasible_intervals": feasible_intervals,
                }
                self._send_json(response_data)
            return

        self._send_error_json(f"未知接口: {path}")

    def _send_json(self, data: Any):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
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

    addr = ("", args.port)
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
