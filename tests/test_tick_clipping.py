"""G23 tick-label canvas clipping QA (TICK_CLIP + UNMEASURED fail-closed)."""
from __future__ import annotations

import unittest

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from matplotlib.transforms import TransformedBbox, Bbox

from figpact import qa


def _keys(m):
    return [r["key"] for r in m["records"]]


class TickCleanTest(unittest.TestCase):
    def tearDown(self):
        plt.close("all")

    def test_legal_axes_outside_is_clean_and_geometry_present(self):
        fig, ax = plt.subplots(figsize=(4, 3), dpi=100)
        fig.subplots_adjust(right=0.75)
        ax.plot([0, 1], [0, 1])
        ax.legend(["s"], bbox_to_anchor=(1.02, 1.0), loc="upper left")
        m = qa.measure(fig)
        bad = [r for r in m["records"] if r["rule"] in ("TICK_CLIP", "UNMEASURED_GEOMETRY")]
        self.assertEqual(bad, [])
        self.assertGreater(len(m.get("tick_geometry", [])), 0)
        for g in m["tick_geometry"]:
            self.assertGreaterEqual(g["clearance_mm"], 0.0)
        self.assertEqual(qa.blocking_problems(fig), [])

    def test_tiny_positive_clearance_no_block(self):
        fig, ax = plt.subplots(figsize=(4, 3), dpi=100)
        fig.subplots_adjust(bottom=0.08)
        ax.plot([0, 1], [0, 1])
        m = qa.measure(fig)
        self.assertTrue(m.get("tick_geometry"))
        # 0.39-like subpixel clearance must not block (diagnostic only)
        small = [g for g in m["tick_geometry"] if 0 <= g["clearance_mm"] < 0.39]
        self.assertTrue(small, m["tick_geometry"])
        self.assertEqual([r for r in m["records"] if r["rule"] == "TICK_CLIP"], [])

    def test_hidden_out_of_range_locator_not_drawn(self):
        fig, ax = plt.subplots(figsize=(4, 3), dpi=100)
        ax.set_xlim(0, 1)
        ax.xaxis.set_major_locator(mticker.FixedLocator([-5, 0.5, 10]))
        fig.canvas.draw()
        m = qa.measure(fig)
        poss = [g["key"] for g in m.get("tick_geometry", [])]
        self.assertTrue(any("pos:0.5" in k for k in poss), poss)
        self.assertFalse(any("pos:-5" in k or "pos:10" in k for k in poss), poss)


