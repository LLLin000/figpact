"""Scientific windows translate in millimetres without distorting local geometry."""
import unittest

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from figpact.transform import apply_display_shift


class DisplayShiftTest(unittest.TestCase):
    def test_blended_window_keeps_shape_and_data_during_translation_and_return(self):
        fig, ax = plt.subplots(figsize=(100 / 25.4, 60 / 25.4), dpi=254)
        try:
            ax.set_xlim(0, 10)
            ax.set_ylim(0, 10)
            window = ax.axvspan(2, 4, ymin=0.2, ymax=0.7)
            fig.canvas.draw()
            original = window.get_window_extent(fig.canvas.get_renderer()).extents.copy()
            scientific_bounds = window.get_bbox().bounds
            apply_display_shift(window, dx_mm=0.7, dy_mm=2.5)
            fig.canvas.draw()
            moved = window.get_window_extent(fig.canvas.get_renderer()).extents
            np.testing.assert_allclose((moved - original) * 25.4 / fig.dpi,
                                       [0.7, 2.5, 0.7, 2.5], atol=1e-10, rtol=0)
            self.assertEqual(window.get_bbox().bounds, scientific_bounds)
            apply_display_shift(window, dx_mm=-0.7, dy_mm=-2.5)
            fig.canvas.draw()
            np.testing.assert_allclose(window.get_window_extent(fig.canvas.get_renderer()).extents,
                                       original, atol=1e-9, rtol=0)
            self.assertEqual(window.get_bbox().bounds, scientific_bounds)
        finally:
            plt.close(fig)
