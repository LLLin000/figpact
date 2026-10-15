#!/usr/bin/env python3
import json, os, shutil, subprocess, sys, tempfile, time
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "browser"))
from conftest import launch_server, node_by_gid, open_page, scene_of, wait_for

SELECTION_PATH = "/api/selection"
SAVE_PATH = "/api/save"
TARGET_GID = "fig2_nmr.main.peak.vancho.3p91"
EVALUATE_PATH = "/api/intents/evaluate"
def _grab_point(page, scene, node):
    import time
    left, bottom, right, top = node["bounds_mm"]
    rect = page.evaluate("""() => { const r=document.getElementById('viewport').getBoundingClientRect();
        return {left:r.left,top:r.top,width:r.width,height:r.height}; }""")
    canvas = scene["canvas_bounds_mm"]
    def to_client(mx, my):
        x = rect["left"] + (mx-canvas[0])/(canvas[2]-canvas[0])*rect["width"]
        y = rect["top"] + (canvas[3]-my)/(canvas[3]-canvas[1])*rect["height"]
        return x, y
    cx = left + 0.5*(right-left)
    cy = bottom + 0.5*(top-bottom)
    x, y = to_client(cx, cy)
    # ensure hover registers this node
    for _ in range(20):
        page.mouse.move(x, y)
        time.sleep(0.1)
        if page.get_attribute("#inspector-root", "data-hover-id") == node["id"]:
            break
    # final verify
    assert page.get_attribute("#inspector-root", "data-hover-id") == node["id"], "hover not registered"
    return x, y

OUT_DIR = ROOT / "docs" / "readme"
OUT_DIR.mkdir(parents=True, exist_ok=True)

def _arm_project(root):
    # 只用**合成演示图**：不得使用任何真实/用户图件（examples/nmr、examples/ftir 都不可）。
    project_dir = root / "project" / "examples" / "demo"
    project_dir.parent.mkdir(parents=True, exist_ok=True)
    src_dir = ROOT / "examples" / "demo"
    if project_dir.exists():
        shutil.rmtree(project_dir)
    shutil.copytree(src_dir, project_dir)
    return project_dir / "demo_figure.py", project_dir / "demo.yaml"

def _launch(root):
    script, config = _arm_project(root)
    server = launch_server(root, command=[sys.executable, "-B", "-X", "utf8", "-m", "figpact.inspector_server",
                                          "--script", str(script), "--config", str(config),
                                          "--scope", "main", "--dpi", "240", "--port", "0"])
    return server, script, config

def main():
    WORK = Path(tempfile.mkdtemp(prefix="readme-", dir=str(Path(os.environ.get("TEMP", tempfile.gettempdir())))))
    server, script, config = _launch(WORK)
    timings = {}
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context, page = open_page(browser, server.base_url)
            page.set_viewport_size({"width": 1600, "height": 1000})
            def shot(name):
                t0 = time.time()
                page.wait_for_timeout(300)
                page.screenshot(path=str(OUT_DIR / name), full_page=False)
                timings[name] = round(time.time()-t0, 2)
                print(f"{name} {timings[name]}s")
            page.wait_for_selector('#inspector-root[data-ready="true"][data-frame-state="verified"]', timeout=120000)
            shot("01-launch.png")

            scene = scene_of(page)
            # 动态挑选演示图里的一个**峰标注**（不硬编码任何具体图件的 gid）
            candidates = [n for n in scene["nodes"]
                          if ".peak." in n["id"] and n.get("registered") and n.get("measured")]
            assert candidates, "演示图里找不到可拖动的峰标注（检查 examples/demo 的 layout_contract）"
            node = sorted(candidates, key=lambda n: n["id"])[0]
            print("TARGET:", node["id"])
            x, y = _grab_point(page, scene, node)
            page.mouse.click(x, y)
            wait_for(lambda: page.get_attribute("#inspector-root", "data-selected-id") == node["id"], "select", timeout=10)
            shot("02-select.png")

            rect = page.evaluate("""() => { const r=document.getElementById('viewport').getBoundingClientRect();
                return {left:r.left,top:r.top,width:r.width,height:r.height}; }""")
            canvas = scene["canvas_bounds_mm"]
            px_per_mm = rect["width"] / (canvas[2]-canvas[0])
            dx_px, dy_px = round(1.2*px_per_mm), round(-0.9*px_per_mm)
            page.mouse.down()
            page.mouse.move(x+dx_px, y+dy_px, steps=12)
            time.sleep(0.6)
            shot("03-drag.png")
            page.mouse.up()
            time.sleep(5)
            print("BADGE after drag:", page.inner_text("#intent-status-badge"))
            wait_for(lambda: not page.is_disabled("#btn-accept") or True, "x", timeout=2)
            wait_for(lambda: not page.is_disabled("#btn-accept"), "accept", timeout=10)
            shot("04-verified.png")
            page.click("#btn-accept")
            wait_for(lambda: page.locator(".pending-save").count() == 1, "pending", timeout=30)
            shot("05-pending.png")

            with page.expect_response(lambda r: urlparse(r.url).path == SAVE_PATH and r.request.method == "POST") as waiting:
                page.click("#save-changes")
                page.wait_for_selector("#save-confirmation:not([hidden])", timeout=10000)
                page.click("#save-confirm")
            waiting.value.json()
            wait_for(lambda: page.inner_text("#save-result") == "修改已保存并通过验证", "saved", timeout=30)
            shot("06-saved.png")
            context.close()
            browser.close()

        server.stop()
        server2, script2, config2 = _launch(WORK)
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context, page = open_page(browser, server2.base_url)
            page.set_viewport_size({"width": 1600, "height": 1000})
            page.wait_for_selector('#inspector-root[data-ready="true"][data-frame-state="verified"]', timeout=120000)
            time.sleep(1)
            page.screenshot(path=str(OUT_DIR / "07-restart.png"), full_page=False)
            timings["07-restart.png"] = 0
            context.close()
            browser.close()
        server2.stop()
    finally:
        try: server.stop()
        except Exception: pass
    # 08 audit output as screenshot via text? write a small html and screenshot not now
    print("TIMINGS", json.dumps(timings, indent=2))
    print("DONE")

if __name__ == "__main__":
    main()
