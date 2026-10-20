"""External G25-S2 science capture: real pie-shadow and Sankey originals.

Runs the reviewed upstream originals unchanged (``tools/g25s/compatible/pie.py``
figs 5/7, ``tools/g25s/compatible/sankey.py`` figs 0-2); no unseen/model claims.
"""
import io
import runpy
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from figpact import science
from figpact.inspector import capture_figure
from figpact.registry import GidRegistry

ROOT = Path(__file__).resolve().parents[1]


def original_figures(relative):
    plt.close('all')
    with matplotlib.rc_context(), patch.object(plt, 'show'):
        runpy.run_path(str(ROOT / relative), run_name='__main__')
    return [plt.figure(n) for n in plt.get_fignums()]


def keep_only(figures, index):
    for i, fig in enumerate(figures):
        if i != index:
            plt.close(fig)
    return figures[index]


class ExternalScienceTest(unittest.TestCase):
    def tearDown(self):
        plt.close('all')

    def test_pie_shadow_first_draw_is_not_a_science_change(self):
        for index in (5, 7):
            with self.subTest(figure=index):
                figures = original_figures('tools/g25s/compatible/pie.py')
                fig = keep_only(figures, index)
                kinds = [type(p).__name__ for p in fig.axes[0].patches]
                self.assertIn('Shadow', kinds,
                              'original must really carry Shadow patches or this proves nothing')
                reg = GidRegistry(scope=f'fig{index}')
                with redirect_stderr(io.StringIO()):
                    bundle = capture_figure(fig, reg, scope=f'fig{index}')
                again = capture_figure(fig, GidRegistry(scope=f'fig{index}'),
                                       scope=f'fig{index}')
                self.assertEqual(bundle['frame_revision'], again['frame_revision'])

    def test_pie_shadow_stable_across_draw_and_real_changes_rejected(self):
        figures = original_figures('tools/g25s/compatible/pie.py')
        fig = keep_only(figures, 5)
        reg = GidRegistry(scope='fig5')
        baseline = science.capture_science(fig, reg)
        with redirect_stderr(io.StringIO()):
            bundle = capture_figure(fig, reg, scope='fig5')
        self.assertEqual(science.compare_science(
            baseline, science.capture_science(fig, reg)), [],
            'Shadow pie must be draw-stable: first draw changes no protected payload')
        wedge_keys = [key for key, record in baseline['objects'].items()
                      if record.get('kind') == 'Wedge']
        self.assertTrue(wedge_keys, 'original wedges must be protected payload')
        wedge = next(p for p in fig.axes[0].patches
                     if type(p).__name__ == 'Wedge')
        wedge.set_theta2(wedge.theta2 + 10.0)
        changed = science.compare_science(baseline, science.capture_science(fig, reg))
        self.assertTrue(changed)
        self.assertEqual(changed[0]['rule_id'], 'SCIENCE_CHANGED')
        self.assertTrue(any(key in changed[0]['object_ids'] for key in wedge_keys),
                        'a real wedge change must name a wedge object')
        wedge.set_theta2(wedge.theta2 - 10.0)
        self.assertEqual(science.compare_science(
            baseline, science.capture_science(fig, reg)), [])
        shadow = next(p for p in fig.axes[0].patches
                      if type(p).__name__ == 'Shadow')
        shadow._ox = shadow._ox - 0.5
        changed = science.compare_science(baseline, science.capture_science(fig, reg))
        self.assertTrue(changed)
        self.assertEqual(changed[0]['rule_id'], 'SCIENCE_CHANGED')

    def test_pie_shadow_stable_across_dpi(self):
        figures = original_figures('tools/g25s/compatible/pie.py')
        fig = keep_only(figures, 5)
        reg = GidRegistry(scope='fig5')
        baseline = science.capture_science(fig, reg)
        previous_dpi = fig.dpi
        try:
            fig.set_dpi(200.0)
            moved = science.capture_science(fig, reg)
        finally:
            fig.set_dpi(previous_dpi)
        self.assertEqual(science.compare_science(baseline, moved), [],
                         'Shadow offset is renderer-side points: dpi must not be science')

    def test_sankey_aspect_settlement_is_not_a_science_change(self):
        for index in (0, 1, 2):
            with self.subTest(figure=index):
                figures = original_figures('tools/g25s/compatible/sankey.py')
                fig = keep_only(figures, index)
                self.assertEqual(fig.axes[0].get_aspect(), 1.0)
                self.assertEqual(fig.axes[0].get_adjustable(), 'datalim')
                reg = GidRegistry(scope=f'fig{index}')
                with redirect_stderr(io.StringIO()):
                    bundle = capture_figure(fig, reg, scope=f'fig{index}')
                again = capture_figure(fig, GidRegistry(scope=f'fig{index}'),
                                       scope=f'fig{index}')
                self.assertEqual(bundle['frame_revision'], again['frame_revision'])

    def test_sankey_view_and_patch_mutations_still_rejected(self):
        figures = original_figures('tools/g25s/compatible/sankey.py')
        fig = keep_only(figures, 0)
        reg = GidRegistry(scope='fig0')
        with redirect_stderr(io.StringIO()):
            capture_figure(fig, reg, scope='fig0')
        baseline = science.capture_science(fig, reg)
        patch = next(p for p in fig.axes[0].patches)
        xlim = fig.axes[0].get_xlim()
        fig.axes[0].set_xlim(xlim[0] - 1.0, xlim[1])
        changed = science.compare_science(
            baseline, science.capture_science(fig, reg))
        self.assertTrue(changed)
        self.assertEqual(changed[0]['rule_id'], 'SCIENCE_CHANGED')
        self.assertIn('panel.0:view', changed[0]['object_ids'])
        baseline = science.capture_science(fig, reg)
        patch.get_path().vertices[1, 0] += 1.0
        changed = science.compare_science(baseline, science.capture_science(fig, reg))
        self.assertEqual(changed[0]['rule_id'], 'SCIENCE_CHANGED')
        self.assertIn('panel.0.unregistered.patch.0', changed[0]['object_ids'])

    def test_draw_time_mutation_is_still_refused(self):
        from figpact.inspector import InspectorError
        fig, ax = plt.subplots()
        wedges, _ = ax.pie([15, 30, 45, 10], shadow=True)
        reg = GidRegistry(scope='m')

        def mutate(event):
            wedges[0].set_theta2(wedges[0].theta2 + 20.0)

        before_theta = wedges[0].theta2
        fig.canvas.mpl_connect('draw_event', mutate)
        with self.assertRaises(InspectorError):
            capture_figure(fig, reg, scope='m')
        self.assertNotEqual(wedges[0].theta2, before_theta,
                            'callback must really mutate or this is not a real failure')

    def test_settlement_time_data_mutation_is_refused_not_baselined(self):
        # A hostile xlim/ylim_changed callback that only fires on the settle-time
        # set_*bound path (disarmed during read-time autoscale) must trip the
        # view-only settle diff, not get laundered into the baseline.
        from figpact.inspector import InspectorError
        fig, ax = plt.subplots()
        ax.set_aspect(1.0, adjustable='datalim')
        line, = ax.plot([0.0, 1.0], [0.0, 1.0])
        reg = GidRegistry(scope='m')
        armed = {'armed': False}

        def mutate(axes):
            if armed['armed'] and list(line.get_ydata()) != [0.0, 99.0]:
                line.set_ydata([0.0, 99.0])

        axes = fig.axes[0]
        axes.callbacks.connect('xlim_changed', mutate)
        axes.callbacks.connect('ylim_changed', mutate)
        baseline = science.capture_science(fig, reg)
        armed['armed'] = True
        with self.assertRaises(InspectorError) as caught:
            capture_figure(fig, reg, scope='m')
        self.assertIn('视图窗口之外', str(caught.exception))
        self.assertEqual(list(line.get_ydata()), [0.0, 99.0],
                         'callback must really mutate or this is not a real failure')
        self.assertEqual(science.compare_science(
            baseline, science.capture_science(fig, reg))[0]['rule_id'],
            'SCIENCE_CHANGED')

    def test_custom_aspect_draw_cannot_baseline_a_data_mutation(self):
        import matplotlib.axes as mpl_axes
        from figpact.inspector import InspectorError
        native = mpl_axes.Axes.apply_aspect

        def mutate_and_apply(axes, position=None):
            if axes.lines:
                line = axes.lines[0]
                line.set_ydata([float(value) + 1.0 for value in line.get_ydata()])
            return native(axes, position)

        class CustomAxes(mpl_axes.Axes):
            apply_aspect = mutate_and_apply

        for subclass in (False, True):
            with self.subTest(subclass=subclass):
                fig = plt.figure()
                ax = fig.add_subplot(1, 1, 1, axes_class=CustomAxes if subclass else mpl_axes.Axes)
                ax.plot([0.0, 1.0], [0.0, 1.0])
                if not subclass:
                    ax.apply_aspect = mutate_and_apply.__get__(ax, type(ax))
                with self.assertRaises(InspectorError):
                    capture_figure(fig, GidRegistry(scope='m'), scope='m')

    def test_failed_settlement_raises_with_cause(self):
        # Native apply_aspect can fail (shared x+y + equal/datalim): the failure
        # must surface as InspectorError with the RuntimeError cause, not pass.
        from figpact.inspector import InspectorError
        fig, (first, _) = plt.subplots(1, 2, sharex=True, sharey=True)
        first.plot([0.0, 1.0], [0.0, 1.0])
        first.set_aspect(1.0, adjustable='datalim')
        with self.assertRaises(InspectorError) as caught:
            capture_figure(fig, GidRegistry(scope='m'), scope='m')
        self.assertIsInstance(caught.exception.__cause__, RuntimeError)


if __name__ == '__main__':
    unittest.main()
