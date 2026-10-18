"""A locally valid draft must never masquerade as whole-figure QA PASS."""
from pathlib import Path
import hashlib

import matplotlib.pyplot as plt

from figpact import style_overlay

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'tools/g15/B/g15b_barchart_decl.py'


def test_new_floor_defect_refused_even_as_draft(tmp_path):
    """G20: brand-new 4pt floor defect is refused; new QA rules not relaxed."""
    target = next(t for t in style_overlay.inventory(SCRIPT, scope='main')
                  if t['role'] == 'axis.title' and t['selector']['axis'] == 'y')
    edits = [{'target_id': target['id'], 'value': 4}]
    overlay = tmp_path/'draft.json'
    refused = style_overlay.apply(SCRIPT, scope='main', edits=edits, overlay=overlay)
    assert refused['figure_verification_state'] == 'FAIL', refused
    assert not overlay.exists()
    draft = style_overlay.apply(SCRIPT, scope='main', edits=edits, overlay=overlay,
                                allow_draft=True)
    assert draft['source_commit_state'] == 'NOT_WRITTEN', draft
    assert draft['figure_verification_state'] == 'FAIL', draft
    assert draft['qa_delta']['eligible'] is False, draft['qa_delta']
    assert draft['qa_delta']['new'], draft['qa_delta']
    assert not overlay.exists()


def test_baseline_floor_defect_inherited_as_draft(tmp_path):
    """G20: pre-existing baseline floor defect inherits into an eligible draft."""
    from figpact import qa as qa_mod
    script = tmp_path/'w.py'
    script.write_text(
        "import matplotlib\nmatplotlib.use('Agg')\n"
        "import matplotlib.pyplot as plt\nfrom figpact import GidRegistry\n"
        "SCOPES = ('main',)\nCONFIG = {}\n"
        "def build_figure_and_registry(scope='main'):\n"
        "    fig, ax = plt.subplots()\n"
        "    ax.plot([0, 1], [0, 1])\n"
        "    ax.set_ylabel('dose', fontsize=4)\n"
        "    return fig, GidRegistry(scope=scope)\n",
        encoding='utf-8')
    target = next(t for t in style_overlay.inventory(script, scope='main')
                  if t['role'] == 'curve.linewidth')
    baseline = style_overlay.apply(
        script, scope='main',
        edits=[{'target_id': target['id'], 'value': 0.8}],
        overlay=tmp_path/'baseline.json', allow_draft=True)
    assert baseline['source_commit_state'] == 'COMMITTED_DRAFT', baseline
    assert baseline['qa_delta']['eligible'] is True, baseline['qa_delta']
    assert baseline['qa_delta']['inherited'], baseline['qa_delta']
    ws_fig, _, ws_loaded = style_overlay.load_workspace(tmp_path/'baseline.json')
    try:
        assert ws_fig is not None
        assert ws_loaded['figure_verification_state'] == 'FAIL', ws_loaded
        strict_fig, _, strict_loaded = style_overlay.load(tmp_path/'baseline.json')
        assert strict_fig is None
        assert strict_loaded['figure_verification_state'] == 'FAIL', strict_loaded
    finally:
        plt.close(ws_fig)


def test_stale_overlay_update_cannot_overwrite_current_bytes(tmp_path):
    target = next(t for t in style_overlay.inventory(SCRIPT, scope='main')
                  if t['role'] == 'axis.title')
    overlay = tmp_path/'style.json'
    first = style_overlay.apply(SCRIPT, scope='main', edits=[{'target_id':target['id'],'value':8}],
                                overlay=overlay, allow_draft=True)
    assert first['local_edit_state'] == 'PASS', first
    original = overlay.read_bytes()
    update = style_overlay.apply(SCRIPT, scope='main', edits=[{'target_id':target['id'],'value':9}],
                                 overlay=overlay, expected_before_sha256=hashlib.sha256(b'stale').hexdigest(),
                                 allow_draft=True)
    assert update['source_commit_state'] == 'NOT_WRITTEN', update
    assert overlay.read_bytes() == original
