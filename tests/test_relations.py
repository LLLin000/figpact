import unittest
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from figpact.relations import measure_relation, set_relation_target, remaining_space


class PhysicalRelationsTest(unittest.TestCase):
    def tearDown(self):
        plt.close('all')

    def test_one_gap_changes_without_scaling_or_changing_other_gap(self):
        fig, ax = plt.subplots(figsize=(48/25.4, 48/25.4), dpi=123)
        ax.set_ylim(0, 10)
        curves = [ax.plot([0, 1, 2], np.array([0, .2, 0])+y)[0] for y in (1, 3, 6)]
        fig.canvas.draw()
        a, b, c = curves
        original_data = [line.get_ydata().copy() for line in curves]
        original_heights = [line.get_window_extent().height for line in curves]
        other_gap = measure_relation('vertical_clearance', b, c)
        set_relation_target(kind='vertical_clearance', object_a=a, object_b=b,
                            target_mm=1.5, move=[b, c])
        self.assertAlmostEqual(measure_relation('vertical_clearance', a, b), 1.5, places=9)
        self.assertAlmostEqual(measure_relation('vertical_clearance', b, c), other_gap, places=9)
        set_relation_target(kind='vertical_clearance', object_a=a, object_b=b,
                            target_mm=50, move=[b, c])
        self.assertAlmostEqual(measure_relation('vertical_clearance', a, b), 50, places=9)
        self.assertGreater(remaining_space(fig, curves)[0]['overflow_mm'], 0)
        for line, data, height in zip(curves, original_data, original_heights):
            np.testing.assert_array_equal(line.get_ydata(), data)
            self.assertAlmostEqual(line.get_window_extent().height, height, places=9)

    def test_pitch_and_invalid_requests_leave_objects_unchanged(self):
        fig, ax = plt.subplots(figsize=(2, 2), dpi=101)
        a, b = ax.axhline(0), ax.axhline(2)
        ax.set_ylim(-1, 10)
        fig.canvas.draw()
        set_relation_target(kind='baseline_pitch', object_a=a, object_b=b,
                            target_mm=1.5, move=[b])
        self.assertAlmostEqual(measure_relation('baseline_pitch', a, b), 1.5, places=9)
        position = b.get_transform().transform(b.get_xydata()).copy()
        for invalid in (True, -1, float('nan'), float('inf'), '1.5'):
            with self.assertRaises(ValueError):
                set_relation_target(kind='baseline_pitch', object_a=a, object_b=b,
                                    target_mm=invalid, move=[b])
        other_fig, other_ax = plt.subplots()
        foreign = other_ax.axhline(0)
        with self.assertRaises(ValueError):
            set_relation_target(kind='baseline_pitch', object_a=a, object_b=b,
                                target_mm=3, move=[b, foreign])
        np.testing.assert_array_equal(b.get_transform().transform(b.get_xydata()), position)


if __name__ == '__main__':
    unittest.main()
