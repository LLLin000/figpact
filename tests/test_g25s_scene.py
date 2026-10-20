"""External G25-S DEVELOPMENT fixtures; no unseen/model accuracy claims."""
import json
from pathlib import Path
import runpy
import unittest
from unittest.mock import patch

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from figpact import scene
from figpact.inspector import InspectorError, capture_figure
from figpact.registry import GidRegistry

ROOT = Path(__file__).resolve().parents[1]


class ExternalSceneTest(unittest.TestCase):
    def tearDown(self):
        plt.close('all')

    def originals(self, relative):
        with matplotlib.rc_context(), patch.object(plt, 'show'):
            runpy.run_path(str(ROOT / relative), run_name='__main__')
        return [plt.figure(n) for n in plt.get_fignums()]

    def test_contour_collection_is_not_text_and_real_labels_are_retained(self):
        figures = self.originals('tools/g25s/gallery/raw/contour_contour_demo.py')
        for fig in figures:
            with self.subTest(figure=fig.number):
                snap = scene.snapshot(fig, GidRegistry(scope='main'), scope='main')
                contours = [n for n in snap['nodes'] if n['artist_type'] == 'QuadContourSet']
                self.assertTrue(contours, 'original contour objects must not disappear')
                for node in contours:
                    self.assertEqual(node['type'], 'collection')
                    self.assertFalse(node['is_text'])
                    self.assertNotIn('text', node)
                    self.assertFalse(node['editable'])
                visible_labels = [t.get_text() for ax in fig.axes for t in ax.texts if t.get_visible()]
                scene_labels = [n['text'] for n in snap['nodes'] if n.get('is_text')]
                for label in visible_labels:
                    self.assertIn(label, scene_labels)
                json.dumps(snap, allow_nan=False)

    def test_nonfinite_log_geometry_is_reported_unmeasurable_not_serialized(self):
        figures = self.originals('tools/g25s/gallery/raw/log_log_demo.py')
        fig = figures[2]
        snap = scene.snapshot(fig, GidRegistry(scope='main'), scope='main')
        json.dumps(snap, allow_nan=False)
        invalid = [n for n in snap['nodes'] if n.get('geometry_reason')]
        self.assertTrue(invalid, 'nonfinite transformed geometry must not be silently omitted')
        for node in invalid:
            self.assertFalse(node['measured'])
            self.assertIsNone(node['bounds_mm'])
            self.assertIsNone(node['anchors'])
            self.assertTrue(any(d['kind'] == 'UNMEASURED_GEOMETRY'
                                and d['severity'] == 'blocking' and node['id'] in d['ids']
                                for d in snap['diagnostics']))
        with self.assertRaises(InspectorError):
            capture_figure(fig, GidRegistry(scope='main'), scope='main')

    def test_nonfinite_text_extent_is_not_promoted_to_measured_anchors(self):
        fig, ax = plt.subplots()
        label = ax.text(np.nan, .5, 'unknown position')
        reg = GidRegistry(scope='main')
        reg.register(label, 'main.label')
        snap = scene.snapshot(fig, reg, scope='main')
        node = next(n for n in snap['nodes'] if n['id'] == 'main.label')
        self.assertFalse(node['measured'])
        self.assertIsNone(node['anchors'])
        json.dumps(snap, allow_nan=False)
        self.assertTrue(any(d['severity'] == 'blocking' and 'main.label' in d['ids']
                            for d in snap['diagnostics']))

    def test_colorbar_empty_dividers_are_known_empty_not_unknown_geometry(self):
        fig, ax = plt.subplots()
        colorbar = fig.colorbar(ax.imshow(np.arange(9).reshape(3, 3)))
        reg = GidRegistry(scope='main')
        reg.register(colorbar.dividers, 'main.dividers')
        snap = scene.snapshot(fig, reg, scope='main')
        node = next(n for n in snap['nodes'] if n['id'] == 'main.dividers')
        self.assertTrue(node['measured'])
        self.assertEqual(node['collection_segments'], 0)
        self.assertEqual(node['polylines_mm'], [])
        self.assertIsNone(node['bounds_mm'])
        self.assertIsNone(node['anchors'])
        self.assertFalse(node['editable'])
        self.assertFalse(any(d['severity'] == 'blocking' for d in snap['diagnostics']))

    def test_unknown_empty_collection_is_still_unmeasurable(self):
        from matplotlib.collections import LineCollection
        class UnknownEmptyCollection(LineCollection):
            pass
        fig, ax = plt.subplots()
        unknown = UnknownEmptyCollection([])
        ax.add_collection(unknown)
        reg = GidRegistry(scope='main')
        reg.register(unknown, 'main.unknown')
        snap = scene.snapshot(fig, reg, scope='main')
        node = next(n for n in snap['nodes'] if n['id'] == 'main.unknown')
        self.assertFalse(node['measured'])
        self.assertTrue(any(d['severity'] == 'blocking' and 'main.unknown' in d['ids']
                            for d in snap['diagnostics']))


if __name__ == '__main__':
    unittest.main()
