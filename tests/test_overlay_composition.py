"""G17 composable overlay consumer regression (owner: ComposeOverlay).

A(ylabel8) -> B(ticks8) -> A9 -> removeA; B stays 8 in source reload;
A restored to original 10 after remove; failures leave bytes unchanged;
empty request retains; remove-all clears; QA failure retains prior bytes.
"""
import hashlib
import matplotlib
import json
from pathlib import Path

import matplotlib.pyplot as plt
import pytest

from figpact import style_overlay

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'tools/g15/B/g15b_barchart_decl.py'

_PINNED_RC = {
    "font.size": 10.0,
    "axes.labelsize": "medium",
    "axes.titlesize": "large",
    "xtick.labelsize": "medium",
    "ytick.labelsize": "medium",
    "legend.fontsize": "medium",
    "figure.dpi": 100.0,
    "lines.linewidth": 1.5,
}


@pytest.fixture(autouse=True)
def _matplotlib_default_style():
    """Pin ambient rc to matplotlib defaults for the whole module.

    ``style_overlay`` builds in the caller's ambient rc
    (``final_size._ambient`` = caller globals + import-time overlay). The
    barchart fixture script sets no fontsize itself, so its baseline is
    ambient: matplotlib defaults give ylabel/ticks 10.0, which is what the
    A8/B8/A9 assertions assume. Another suite's FTIR ``build_scene`` calls
    ``fs.apply()`` directly on the shared-process globals and leaks
    ``xtick/ytick.labelsize=8`` (plus ``axes.labelsize=8.5``,
    ``font.size=8``) past teardown; without this pin, B's ``value=8`` edit
    is a silent no-op and the shared ``required_changed`` gate must fail
    it (G16 semantics: a no-op is never a fake first edit). Restores every
    pinned key on teardown so this module never leaks outward either.
    """
    saved = {key: matplotlib.rcParams[key] for key in _PINNED_RC}
    matplotlib.rcParams.update(_PINNED_RC)
    try:
        yield
    finally:
        matplotlib.rcParams.update(saved)


def _ids():
    inv = style_overlay.inventory(SCRIPT, scope='main')
    a = next(t['id'] for t in inv
             if t['role'] == 'axis.title' and t['selector'].get('axis') == 'y')
    b = next(t['id'] for t in inv
             if t['role'] == 'axis.tick' and t['selector'].get('axis') == 'x')
    return a, b


