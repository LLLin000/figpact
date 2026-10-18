"""Real statistical input: partial controls must not hide failed verification."""
import json
from pathlib import Path
import shutil

import yaml

from figpact import init_contract
from figpact.cli import main


def test_unify_returns_failure_when_committed_figure_verification_fails(tmp_path, capsys):
    source = Path(__file__).resolve().parents[1] / 'examples' / 'statistics'
    script = tmp_path / 'statistical.py'
    config = tmp_path / 'statistical.yaml'
    shutil.copyfile(source / script.name, script)
    shutil.copyfile(source / config.name, config)
    draft = init_contract.discover(script, config)
    for candidate in draft['candidates']:
        candidate['confirmed'] = True
    contract = tmp_path / 'contract.yaml'
    contract.write_text(yaml.safe_dump(draft), encoding='utf-8')
    verification = init_contract.verify(contract, width_mm=80)
    assert set(verification['verified']) == {'axis_font_pt', 'tick_font_pt', 'legend_font_pt'}
    assert verification['failed'] == ['line_width']
    manifest = tmp_path / 'plate.yaml'
    manifest.write_text(yaml.safe_dump({
        'plate': {'target_width_mm': 80, 'figures': [{
            'id': 'statistics', 'kind': 'code', 'source': str(script),
            'config': str(config), 'contract': str(contract), 'scope': 'main'}]},
        'design': {'global': {'axis_title_pt': 8, 'axis_tick_pt': 8},
                   'plot': {'curve_linewidth_pt': 0.8}},
    }), encoding='utf-8')
    script_before = script.read_bytes()
    capsys.readouterr()
    code = main(['plate', 'unify', str(manifest), '--apply'])
    result = json.loads(capsys.readouterr().out)
    applied = result['unify']['per_figure'][0]['result']
    assert result['status'] not in ('OK', 'PARTIAL'), result['status']
    assert result['unify']['status'] not in ('OK', 'PARTIAL'), result['unify']
    assert applied['status'] != 'OK', applied
    assert applied['source_commit_state'] == 'COMMITTED'
    assert applied['figure_verification_state'] == 'FAIL'
    assert applied['refused_roles'] == ['line_width']
    assert yaml.safe_load(config.read_text(encoding='utf-8'))['line_width'] == 1.2
    assert script.read_bytes() == script_before
    assert code == 1, 'a failed rendered figure must fail the CLI even after a successful write'
    dual = result['receipt']['dual_state']
    assert dual['source_commit_state'] == 'COMMITTED', dual
    assert dual['figure_verification_state'] == 'FAIL', dual
