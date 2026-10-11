"""Real FTIR preview hook must retain scope isolation and figure-image QA."""
import unittest
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from figpact.session import load_module

ROOT = Path(__file__).resolve().parents[1]


class FtirPreviewQaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with matplotlib.rc_context():
            cls.plot = load_module(ROOT / "examples/ftir/plot_ftir.py",
                                   ROOT / "examples/ftir/ftir.yaml")

    def figure(self):
        fig, axes = plt.subplots(2, figsize=(2, 2), dpi=100)
        self.addCleanup(plt.close, fig)
        for ax in axes:
            ax.set_xlim(0, 1)
            ax.set_ylim(0, 1)
        return fig, axes

    def test_both_compare_scopes_report_outside_figure_images(self):
        fig, _axes = self.figure()
        image = fig.figimage(np.ones((20, 20)), xo=195, yo=20)
        image.set_gid("scope-image-overflow")
        for scope in ("compare_raw", "compare_processed"):
            with self.subTest(scope=scope):
                problems = self.plot.preview_qa(fig, scope)
                self.assertTrue(any("scope-image-overflow" in item for item in problems),
                                "A scope preview must not hide a clipped figure-level image")

    def test_compare_preview_does_not_report_sibling_curve_overflow(self):
        fig, axes = self.figure()
        line, = axes[0].plot([0.5, 0.5, 0.5], [-1, 0.5, 2])
        line.set_gid("raw-only-overflow")
        raw = self.plot.preview_qa(fig, "compare_raw")
        processed = self.plot.preview_qa(fig, "compare_processed")
        self.assertTrue(any("raw-only-overflow" in item for item in raw))
        self.assertFalse(any("raw-only-overflow" in item for item in processed))