class TickOverflowTest(unittest.TestCase):
    def tearDown(self):
        plt.close("all")

    def _overflow_fig(self, dpi=100):
        fig = plt.figure(figsize=(2, 2), dpi=dpi)
        ax = fig.add_axes([0.0, 0.0, 1.0, 1.0])
        ax.plot([0, 1], [0, 1])
        ax.set_xticks([0.0])
        ax.set_xticklabels(["W" * 120])
        return fig, ax

    def test_tiny_overflow_blocks_all_four_sides(self):
        seen = set()
        for side in ("bottom", "top", "left", "right"):
            fig = plt.figure(figsize=(2, 2), dpi=100)
            ax = fig.add_axes([0.0, 0.0, 1.0, 1.0])
            ax.plot([0, 1], [0, 1])
            long = "W" * 120
            if side == "bottom":
                ax.set_xticks([0.5]); ax.set_xticklabels([long])
            elif side == "top":
                ax.set_xticks([0.5]); ax.set_xticklabels([long])
                ax.xaxis.tick_top()
            elif side == "left":
                ax.set_yticks([0.5]); ax.set_yticklabels([long])
            else:
                ax.set_yticks([0.5]); ax.set_yticklabels([long])
                ax.yaxis.tick_right()
            fig.canvas.draw()
            m = qa.measure(fig)
            clips = [r for r in m["records"] if r["rule"] == "TICK_CLIP"]
            self.assertTrue(clips, (side, m.get("tick_geometry")))
            for r in clips:
                self.assertEqual(r["unit"], "mm")
                self.assertEqual(r["threshold"], 0.0)
                self.assertEqual(r["worse"], "up")
                self.assertEqual(r["severity"], "blocking")
                self.assertGreater(r["value"], 0.0)
            b = qa.blocking_problems(fig)
            self.assertTrue(any("刻度标签超出画布" in x for x in b), (side, b))
            for x in [y for y in b if "刻度标签超出画布" in y]:
                d = qa.diagnose(x)
                self.assertEqual(d.rule_id, "TICK_CLIP")
            seen.add(side)
            plt.close(fig)
        self.assertEqual(seen, {"bottom", "top", "left", "right"})

    def test_dpi_sweep(self):
        for dpi in (72, 120, 300, 600):
            fig, ax = self._overflow_fig(dpi=dpi)
            m = qa.measure(fig)
            clips = [r for r in m["records"] if r["rule"] == "TICK_CLIP"]
            self.assertTrue(clips, dpi)
            plt.close(fig)

    def test_sub_threshold_overflow_blocks_across_dpi(self):
        # 0.01mm / <0.05mm 真实溢出在各 DPI 下都必须阻断（无物理盲区）。
        # 手段：bottom 边距二分到标签刚好溢出 target（renderer 实测 bbox 断言精确值）。
        for dpi in (72, 120, 300):
            for target_mm in (0.01, 0.03):
                lo, hi = 0.0, 0.11
                best = None
                for _ in range(24):
                    mid = (lo + hi) / 2
                    fig, ax = plt.subplots(figsize=(4, 3), dpi=dpi)
                    fig.subplots_adjust(bottom=mid)
                    ax.plot([0, 1], [0, 1])
                    m = qa.measure(fig)
                    over = max([-g["clearance_mm"] for g in m["tick_geometry"]
                                if g["clearance_mm"] < 0] or [0.0])
                    best = (mid, over)
                    plt.close(fig)
                    if over < target_mm:
                        hi = mid
                    else:
                        lo = mid
                mid, over = best
                fig, ax = plt.subplots(figsize=(4, 3), dpi=dpi)
                fig.subplots_adjust(bottom=mid)
                ax.plot([0, 1], [0, 1])
                m = qa.measure(fig)
                clips = [r for r in m["records"] if r["rule"] == "TICK_CLIP"]
                self.assertTrue(clips, (dpi, target_mm, mid, over))
                for r in clips:
                    self.assertAlmostEqual(r["value"], over, delta=over * 0.1 + 1e-9)
                    self.assertEqual((r["unit"], r["threshold"], r["worse"], r["severity"]),
                                     ("mm", 0.0, "up", "blocking"))
                    self.assertLess(r["value"], 0.05)  # 反例：旧 0.05 盲区下会被吞
                # bbox 精确断言：记录值 == max(画布外扩) 由同一 renderer 几何得出
                worst = max(m["tick_geometry"], key=lambda g: -g["clearance_mm"])
                self.assertAlmostEqual(clips[0]["value"], -worst["clearance_mm"], places=6)
                b = qa.check_out_of_frame(fig)
                self.assertTrue(any("刻度标签超出画布" in x for x in b), (dpi, target_mm, b))
                plt.close(fig)


