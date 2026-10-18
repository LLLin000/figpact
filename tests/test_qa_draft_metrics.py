"""QA 实测记录回归：合法轴外图例 + 真实裁切 + 记录比较语义。"""
from __future__ import annotations

import unittest

import matplotlib
import numpy as np

matplotlib.use("Agg")

import matplotlib.pyplot as plt

from figpact import qa
from tests.fixtures import native_ftir


class LegendCanvasTest(unittest.TestCase):
    def tearDown(self):
        plt.close("all")

    def test_legit_outside_axes_but_inside_canvas_is_clean(self):
        fig, ax = plt.subplots(figsize=(4, 3), dpi=100)
        ax.plot([0, 1], [0, 1], gid="fig.main.curve.x")
        fig.subplots_adjust(left=0.15, right=0.95, bottom=0.15, top=0.80)
        leg = ax.legend(["s"], loc="lower center", bbox_to_anchor=(0.5, 1.02), ncol=1)
        leg.set_gid("fig.main.legend")
        self.assertEqual(qa.check_out_of_frame(fig), [])
        rec = qa.measure(fig)
        self.assertEqual([r for r in rec["records"] if r["rule"] == "OUT_OF_FRAME"], [])

    def test_true_canvas_clipped_legend_blocks(self):
        fig, ax = plt.subplots(figsize=(2, 2), dpi=100)
        ax.plot([0, 1], [0, 1], gid="fig.main.curve.x")
        leg = ax.legend(["s"], loc="upper left", bbox_to_anchor=(1.6, 1.6))
        leg.set_gid("fig.main.legend")
        problems = qa.check_out_of_frame(fig)
        self.assertTrue(any("超出画布" in p for p in problems), problems)
        recs = qa.collect_records(fig)
        self.assertTrue(any(r["rule"] == "OUT_OF_FRAME" for r in recs), recs)
        delta = qa.delta_records({"records": []}, {"records": recs})
        self.assertFalse(delta["eligible"])


class DeltaRecordsTest(unittest.TestCase):
    def tearDown(self):
        plt.close("all")

    def _text_fig(self, size: float):
        fig, ax = plt.subplots(figsize=(3, 2), dpi=100)
        ax.plot([0, 1], [0, 1], gid="fig.main.curve.x")
        ax.text(0.5, 0.5, "plain", fontsize=size, gid="fig.main.note")
        return fig

    def test_ftir_math_floor_inherits(self):
        cfg = native_ftir.load_config()
        sci = native_ftir.load_science()
        fig, _ = native_ftir.build_scene(sci, cfg, "main")
        try:
            rec = qa.measure(fig)
            self.assertTrue(any(r["rule"] == "GLYPH_FLOOR" for r in rec["records"]))
            delta = qa.delta_records(rec, rec)
            self.assertTrue(delta["eligible"], delta)
            self.assertEqual(delta["new"], [])
        finally:
            plt.close(fig)

    def test_worsening_47_to_37_rejected(self):
        f1, f2 = self._text_fig(4.7), self._text_fig(3.7)
        try:
            r1, r2 = qa.measure(f1), qa.measure(f2)
            delta = qa.delta_records(r1, r2)
            self.assertFalse(delta["eligible"], delta)
            self.assertEqual(len(delta["worsened"]), 1)
            self.assertEqual(delta["worsened"][0]["before"], 4.7)
            self.assertEqual(delta["worsened"][0]["after"], 3.7)
        finally:
            plt.close(f1)
            plt.close(f2)

    def test_improvement_is_eligible(self):
        f1, f2 = self._text_fig(3.7), self._text_fig(4.7)
        try:
            delta = qa.delta_records(qa.measure(f1), qa.measure(f2))
            self.assertTrue(delta["eligible"], delta)
        finally:
            plt.close(f1)
            plt.close(f2)

    def test_duplicate_same_key_never_overwrites(self):
        base = {"records": [
            {"rule": "TEXT_OVERLAP", "key": "overlap:A x B", "value": 5.0,
             "unit": "px2", "threshold": 4.0, "worse": "up",
             "severity": "blocking", "text": "t1"},
            {"rule": "TEXT_OVERLAP", "key": "overlap:A x B", "value": 9.0,
             "unit": "px2", "threshold": 4.0, "worse": "up",
             "severity": "blocking", "text": "t2"},
        ]}
        delta = qa.delta_records({"records": []}, base)
        self.assertFalse(delta["eligible"], delta)
        self.assertIn("overlap:A x B", delta["ambiguous"])

    def test_unmeasured_fails_closed(self):
        base = {"records": [
            {"rule": "UNMEASURED_GEOMETRY", "key": "g:x", "value": None,
             "unit": "none", "threshold": None, "worse": "up",
             "severity": "blocking", "text": "unmeasured"},
        ]}
        delta = qa.delta_records({"records": []}, base)
        self.assertFalse(delta["eligible"], delta)
        self.assertIn("g:x", delta["unmeasured"])

    def test_legacy_string_input_fails_closed(self):
        delta = qa.delta_records([], ["some string"])
        self.assertFalse(delta["eligible"], delta)

    def test_plain_list_of_records_accepted(self):
        f = self._text_fig(4.7)
        try:
            recs = qa.collect_records(f)
            self.assertTrue(recs)
            delta = qa.delta_records(recs, recs)
            self.assertTrue(delta["eligible"], delta)
        finally:
            plt.close(f)

    def test_spec_drift_rejected(self):
        f = self._text_fig(4.7)
        try:
            recs = qa.collect_records(f)
            other = [dict(r) for r in recs]
            other[0]["threshold"] = 999.0
            delta = qa.delta_records({"records": recs}, {"records": other})
            self.assertFalse(delta["eligible"], delta)
        finally:
            plt.close(f)


