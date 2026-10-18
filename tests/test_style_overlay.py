"""Verified overlay persistence, restart and protected-source behavior."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import matplotlib.pyplot as plt
import pytest

from figpact import style_overlay

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'tools/g15/B/g15b_errorbar_decl.py'


def test_overlay_persists_curve_only_and_replays_after_restart(tmp_path):
    original = SCRIPT.read_bytes()
    target = next(t for t in style_overlay.inventory(SCRIPT, scope='ax0')
                  if t['role'] == 'curve.linewidth')
    overlay = tmp_path / 'style.json'
    edit = [{'target_id': target['id'], 'value': .8}]
    receipt = style_overlay.apply(SCRIPT, scope='ax0', edits=edit, overlay=overlay,
                                  allow_draft=True)
    assert receipt['local_edit_state'] == 'PASS', receipt
    assert receipt['source_commit_state'] in ('COMMITTED', 'COMMITTED_DRAFT'), receipt
    saved = overlay.read_bytes()
    code = '''
import json,sys
from figpact import style_overlay
fig,reg,r=style_overlay.load(sys.argv[1])
assert r['local_edit_state']=='PASS',r
ax0,ax1=fig.axes
assert ax0.lines[0].get_linewidth()==.8
assert ax1.lines[0].get_linewidth()==1.5
assert all(float(w)==1.5 for ax in fig.axes for c in ax.collections for w in c.get_linewidths())
assert ax1.get_yscale()=='log'
assert ax0.get_shared_x_axes().joined(ax0,ax1)
assert r['science_unchanged'] is True
print(json.dumps(r))
'''
    result = subprocess.run([sys.executable, '-B', '-X', 'utf8', '-c', code, str(overlay)],
                            cwd=ROOT, env=dict(os.environ, PYTHONPATH=str(ROOT), MPLBACKEND='Agg'),
                            capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    replay = json.loads(result.stdout)
    assert replay['local_edit_state'] == 'PASS'
    repeat = style_overlay.apply(SCRIPT, scope='ax0', edits=edit, overlay=overlay,
                                 expected_before_sha256=hashlib.sha256(saved).hexdigest(),
                                 allow_draft=True)
    assert repeat['local_edit_state'] == 'PASS', repeat
    assert overlay.read_bytes() == saved
    assert SCRIPT.read_bytes() == original


@pytest.mark.parametrize('value', [True, float('nan'), float('inf'), -1, 1000])
def test_invalid_value_never_creates_overlay(tmp_path, value):
    target = next(t for t in style_overlay.inventory(SCRIPT, scope='ax0')
                  if t['role'] == 'curve.linewidth')
    overlay = tmp_path / 'refused.json'
    result = style_overlay.apply(SCRIPT, scope='ax0', edits=[{'target_id':target['id'], 'value':value}],
                                 overlay=overlay)
    assert result['local_edit_state'] != 'PASS'
    assert not overlay.exists()
    plt.close('all')
