"""G16 R2: real CLI persistence + independent process replay on fixed G15 inputs."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
ENV = dict(os.environ, PYTHONPATH=str(ROOT), MPLBACKEND='Agg', PYTHONDONTWRITEBYTECODE='1')
SAMPLES = [
    ('bar_ylabel', 'tools/g15/B/g15b_barchart_decl.py', 'main', 'axis.title', 0, 'y', 8),
    ('shared_ticks', 'tools/g15/A/wrap_subplots_demo_r1.py', 'fig07', 'axis.tick', 0, 'y', 8),
    ('errorbar_curve', 'tools/g15/B/g15b_errorbar_decl.py', 'ax0', 'curve.linewidth', 0, None, .8),
]


def run(args, dest):
    command = [sys.executable, '-B', '-X', 'utf8', '-m', 'figpact', 'overlay', *args]
    result = subprocess.run(command, cwd=ROOT, env=ENV, capture_output=True, text=True, timeout=180)
    dest.with_suffix('.stdout.json').write_text(result.stdout, encoding='utf-8')
    dest.with_suffix('.stderr.log').write_text(result.stderr, encoding='utf-8')
    return result.returncode, json.loads(result.stdout)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output-dir', type=Path, required=True)
    out = parser.parse_args().output_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    results = []
    for name, script, scope, role, axes, axis, value in SAMPLES:
        directory = out / name
        directory.mkdir(parents=True, exist_ok=True)
        common = ['--script', str(ROOT/script), '--scope', scope]
        code, inventory = run(['inventory', *common], directory/'inventory')
        assert code == 0, inventory
        targets = [t for t in inventory['targets'] if t['role'] == role
                   and t['display']['axes_index'] == axes
                   and (axis is None or t['selector'].get('axis') == axis)]
        assert len(targets) == 1 and targets[0]['eligible'], targets
        edits = directory/'edits.json'
        edits.write_text(json.dumps([{'target_id':targets[0]['id'], 'value':value}]), encoding='utf-8')
        overlay = directory/'overlay.json'
        assert not overlay.exists(), 'Use a fresh output directory for first-apply evidence'
        source_hash = hashlib.sha256((ROOT/script).read_bytes()).hexdigest()
        code, first = run(['apply', *common, '--edits', str(edits), '--overlay', str(overlay),
                           '--allow-draft'], directory/'apply')
        assert first['local_edit_state'] == 'PASS', first
        assert first['source_commit_state'] in ('COMMITTED', 'COMMITTED_DRAFT'), first
        saved = overlay.read_bytes()
        replay_code, replay = run(['render', str(overlay), '--output', str(directory/'after.png')],
                                  directory/'restart')
        assert replay['local_edit_state'] == 'PASS', replay
        assert replay['science_unchanged'], replay
        repeat_code, repeat = run(['apply', *common, '--edits', str(edits), '--overlay', str(overlay),
                                   '--expected-sha256', hashlib.sha256(saved).hexdigest(),
                                   '--allow-draft'], directory/'repeat')
        assert repeat['local_edit_state'] == 'PASS', repeat
        assert overlay.read_bytes() == saved
        assert hashlib.sha256((ROOT/script).read_bytes()).hexdigest() == source_hash
        results.append({'sample':name, 'value':value, 'first_exit':code,
                        'restart_exit':replay_code, 'repeat_exit':repeat_code,
                        'first':first, 'restart':replay, 'repeat':repeat,
                        'source_unchanged':True, 'overlay_repeat_bytes_identical':True})
    (out/'results.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
    print(json.dumps([{'sample':r['sample'], 'local':r['first']['local_edit_state'],
                       'whole_QA':r['first']['figure_verification_state'],
                       'saved':r['first']['source_commit_state']} for r in results], indent=2))


if __name__ == '__main__':
    main()
