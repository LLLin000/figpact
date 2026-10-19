"""Baseline scene lifecycle: per-call scenes, owned-only cleanup, failure safety."""
import gc
import unittest
import weakref
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib._pylab_helpers import Gcf

from figpact.session import load_module

ROOT = Path(__file__).resolve().parents[1]
FTIR_SCRIPT = ROOT / "examples/ftir/plot_ftir.py"
FTIR_CONFIG = ROOT / "examples/ftir/ftir.yaml"
NMR_SCRIPT = ROOT / "examples/nmr/08 NMR.py"
NMR_CONFIG = ROOT / "examples/nmr/nmr.yaml"


def _fresh(which):
    if which == "ftir":
        return load_module(FTIR_SCRIPT, FTIR_CONFIG)
    return load_module(NMR_SCRIPT, NMR_CONFIG)


class BaselineSceneLifecycleTest(unittest.TestCase):
    def test_contract_closes_owned_only_and_keeps_caller(self):
        for which in ("ftir", "nmr"):
            with self.subTest(which=which):
                mod = _fresh(which)
                ext, ax = plt.subplots()
                ax.plot([0, 1], [0, 1])
                base = len(Gcf.get_all_fig_managers())
                for scope in mod.SCOPES:
                    contract = mod.layout_contract(scope)
                    self.assertIn("nodes", contract)
                    self.assertTrue(contract["nodes"])
                gc.collect()
                self.assertEqual(mod._BASELINE_SCENES, {})
                self.assertEqual(list(mod._BASELINE_OWNED), [])
                self.assertEqual(mod._BASELINE_DEPTH, 0)
                self.assertEqual(len(Gcf.get_all_fig_managers()), base)
                self.assertIsNotNone(ax.figure)
                self.assertEqual(list(ax.lines[0].get_ydata()), [0, 1])
                plt.close(ext)

    def test_manifest_closes_owned_only(self):
        for which in ("ftir", "nmr"):
            with self.subTest(which=which):
                mod = _fresh(which)
                base = len(Gcf.get_all_fig_managers())
                man = mod.science_manifest(mod.load_science())
                self.assertIn("science", man)
                gc.collect()
                self.assertEqual(mod._BASELINE_SCENES, {})
                self.assertEqual(list(mod._BASELINE_OWNED), [])
                self.assertEqual(len(Gcf.get_all_fig_managers()), base)

    def test_nested_reuse_within_call_single_build(self):
        mod = _fresh("ftir")
        calls = {"n": 0}
        real_build = mod._build

        def counting(science, scope, _owned=None):
            calls["n"] += 1
            return real_build(science, scope, _owned=_owned)

        mod._build = counting
        try:
            contract = mod.layout_contract("main")  # internally nests via _panel_scopes
            self.assertTrue(contract["nodes"])
            self.assertEqual(calls["n"], 1)
            self.assertEqual(mod._BASELINE_SCENES, {})
        finally:
            mod._build = real_build

    def test_build_failure_during_draw_closes_partial_fig(self):
        for which in ("ftir", "nmr"):
            with self.subTest(which=which):
                mod = _fresh(which)
                base = len(Gcf.get_all_fig_managers())
                refs = []
                name = "draw_panel" if which == "ftir" else "place_peak_labels"
                real_draw = getattr(mod, name)

                def failing(*a, **k):
                    refs.append(weakref.ref(plt.gcf()))
                    raise RuntimeError("injected draw failure")

                setattr(mod, name, failing)
                try:
                    with self.assertRaises(RuntimeError):
                        mod.layout_contract(mod.SCOPES[0])
                finally:
                    setattr(mod, name, real_draw)
                gc.collect()
                self.assertEqual(mod._BASELINE_SCENES, {})
                self.assertEqual(list(mod._BASELINE_OWNED), [])
                self.assertEqual(len(Gcf.get_all_fig_managers()), base)
                self.assertTrue(refs)
                self.assertTrue(all(r() is None for r in refs))

    def test_build_failure_inside_draw_spectra_closes_fig(self):
        # `_draw_spectra` 内 `subplots` 之后、`fig.canvas.draw()` 途中抛异常：
        # 所有权在创建点已登记，`_draw_spectra` 自己 except 关掉，不漏给上层。
        import matplotlib.backends.backend_agg as _agg

        mod = _fresh("nmr")
        base = len(Gcf.get_all_fig_managers())
        refs: list = []

        real_figure_draw = _agg.FigureCanvasAgg.draw

        def failing_draw(self, *a, **k):
            refs.append(weakref.ref(self.figure))
            raise RuntimeError("injected inside-draw failure")

        _agg.FigureCanvasAgg.draw = failing_draw
        try:
            with self.assertRaises(RuntimeError):
                mod.layout_contract(mod.SCOPES[0])
        finally:
            _agg.FigureCanvasAgg.draw = real_figure_draw
        gc.collect()
        self.assertEqual(mod._BASELINE_SCENES, {})
        self.assertEqual(list(mod._BASELINE_OWNED), [])
        self.assertEqual(len(Gcf.get_all_fig_managers()), base)
        self.assertTrue(refs)
        self.assertTrue(all(r() is None for r in refs))

    def test_role_extraction_failure_mid_multiscope_closes_all_owned(self):
        mod = _fresh("ftir")
        base = len(Gcf.get_all_fig_managers())
        refs = []
        real_build = mod._build
        def tracking(science, scope, _owned=None):
            fig, reg = real_build(science, scope, _owned=_owned)
            refs.append(weakref.ref(fig))
            return fig, reg

        mod._build = tracking
        real_roles = mod._scene_roles
        seen = {"n": 0}

        def failing_roles(fig, reg):
            seen["n"] += 1
            if seen["n"] == 2:  # fail during multiscope manifest traversal, not first build
                raise RuntimeError("injected role failure")
            return real_roles(fig, reg)

        mod._scene_roles = failing_roles
        try:
            with self.assertRaises(RuntimeError):
                mod.science_manifest(mod.load_science())
        finally:
            mod._build = real_build
            mod._scene_roles = real_roles
        gc.collect()
        self.assertEqual(mod._BASELINE_SCENES, {})
        self.assertEqual(list(mod._BASELINE_OWNED), [])
        self.assertEqual(len(Gcf.get_all_fig_managers()), base)
        self.assertTrue(refs)
        self.assertTrue(all(r() is None for r in refs))

    def test_external_figure_never_closed(self):
        for which in ("ftir", "nmr"):
            with self.subTest(which=which):
                mod = _fresh(which)
                ext, ax = plt.subplots()
                ax.plot([0, 1], [2, 3])
                manager = ext.canvas.manager
                mod.layout_contract(mod.SCOPES[0])
                mod.science_manifest(mod.load_science())
                gc.collect()
                self.assertIn(manager, Gcf.get_all_fig_managers())
                self.assertEqual(list(ax.lines[0].get_ydata()), [2, 3])
                plt.close(ext)


if __name__ == "__main__":
    unittest.main()
