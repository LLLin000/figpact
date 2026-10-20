"""G25-S2 complete suites and isolated historical strict semantics.

Run only after product edits finish. Keeps full stdout/stderr, never overwrites
old evidence. Clinical inputs and strict exports remain in private temp storage.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[3]


def save(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')


def run(name, command, out, env, timeout=2400):
    start = time.time()
    with (out / f'{name}.stdout.log').open('w', encoding='utf-8') as stdout, \
         (out / f'{name}.stderr.log').open('w', encoding='utf-8') as stderr:
        try:
            result = subprocess.run(command, cwd=ROOT, env=env, stdout=stdout,
                                    stderr=stderr, timeout=timeout)
            code, timed_out = result.returncode, False
        except subprocess.TimeoutExpired:
            code, timed_out = None, True
    record = {'name': name, 'command': command, 'returncode': code,
              'timed_out': timed_out, 'seconds': round(time.time() - start, 2)}
    save(out / f'{name}.process.json', record)
    print(json.dumps(record), flush=True)
    return record


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--strict-only', action='store_true')
    args = ap.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    env = dict(os.environ, MPLBACKEND='Agg', PYTHONDONTWRITEBYTECODE='1',
               PYTHONIOENCODING='utf-8', PYTHONPATH=str(ROOT))
    fingerprint = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in sorted((ROOT / 'figpact').rglob('*.py'))}
    save(out / 'engine-before.json', fingerprint)
    records = []
    if not args.strict_only:
        for name, command in [
            ('python', [sys.executable, '-B', '-X', 'utf8', '-m', 'pytest', 'tests',
                        '--ignore=tests/browser', '-q', '-p', 'no:cacheprovider', '--tb=short']),
            ('chromium', [sys.executable, '-B', '-X', 'utf8', '-m', 'pytest', 'tests/browser',
                          '-q', '-p', 'no:cacheprovider', '--tb=short']),
            ('node', ['node', '--test', 'tests/inspector/test_inspector.js']),
        ]:
            records.append(run(name, command, out, env))
    private = Path(tempfile.mkdtemp(prefix='figpact-g25s2-strict-'))
    # Exact product/source copies satisfy the examples' ancestor discovery;
    # no empty import marker, altered clinical source, or synthetic data.
    shutil.copytree(ROOT / 'figpact', private / 'figpact', ignore=shutil.ignore_patterns('__pycache__'))
    for name, script, config, data in [
        ('nmr', '08 NMR.py', 'nmr.yaml', '核磁原始数据'),
        ('ftir', 'plot_ftir.py', 'ftir.yaml', '2084_1788253487778_26083154776'),
    ]:
        stage = private / 'examples' / name
        stage.mkdir(parents=True)
        for filename in (script, config, 'figure_style.py'):
            shutil.copy2(ROOT / 'examples' / name / filename, stage / filename)
        shutil.copytree(ROOT / 'examples' / name / data, stage / data,
                        ignore=shutil.ignore_patterns('__pycache__'))
    record = run('strict', [sys.executable, '-B', '-X', 'utf8',
        str(ROOT / 'tools/g23/publication_trial.py'),
        '--nmr-script', str(private / 'examples/nmr/08 NMR.py'),
        '--nmr-config', str(private / 'examples/nmr/nmr.yaml'),
        '--ftir-stage', str(private / 'examples/ftir'),
        '--out', str(private / 'evidence')], out, env, timeout=2400)
    records.append(record)
    strict_summary = private / 'evidence/g23_tick_summary.json'
    if strict_summary.exists():
        shutil.copy2(strict_summary, out / 'strict-summary.json')
    save(out / 'results.json', {'checks': records, 'private_strict_artifacts': str(private),
         'engine_unchanged_during_checks': fingerprint == {
             str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted((ROOT / 'figpact').rglob('*.py'))}})
    if any(r['returncode'] != 0 for r in records):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
