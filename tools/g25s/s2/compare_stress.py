"""Compare every historical G25-S candidate, never remove failed cases."""
import argparse
from collections import Counter
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OLD = ROOT / 'tools/g25s/runs'


def load(directory):
    result = {}
    sources = []
    figures = []
    negatives = []
    for path in sorted(directory.glob('*/results.json')):
        source = json.loads(path.read_text(encoding='utf-8'))
        sources.append(source)
        for figure in source['figures']:
            figures.append({'source': source['id'], **figure})
            for probe in figure['probes']:
                if probe.get('boundary') == 'inspect_candidate':
                    key = (source['id'], figure['scope'], probe['name'])
                    if key in result:
                        raise ValueError(f'duplicate probe key: {key}')
                    result[key] = probe
                elif probe.get('boundary') == 'check_plan':
                    negatives.append(probe)
    return result, sources, figures, negatives


def state(probe):
    if probe is None:
        return {'status': 'MISSING'}
    return {k: probe.get(k) for k in ('local_edit_state', 'figure_verification_state',
            'science_unchanged', 'error', 'local_problems', 'official_overlay_absent')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--new', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    before = {}
    for name in ('gallery-probes', 'compatible-first', 'thirdparty-first'):
        samples, _, _, _ = load(OLD / name)
        before.update(samples)
    assert len(before) == 129
    after, sources, figures, negatives = load(args.new)
    rows = []
    counts = Counter()
    for key, original in before.items():
        current = after.get(key)
        same = current is not None and all(current.get(field) == original.get(field)
                for field in ('target_id', 'base_value', 'requested_value'))
        row = {'source': key[0], 'scope': key[1], 'probe': key[2],
               'same_target_and_value': same, 'before': state(original), 'after': state(current)}
        rows.append(row)
        counts['historical_probes'] += 1
        counts['missing_probes'] += current is None
        counts['request_drift'] += current is not None and not same
        counts['old_uncaught_exceptions'] += bool(original.get('error'))
        counts['new_uncaught_exceptions'] += bool(current and current.get('error'))
        if current:
            kind = key[2].split(':')[-1]
            counts[kind + '_count'] += 1
            counts[kind + '_local_pass'] += current.get('local_edit_state') == 'PASS'
            counts[kind + '_whole_pass'] += current.get('figure_verification_state') == 'PASS'
            counts['official_overlay_absent'] += current.get('official_overlay_absent') is True
    summary = {'kind': 'G25-S2 DEVELOPMENT fixed-denominator comparison',
        'model_called': False, 'independent_signoff': False, 'g25_status': 'BLOCKED',
        'counts': dict(counts), 'sources': len(sources), 'baseline_failed': [
            {'id': s['id'], 'error': s['baseline_error']} for s in sources if s.get('baseline_error')],
        'source_unchanged': sum(s.get('source_unchanged') is True for s in sources),
        'figures': len(figures), 'context_failures': [
            {'source': f['source'], 'scope': f['scope'], 'error': f['context_error']}
            for f in figures if f.get('context_error')],
        'plan_negatives': len(negatives), 'plan_negatives_rejected': sum(
            p.get('rejected') is True for p in negatives),
        'new_candidate_probes': len(after),
        'additional_candidates_not_in_historical_denominator': [list(k) for k in after if k not in before],
        'probe_comparison': rows}
    with args.output.open('x', encoding='utf-8') as handle:
        json.dump(summary, handle, indent=2, ensure_ascii=False, allow_nan=False)
    print(json.dumps({k: v for k, v in summary.items() if k not in ('probe_comparison',)}, indent=2, ensure_ascii=False))
    if counts['missing_probes'] or counts['request_drift'] or len(sources) != 26:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
