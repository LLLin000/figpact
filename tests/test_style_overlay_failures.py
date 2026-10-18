"""A locally valid draft must never masquerade as whole-figure QA PASS."""
from pathlib import Path
import hashlib

import matplotlib.pyplot as plt

from figpact import style_overlay

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'tools/g15/B/g15b_barchart_decl.py'


def test_glyph_floor_requires_explicit_draft_and_survives_reload(tmp_path):
    target = next(t for t in style_overlay.inventory(SCRIPT, scope='main')
                  if t['role'] == 'axis.title' and t['selector']['axis'] == 'y')
    edits = [{'target_id': target['id'], 'value': 4}]
    overlay = tmp_path/'draft.json'
    refused = style_overlay.apply(SCRIPT, scope='main', edits=edits, overlay=overlay)
    assert refused['figure_verification_state'] == 'FAIL', refused
    assert not overlay.exists()
    draft = style_overlay.apply(SCRIPT, scope='main', edits=edits, overlay=overlay,
                                allow_draft=True)
    assert draft['local_edit_state'] == 'PASS', draft
    assert draft['source_commit_state'] == 'COMMITTED_DRAFT', draft
    assert draft['figure_verification_state'] == 'FAIL', draft
    fig, _, loaded = style_overlay.load(overlay)
    try:
        assert loaded['local_edit_state'] == 'PASS', loaded
        assert loaded['figure_verification_state'] == 'FAIL', loaded
        assert loaded['figure_qa']['glyph_floor']
        assert loaded['figure_qa']['pass'] is False
    finally:
        plt.close(fig)
    saved = overlay.read_bytes()
    result = style_overlay.render(overlay, overlay)
    assert result['local_edit_state'] != 'PASS', result
    assert overlay.read_bytes() == saved


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
