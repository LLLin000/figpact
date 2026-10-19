"""G23 tick-clip overlay regression (structured records, consumer-visible).

Structured tick clipping (TICK_CLIP, mm/0.0/up/blocking) through
style_overlay.apply(allow_draft=True): new clip refused, worsening
refused, inherited-not-worse drafts only as whole-FAIL, unmeasured
refused with no official bytes. Real consumer-visible wrapper figures
(actual renderer bboxes), never text/mock echoes.
"""
from __future__ import annotations

import hashlib
import unittest

import matplotlib

matplotlib.use("Agg")

from figpact import style_overlay


def _h(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


WRAPPER = (
    "import matplotlib\nmatplotlib.use(\"Agg\")\n"
    "import matplotlib.pyplot as plt\nfrom figpact import GidRegistry\n"
    'SCOPES = ("main",)\nCONFIG = {}\n{extra}\n'
    "def build_figure_and_registry(scope=\"main\"):\n"
    "    fig, ax = plt.subplots(figsize=(4, 3))\n"
    "    fig.subplots_adjust(left=0.30, right=0.9, bottom=0.25, top=0.9)\n"
    "    ax.plot([0, 1], [0, 1])\n"
    "    ax.set_ylabel(\"dose\", fontsize=6)\n"
    "    ax.set_yticks([0, 0.5, 1.0])\n"
    '    ax.set_yticklabels(["-123456.789", "-123456.789", "-123456.789"], fontsize={tickfs})\n'
    "    for t in ax.get_xticklabels(): t.set_fontsize(6)\n"
    "    {body}\n"
    "    return fig, GidRegistry(scope=scope)\n"
)


def _write(path, tickfs=6, body="", extra=""):
    path.write_text(WRAPPER.replace("{tickfs}", str(tickfs))
                    .replace("{extra}", extra).replace("{body}", body),
                    encoding="utf-8")
    return path


def _tick_y_id(script):
    return next(t["id"] for t in style_overlay.inventory(script, scope="main")
                if t["role"] == "axis.tick" and t["id"].endswith(".tick.y.fontsize"))


def _curve_id(script):
    return next(t["id"] for t in style_overlay.inventory(script, scope="main")
                if t["role"] == "curve.linewidth")


class TickClipOverlayTest(unittest.TestCase):
    def test_new_tick_clip_refused_no_bytes(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            script = _write(tmp / "w.py", tickfs=6)
            overlay = tmp / "clip.json"
            r = style_overlay.apply(script, scope="main",
                                    edits=[{"target_id": _tick_y_id(script),
                                            "value": 20.0}],
                                    overlay=overlay, allow_draft=True)
            self.assertEqual(r["source_commit_state"], "NOT_WRITTEN", r)
            self.assertEqual(r["figure_verification_state"], "FAIL", r)
            self.assertFalse(r["qa_delta"]["eligible"], r["qa_delta"])
            self.assertTrue(r["qa_delta"]["new"], r["qa_delta"])
            self.assertFalse(overlay.exists())

    def test_worsened_tick_clip_refused_no_bytes(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            script = _write(tmp / "w.py", tickfs=20)
            overlay = tmp / "worse.json"
            r = style_overlay.apply(script, scope="main",
                                    edits=[{"target_id": _tick_y_id(script),
                                            "value": 28.0}],
                                    overlay=overlay, allow_draft=True)
            self.assertEqual(r["source_commit_state"], "NOT_WRITTEN", r)
            self.assertFalse(r["qa_delta"]["eligible"], r["qa_delta"])
            self.assertTrue(r["qa_delta"]["worsened"], r["qa_delta"])
            self.assertFalse(overlay.exists())

    def test_inherited_tick_clip_drafts_only_as_whole_fail(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            script = _write(tmp / "w.py", tickfs=20)
            overlay = tmp / "draft.json"
            r = style_overlay.apply(script, scope="main",
                                    edits=[{"target_id": _curve_id(script),
                                            "value": 0.8}],
                                    overlay=overlay, allow_draft=True)
            self.assertEqual(r["local_edit_state"], "PASS", r)
            self.assertEqual(r["source_commit_state"], "COMMITTED_DRAFT", r)
            self.assertEqual(r["figure_verification_state"], "FAIL", r)
            self.assertTrue(r["qa_delta"]["eligible"], r["qa_delta"])
            self.assertTrue(r["qa_delta"]["inherited"], r["qa_delta"])
            saved = overlay.read_bytes()
            for opener in (style_overlay.load_workspace, style_overlay.load):
                fig, _, loaded = opener(overlay)
                try:
                    if opener is style_overlay.load_workspace:
                        self.assertIsNotNone(fig)
                    else:
                        self.assertIsNone(fig)
                    self.assertEqual(loaded["figure_verification_state"], "FAIL", loaded)
                finally:
                    import matplotlib.pyplot as _plt
                    try:
                        _plt.close(fig)
                    except Exception:
                        pass
            out = tmp / "out.png"
            rendered = style_overlay.render(overlay, out)
            self.assertEqual(rendered["figure_verification_state"], "FAIL", rendered)
            self.assertFalse(out.exists())
            self.assertEqual(overlay.read_bytes(), saved)

    def test_unmeasured_tick_geometry_refused_no_bytes(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            script = _write(tmp / "w.py", tickfs=6, extra="import matplotlib.ticker as _mt\n",
                            body="ax.set_xlim(0, 1)\n    "
                                 "ax.xaxis.set_major_locator(_mt.FixedLocator([0.5, 0.5]))")
            overlay = tmp / "unm.json"
            r = style_overlay.apply(script, scope="main",
                                    edits=[{"target_id": _curve_id(script),
                                            "value": 0.8}],
                                    overlay=overlay, allow_draft=True)
            self.assertEqual(r["source_commit_state"], "NOT_WRITTEN", r)
            self.assertFalse(r["qa_delta"]["eligible"], r["qa_delta"])
            self.assertTrue(r["qa_delta"]["unmeasured"], r["qa_delta"])
            self.assertFalse(overlay.exists())


if __name__ == "__main__":
    unittest.main()