class ClipGeometryTest(unittest.TestCase):
    def tearDown(self):
        plt.close("all")

    def test_legend_inside_canvas_but_clipbox_smaller_reports_clip(self):
        from matplotlib.transforms import Bbox
        fig, ax = plt.subplots(figsize=(4, 3), dpi=100)
        ax.plot([0, 1], [0, 1], gid="fig.main.curve.x")
        fig.subplots_adjust(left=0.15, right=0.95, bottom=0.15, top=0.80)
        leg = ax.legend(["s"], loc="lower center", bbox_to_anchor=(0.5, 1.02), ncol=1)
        leg.set_gid("fig.main.legend")
        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()
        bb = leg.get_window_extent(renderer)
        tiny = Bbox.from_extents(bb.x0, bb.y0, bb.x0 + bb.width / 3, bb.y0 + bb.height / 3)
        leg.set_clip_box(tiny)
        leg.set_clip_on(True)
        recs = qa.collect_records(fig)
        clips = [r for r in recs if r["rule"] == "LEGEND_CLIP"]
        self.assertTrue(clips, recs)
        self.assertGreater(clips[0]["value"], 0.0)

    def test_hidden_text_not_measured(self):
        fig, ax = plt.subplots(figsize=(3, 2), dpi=100)
        ax.plot([0, 1], [0, 1], gid="fig.main.curve.x")
        t = ax.text(0.5, 0.5, "hidden", fontsize=3.0, gid="fig.main.hidden")
        t.set_visible(False)
        recs = qa.collect_records(fig)
        self.assertFalse([r for r in recs if r["key"] == "gid:fig.main.hidden"], recs)

    def test_line_out_of_axes_recorded(self):
        fig, ax = plt.subplots(figsize=(3, 2), dpi=100)
        ln, = ax.plot([0, 1], [100, 200], gid="fig.main.curve.x")
        ax.set_ylim(0, 1)
        recs = qa.collect_records(fig)
        self.assertTrue(any(r["rule"] == "OUT_OF_FRAME" and r["key"] == "gid:fig.main.curve.x"
                            for r in recs), recs)

    def test_figimage_overflow_recorded(self):
        fig = plt.figure(figsize=(1, 1), dpi=100)
        fig.figimage(np.zeros((10, 10)), xo=96, yo=40)
        recs = qa.collect_records(fig)
        self.assertTrue(any(r["rule"] == "OUT_OF_FRAME" for r in recs), recs)


if __name__ == "__main__":
    unittest.main()