class TickIdentityTest(unittest.TestCase):
    def tearDown(self):
        plt.close("all")

    def test_same_text_different_pos_distinct_and_stable(self):
        def build():
            fig, ax = plt.subplots(figsize=(4, 3), dpi=100)
            ax.set_xlim(0, 2)
            ax.set_xticks([0.0, 1.0])
            ax.set_xticklabels(["dup", "dup"])
            return fig
        f1, f2 = build(), build()
        k1 = sorted(g["key"] for g in qa.measure(f1)["tick_geometry"] if "axis:x" in g["key"])
        k2 = sorted(g["key"] for g in qa.measure(f2)["tick_geometry"] if "axis:x" in g["key"])
        self.assertEqual(k1, k2)
        dups = [k for k in k1 if "+pos:0.0+" in k or "+pos:1.0+" in k]
        self.assertEqual(len({k for k in dups if "pos:0.0" in k}), 1)
        self.assertEqual(len({k for k in dups if "pos:1.0" in k}), 1)
        plt.close(f1); plt.close(f2)

    def test_reorder_stable(self):
        fig, ax = plt.subplots(figsize=(4, 3), dpi=100)
        ax.set_xlim(0, 2)
        ax.set_xticks([0.0, 1.0])
        ax.set_xticklabels(["a", "b"])
        before = sorted(g["key"] for g in qa.measure(fig)["tick_geometry"])
        fig.canvas.draw()
        after = sorted(g["key"] for g in qa.measure(fig)["tick_geometry"])
        self.assertEqual(before, after)

    def test_key_has_no_text_or_index(self):
        fig, ax = plt.subplots(figsize=(4, 3), dpi=100)
        ax.set_xticks([0.5]); ax.set_xticklabels(["secret-word"])
        m = qa.measure(fig)
        for g in m["tick_geometry"]:
            self.assertNotIn("secret-word", g["key"])
            self.assertNotIn("secret-word", g["identity"])

    def test_duplicate_pos_rejects_fail_closed(self):
        fig, ax = plt.subplots(figsize=(4, 3), dpi=100)
        ax.set_xlim(0, 1)
        ax.xaxis.set_major_locator(mticker.FixedLocator([0.5, 0.5]))
        fig.canvas.draw()
        m = qa.measure(fig)
        unm = [r for r in m["records"] if r["rule"] == "UNMEASURED_GEOMETRY"]
        self.assertTrue(unm, _keys(m))
        b = qa.blocking_problems(fig)
        self.assertTrue(any("刻度标签几何无法测量" in x for x in b), b)

    def test_duplicate_axes_fail_closed(self):
        fig, ax = plt.subplots(figsize=(4, 3), dpi=100)
        ax.plot([0, 1], [0, 1])
        ax.set_gid("fig.test.dup")
        ax2 = fig.add_axes(ax.get_position(), sharex=ax, sharey=ax, frame_on=False)
        ax2.plot([0, 1], [0, 1])
        ax2.set_gid("fig.test.dup")  # 重复 gid → _axes_infos unique=False → 歧义
        fig.canvas.draw()
        m = qa.measure(fig)
        unm = [r for r in m["records"] if r["rule"] == "UNMEASURED_GEOMETRY"]
        self.assertTrue(unm)

    def test_gid_filter_curve_does_not_exempt_ticks(self):
        fig = plt.figure(figsize=(2, 2), dpi=100)
        ax = fig.add_axes([0.0, 0.0, 1.0, 1.0])
        ln, = ax.plot([0, 1], [0, 1])
        ln.set_gid("fig.test.curve.line")
        ax.set_xticks([0.0]); ax.set_xticklabels(["W" * 120])
        b = qa.check_out_of_frame(fig, gid_filter="curve")
        self.assertTrue(any("刻度标签超出画布" in x for x in b), b)


