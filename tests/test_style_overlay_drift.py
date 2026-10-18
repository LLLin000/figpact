"""Drift is refused before running changed trusted source; no nearest match."""

import matplotlib.pyplot as plt

from figpact import style_overlay


def test_changed_source_is_not_executed_by_overlay_reload(tmp_path):
    script = tmp_path/'plot.py'
    script.write_text('''
import matplotlib.pyplot as plt
from figpact import GidRegistry
SCOPES=('main',)
def build_figure_and_registry(scope='main'):
    f,a=plt.subplots()
    a.plot([0,1,2],[1,2,3],label='signal')
    return f,GidRegistry(scope=scope)
''', encoding='utf-8')
    target = next(t for t in style_overlay.inventory(script) if t['role']=='curve.linewidth')
    overlay = tmp_path/'style.json'
    first = style_overlay.apply(script, edits=[{'target_id':target['id'],'value':.8}],
                                overlay=overlay, allow_draft=True)
    assert first['local_edit_state']=='PASS',first
    saved=overlay.read_bytes()
    marker=tmp_path/'changed-source-executed'
    with script.open('a',encoding='utf-8') as handle:
        handle.write(f'\nfrom pathlib import Path\nPath({str(marker)!r}).touch()\n')
    fig,_,result=style_overlay.load(overlay)
    plt.close(fig)
    assert result['local_edit_state']=='ERROR',result
    assert not marker.exists(), 'changed source ran before its stored hash was checked'
    assert overlay.read_bytes()==saved