def _h(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def test_composition_sequence(tmp_path):
    a, b = _ids()
    overlay = tmp_path / 'style.json'
    r = style_overlay.apply(SCRIPT, scope='main',
                            edits=[{'target_id': a, 'value': 8}], overlay=overlay)
    assert r['local_edit_state'] == 'PASS', r
    assert r['source_commit_state'] == 'COMMITTED', r
    assert r['figure_verification_state'] == 'PASS', r
    r = style_overlay.apply(SCRIPT, scope='main',
                            edits=[{'target_id': b, 'value': 8}], overlay=overlay,
                            expected_before_sha256=_h(overlay))
    assert r['local_edit_state'] == 'PASS', r
    assert r['source_commit_state'] == 'COMMITTED', r
    saved = {t['id']: t['value']
             for t in json.loads(overlay.read_text(encoding='utf-8'))['targets']}
    assert saved == {a: 8.0, b: 8.0}, saved
    r = style_overlay.apply(SCRIPT, scope='main',
                            edits=[{'target_id': a, 'value': 9}], overlay=overlay,
                            expected_before_sha256=_h(overlay))
    assert r['local_edit_state'] == 'PASS', r
    trans = r['audit_summary'].get('transition', {})
    assert trans.get('requested_upserts') == [a], trans
    assert trans.get('retained') == [b], trans
    r = style_overlay.apply(SCRIPT, scope='main', edits=[], overlay=overlay,
                            expected_before_sha256=_h(overlay), remove=[a])
    assert r['local_edit_state'] == 'PASS', r
    assert r['source_commit_state'] == 'COMMITTED', r
    assert r['audit_summary']['transition']['requested_removals'] == [a], r
    saved = {t['id']: t['value']
             for t in json.loads(overlay.read_text(encoding='utf-8'))['targets']}
    assert saved == {b: 8.0}, saved
    fig, _, loaded = style_overlay.load(overlay)
    try:
        assert loaded['local_edit_state'] == 'PASS', loaded
        assert fig.axes[0].yaxis.label.get_fontsize() == 10.0
        assert {t.get_fontsize() for t in fig.axes[0].get_xticklabels()} == {8.0}
    finally:
        plt.close(fig)
    plt.close('all')


def test_empty_request_retains_all(tmp_path):
    a, b = _ids()
    overlay = tmp_path / 'style.json'
    first = style_overlay.apply(SCRIPT, scope='main',
                                edits=[{'target_id': a, 'value': 8}], overlay=overlay)
    assert first['source_commit_state'] == 'COMMITTED', first
    second = style_overlay.apply(SCRIPT, scope='main',
                                 edits=[{'target_id': b, 'value': 8}], overlay=overlay,
                                 expected_before_sha256=_h(overlay))
    assert second['source_commit_state'] == 'COMMITTED', second
    before = overlay.read_bytes()
    r = style_overlay.apply(SCRIPT, scope='main', edits=[], overlay=overlay,
                            expected_before_sha256=_h(overlay), remove=[])
    assert r['local_edit_state'] == 'PASS', r
    assert overlay.read_bytes() == before
    plt.close('all')


def test_remove_all_clears_to_original(tmp_path):
    a, b = _ids()
    overlay = tmp_path / 'style.json'
    first = style_overlay.apply(SCRIPT, scope='main',
                                edits=[{'target_id': a, 'value': 8}], overlay=overlay)
    assert first['source_commit_state'] == 'COMMITTED', first
    second = style_overlay.apply(SCRIPT, scope='main',
                                 edits=[{'target_id': b, 'value': 8}], overlay=overlay,
                                 expected_before_sha256=_h(overlay))
    assert second['source_commit_state'] == 'COMMITTED', second
    r = style_overlay.apply(SCRIPT, scope='main', edits=[], overlay=overlay,
                            expected_before_sha256=_h(overlay), remove=[a, b])
    assert r['local_edit_state'] == 'PASS', r
    assert r['audit_summary'].get('cleared') is True, r
    assert json.loads(overlay.read_text(encoding='utf-8'))['targets'] == []
    fig, _, loaded = style_overlay.load(overlay)
    try:
        assert loaded['local_edit_state'] == 'PASS', loaded
        assert fig.axes[0].yaxis.label.get_fontsize() == 10.0
        assert {t.get_fontsize() for t in fig.axes[0].get_xticklabels()} == {10.0}
    finally:
        plt.close(fig)
    plt.close('all')


def test_failure_modes_leave_bytes(tmp_path):
    a, b = _ids()
    overlay = tmp_path / 'style.json'
    first = style_overlay.apply(SCRIPT, scope='main',
                                edits=[{'target_id': a, 'value': 8}], overlay=overlay)
    assert first['source_commit_state'] == 'COMMITTED', first
    stable = overlay.read_bytes()
    bad = style_overlay.apply(
        SCRIPT, scope='main', edits=[{'target_id': b, 'value': 8}],
        overlay=overlay, expected_before_sha256='0' * 64)
    assert bad['source_commit_state'] == 'NOT_WRITTEN', bad
    assert overlay.read_bytes() == stable
    bad = style_overlay.apply(
        SCRIPT, scope='main', edits=[{'target_id': a, 'value': 9}],
        overlay=overlay, expected_before_sha256=_h(overlay), remove=[a])
    assert bad['local_edit_state'] == 'ERROR', bad
    assert overlay.read_bytes() == stable
    bad = style_overlay.apply(
        SCRIPT, scope='main', edits=[], overlay=overlay,
        expected_before_sha256=_h(overlay), remove=['no.such.id'])
    assert bad['local_edit_state'] == 'ERROR', bad
    assert overlay.read_bytes() == stable
    bad = style_overlay.apply(
        SCRIPT, scope='main', edits=[{'target_id': a, 'value': 9},
                                     {'target_id': a, 'value': 9}],
        overlay=overlay, expected_before_sha256=_h(overlay))
    assert bad['local_edit_state'] == 'ERROR', bad
    assert overlay.read_bytes() == stable
    plt.close('all')


def test_qa_failure_retains_prior_bytes(tmp_path):
    a, _b = _ids()
    overlay = tmp_path / 'draft.json'
    good = style_overlay.apply(SCRIPT, scope='main',
                               edits=[{'target_id': a, 'value': 8}],
                               overlay=overlay)
    assert good['figure_verification_state'] == 'PASS', good
    stable = overlay.read_bytes()
    refused = style_overlay.apply(SCRIPT, scope='main',
                                  edits=[{'target_id': a, 'value': 4}],
                                  overlay=overlay,
                                  expected_before_sha256=_h(overlay))
    assert refused['source_commit_state'] == 'NOT_WRITTEN', refused
    assert refused['figure_verification_state'] == 'FAIL', refused
    assert overlay.read_bytes() == stable
    plt.close('all')


def test_update_drift_does_not_execute_changed_source(tmp_path):
    script = tmp_path / 'plot.py'
    script.write_text('''
import matplotlib.pyplot as plt
from figpact import GidRegistry
SCOPES = ('main',)
def build_figure_and_registry(scope='main'):
    f, a = plt.subplots()
    a.plot([0, 1, 2], [1, 2, 3], label='signal')
    a.set_ylabel('Length (mm)')
    return f, GidRegistry(scope=scope)
''', encoding='utf-8')
    target = next(t for t in style_overlay.inventory(script)
                  if t['role'] == 'curve.linewidth')
    overlay = tmp_path / 'style.json'
    first = style_overlay.apply(script,
                                edits=[{'target_id': target['id'], 'value': .8}],
                                overlay=overlay)
    assert first['local_edit_state'] == 'PASS', first
    stable = overlay.read_bytes()
    marker = tmp_path / 'changed-source-executed'
    with script.open('a', encoding='utf-8') as handle:
        handle.write(f'\nfrom pathlib import Path\nPath({str(marker)!r}).touch()\n')
    bad = style_overlay.apply(script,
                              edits=[{'target_id': target['id'], 'value': .9}],
                              overlay=overlay,
                              expected_before_sha256=_h(overlay))
    assert bad['source_commit_state'] == 'NOT_WRITTEN', bad
    assert 'DRIFT' in (bad.get('drift') or ''), bad
    assert not marker.exists(), 'changed source ran before its stored hash was checked'
    assert overlay.read_bytes() == stable
    plt.close('all')


def test_remove_cannot_launder_disappeared_target(tmp_path, monkeypatch):
    import figpact.style_identity as ident
    a, b = _ids()
    overlay = tmp_path / 'style.json'
    first = style_overlay.apply(SCRIPT, scope='main',
                                edits=[{'target_id': a, 'value': 8}], overlay=overlay)
    assert first['source_commit_state'] == 'COMMITTED', first
    second = style_overlay.apply(SCRIPT, scope='main',
                                 edits=[{'target_id': b, 'value': 8}], overlay=overlay,
                                 expected_before_sha256=_h(overlay))
    assert second['source_commit_state'] == 'COMMITTED', second
    stable = overlay.read_bytes()
    real_inventory = ident.inventory

    def _drop_b(fig, scope='main'):
        return [d for d in real_inventory(fig, scope=scope) if d['id'] != b]

    monkeypatch.setattr(ident, 'inventory', _drop_b)
    bad = style_overlay.apply(SCRIPT, scope='main', edits=[], overlay=overlay,
                              expected_before_sha256=_h(overlay), remove=[b])
    assert bad['local_edit_state'] == 'ERROR', bad
    probs = ' '.join(bad.get('local_problems') or [])
    assert 'UNKNOWN_ID' in probs or 'AMBIGUOUS' in probs, bad
    assert overlay.read_bytes() == stable
    plt.close('all')