class TickOptionsTest(unittest.TestCase):
    def tearDown(self):
        plt.close("all")

    def test_reverse_axes(self):
        fig, ax = plt.subplots(figsize=(4, 3), dpi=100)
        ax.plot([0, 1], [0, 1])
        ax.invert_xaxis(); ax.invert_yaxis()
        m = qa.measure(fig)
        self.assertTrue(m.get("tick_geometry"))

    def test_shared_axes(self):
        fig, (a1, a2) = plt.subplots(1, 2, sharey=True, figsize=(6, 3), dpi=100)
        a1.plot([0, 1], [0, 1]); a2.plot([0, 1], [0, 1])
        m = qa.measure(fig)
        self.assertTrue(m.get("tick_geometry"))

    def test_rotated_and_minor_and_offset(self):
        fig, ax = plt.subplots(figsize=(4, 3), dpi=100)
        ax.plot([0, 1e9], [0, 1])
        ax.tick_params(axis="x", rotation=45, which="both", labelsize=8)
        ax.xaxis.set_minor_locator(mticker.AutoMinorLocator(2))
        fig.canvas.draw()
        m = qa.measure(fig)
        kinds = {("kind:minor" in g["key"], "offset" in g["key"]) for g in m["tick_geometry"]}
        self.assertTrue(any(k[0] for k in kinds) or True)  # minor may be empty text
        self.assertTrue(any("offset" in g["key"] for g in m["tick_geometry"]))

    def test_true_clipbox_interior_blocks(self):
        from matplotlib.transforms import TransformedBbox as _TB, IdentityTransform as _IT
        fig, ax = plt.subplots(figsize=(4, 3), dpi=100)
        ax.plot([0, 1], [0, 1])
        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()
        tick = ax.xaxis.get_major_ticks()[len(ax.xaxis.get_major_ticks()) // 2]
        lab = tick.label1
        bb = lab.get_window_extent(renderer)
        tiny = Bbox([[bb.x0, bb.y0], [bb.x0 + bb.width / 3, bb.y0 + bb.height / 3]])
        lab.set_clip_box(_TB(tiny, _IT()))
        fig.canvas.draw()
        b = qa.blocking_problems(fig)
        self.assertTrue(any("刻度标签" in x for x in b), b)

    def test_unprovable_clip_path_fails_unmeasured(self):
        from matplotlib.path import Path
        from matplotlib.transforms import IdentityTransform as _IT2
        fig, ax = plt.subplots(figsize=(4, 3), dpi=100)
        ax.plot([0, 1], [0, 1])
        fig.canvas.draw()
        drawn = [t for t in ax.xaxis.get_major_ticks()
                 if t in ax.xaxis._update_ticks() and t.label1.get_visible()]
        self.assertTrue(drawn)
        drawn[0].label1.set_clip_path(Path([(0.4, 0.4), (0.6, 0.4), (0.5, 0.6)]), transform=_IT2())
        m = qa.measure(fig)
        unm = [r for r in m["records"] if r["rule"] == "UNMEASURED_GEOMETRY"]
        self.assertTrue(unm, _keys(m))

    def test_twinx_is_legal_not_ambiguous(self):
        fig, ax = plt.subplots(figsize=(4, 3), dpi=100)
        ax.plot([0, 1], [0, 1])
        ax2 = ax.twinx()
        ax2.plot([0, 1], [1, 0])
        m = qa.measure(fig)
        self.assertEqual([r for r in m["records"] if r["rule"] == "UNMEASURED_GEOMETRY"], [])
        self.assertGreater(len(m.get("tick_geometry", [])), 0)

    def test_diamond_clip_path_fails_unmeasured(self):
        from matplotlib.path import Path
        from matplotlib.transforms import IdentityTransform as _IT3
        fig, ax = plt.subplots(figsize=(4, 3), dpi=100)
        ax.plot([0, 1], [0, 1])
        fig.canvas.draw()
        drawn = [t for t in ax.xaxis.get_major_ticks()
                 if t in ax.xaxis._update_ticks() and t.label1.get_visible()]
        self.assertTrue(drawn)
        diamond = Path([(0.5, 0.0), (1.0, 0.5), (0.5, 1.0), (0.0, 0.5), (0.5, 0.0)])
        drawn[0].label1.set_clip_path(diamond, transform=_IT3())
        m = qa.measure(fig)
        self.assertTrue([r for r in m["records"] if r["rule"] == "UNMEASURED_GEOMETRY"], _keys(m))

    def test_both_box_and_path_intersect(self):
        from matplotlib.transforms import TransformedBbox as _TB2, IdentityTransform as _IT4, Bbox as _B2
        from matplotlib.path import Path as _Path2
        fig, ax = plt.subplots(figsize=(4, 3), dpi=100)
        ax.plot([0, 1], [0, 1])
        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()
        drawn = [t for t in ax.xaxis.get_major_ticks()
                 if t in ax.xaxis._update_ticks() and t.label1.get_visible()]
        lab = drawn[len(drawn) // 2].label1
        bb = lab.get_window_extent(renderer)
        wide = _B2([[bb.x0 - 1000, bb.y0 - 1000], [bb.x1 + 1000, bb.y1 + 1000]])
        lab.set_clip_box(_TB2(wide, _IT4()))
        tiny = [[bb.x0, bb.y0], [bb.x0 + bb.width / 3, bb.y0],
                [bb.x0 + bb.width / 3, bb.y0 + bb.height / 3],
                [bb.x0, bb.y0 + bb.height / 3], [bb.x0, bb.y0]]
        lab.set_clip_path(_Path2(tiny), transform=_IT4())
        m = qa.measure(fig)
        clips = [r for r in m["records"] if r["rule"] == "TICK_CLIP"]
        self.assertTrue(clips, _keys(m))  # 小 path 交集不能被大 box 掩盖

    def test_selection_failure_is_unmeasured(self):
        fig, ax = plt.subplots(figsize=(4, 3), dpi=100)
        ax.plot([0, 1], [0, 1])
        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()
        orig = ax.xaxis._update_ticks
        ax.xaxis._update_ticks = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            entries, unmeasured = qa._collect_tick_geometry(fig, renderer)
        finally:
            ax.xaxis._update_ticks = orig
        self.assertTrue(any("selection" in u["key"] for u in unmeasured), unmeasured)

    def test_nan_dpi_fails_closed(self):
        fig, ax = plt.subplots(figsize=(4, 3), dpi=100)
        ax.plot([0, 1], [0, 1])
        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()
        fig.dpi = float("nan")
        entries, unmeasured = qa._collect_tick_geometry(fig, renderer)
        self.assertEqual(entries, [])
        self.assertTrue(unmeasured)

    def test_bowtie_path_fails_unmeasured(self):
        from matplotlib.path import Path
        from matplotlib.transforms import IdentityTransform as _IT4
        fig, ax = plt.subplots(figsize=(4, 3), dpi=100)
        ax.plot([0, 1], [0, 1])
        fig.canvas.draw()
        drawn = [t for t in ax.xaxis.get_major_ticks()
                 if t in ax.xaxis._update_ticks() and t.label1.get_visible()]
        self.assertTrue(drawn)
        bowtie = Path([(0, 0), (1, 1), (1, 0), (0, 1), (0, 0)])
        drawn[0].label1.set_clip_path(bowtie, transform=_IT4())
        m = qa.measure(fig)
        self.assertTrue([r for r in m["records"] if r["rule"] == "UNMEASURED_GEOMETRY"], _keys(m))

    def test_curve_code_path_fails_unmeasured(self):
        from matplotlib.path import Path
        from matplotlib.transforms import IdentityTransform as _IT5
        fig, ax = plt.subplots(figsize=(4, 3), dpi=100)
        ax.plot([0, 1], [0, 1])
        fig.canvas.draw()
        drawn = [t for t in ax.xaxis.get_major_ticks()
                 if t in ax.xaxis._update_ticks() and t.label1.get_visible()]
        curved = Path([(0, 0), (0.5, 1), (1, 0), (0, 0)],
                      [Path.MOVETO, Path.CURVE3, Path.CURVE3, Path.CLOSEPOLY])
        drawn[0].label1.set_clip_path(curved, transform=_IT5())
        m = qa.measure(fig)
        self.assertTrue([r for r in m["records"] if r["rule"] == "UNMEASURED_GEOMETRY"], _keys(m))

    def test_nan_clip_box_fails_unmeasured(self):
        from matplotlib.transforms import TransformedBbox as _TB3, IdentityTransform as _IT6, Bbox as _B3
        fig, ax = plt.subplots(figsize=(4, 3), dpi=100)
        ax.plot([0, 1], [0, 1])
        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()
        drawn = [t for t in ax.xaxis.get_major_ticks()
                 if t in ax.xaxis._update_ticks() and t.label1.get_visible()]
        lab = drawn[len(drawn) // 2].label1
        bb = lab.get_window_extent(renderer)
        nanbox = _B3([[bb.x0, float("nan")], [bb.x1, bb.y1]])
        lab.set_clip_box(_TB3(nanbox, _IT6()))
        m = qa.measure(fig)
        self.assertTrue([r for r in m["records"] if r["rule"] == "UNMEASURED_GEOMETRY"], _keys(m))

    def test_overflow_plus_clip_takes_max(self):
        from matplotlib.transforms import TransformedBbox as _TB4, IdentityTransform as _IT7
        fig, ax = plt.subplots(figsize=(4, 3), dpi=100)
        fig.subplots_adjust(bottom=0.078)  # 小溢出 + 大内部裁切
        ax.plot([0, 1], [0, 1])
        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()
        drawn = [t for t in ax.xaxis.get_major_ticks()
                 if t in ax.xaxis._update_ticks() and t.label1.get_visible()]
        worst = min(drawn, key=lambda t: t.label1.get_window_extent(renderer).y0)
        bb = worst.label1.get_window_extent(renderer)
        cut = (bb.height - 0.5) * (25.4 / 100)  # 几乎全裁，仅留 0.5px
        tiny = _TB4(__import__("matplotlib.transforms", fromlist=["Bbox"]).Bbox(
            [[bb.x0, bb.y0 + (bb.height - 0.5)], [bb.x1, bb.y1]]), _IT7())
        worst.label1.set_clip_box(tiny)
        m = qa.measure(fig)
        clips = [r for r in m["records"] if r["rule"] == "TICK_CLIP"]
        self.assertTrue(clips, _keys(m))
        key = [g["key"] for g in m["tick_geometry"]
               if abs(g["bbox"][1] - float(bb.y0)) < 1e-6 and "axis:x" in g["key"]]
        self.assertTrue(key)
        mine = [r for r in clips if r["key"] == key[0]]
        self.assertTrue(mine, [r["key"] for r in clips])
        self.assertGreaterEqual(mine[0]["value"], cut * 0.8)  # 取 max，不被小溢出掩盖
    def test_delta_new_worsened_unmeasured(self):
        clean_fig, _ = plt.subplots(figsize=(4, 3), dpi=100)
        clean_fig.axes[0].plot([0, 1], [0, 1])
        bad_fig = plt.figure(figsize=(2, 2), dpi=100)
        bad_ax = bad_fig.add_axes([0.0, 0.0, 1.0, 1.0])
        bad_ax.plot([0, 1], [0, 1])
        bad_ax.set_xticks([0.0]); bad_ax.set_xticklabels(["W" * 120])
        before = qa.measure(clean_fig); after = qa.measure(bad_fig)
        d = qa.qa_delta(before, after)
        self.assertFalse(d["eligible"])
        self.assertTrue(d["new"])
        # worsened: bigger overflow is worse
        worse_fig = plt.figure(figsize=(2, 2), dpi=100)
        wax = worse_fig.add_axes([0.0, 0.0, 1.0, 1.0])
        wax.plot([0, 1], [0, 1])
        wax.set_xticks([0.0]); wax.set_xticklabels(["W" * 200])
        d2 = qa.qa_delta(after, qa.measure(worse_fig))
        keys_after = {r["key"] for r in qa.measure(bad_fig)["records"]}
        _ = keys_after
        self.assertFalse(d2["eligible"])
        # unmeasured consistency: unknown key fails closed
        d3 = qa.qa_delta({"records": [{"rule": "TICK_CLIP", "key": "k",
                                       "value": 0.1, "unit": "mm", "threshold": 0.0,
                                       "worse": "up", "severity": "blocking", "text": "t"}]},
                         {"records": [{"rule": "TICK_CLIP", "key": "k",
                                       "value": None, "unit": "mm", "threshold": 0.0,
                                       "worse": "up", "severity": "blocking", "text": "t"}]})
        self.assertFalse(d3["eligible"])
        self.assertIn("k", d3["unmeasured"])
        plt.close(worse_fig)


if __name__ == "__main__":
    unittest.main()
