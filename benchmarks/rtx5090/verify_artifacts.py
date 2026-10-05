"""Check fixture identity, metric arithmetic and publication hygiene without a GPU."""
import gzip
import hashlib
import json
import math
import re
import statistics
from pathlib import Path

root = Path(__file__).resolve().parent
fixture = gzip.decompress((root / 'fixtures/real-code-prompt.txt.gz').read_bytes())
assert hashlib.sha256(fixture).hexdigest() == '2aa13fecf38c5f26b79b7e7b981d2aaf240e384744e395ee64f3bf7945cfe804'
checked = 0
incomplete = []
for path in (root / 'data/results').glob('*.json'):
    report = json.loads(path.read_text())
    if not report.get('usage', {}).get('completion_tokens'):
        assert report.get('decode_tps') is None, path
        incomplete.append(path.name)
        continue
    count = report['usage']['completion_tokens']
    assert count > 1 and report['last_token_s'] > report['ttft_s'] > 0, path
    assert math.isclose(report['decode_tps'], (count - 1) / (report['last_token_s'] - report['ttft_s']), rel_tol=1e-10), path
    assert math.isclose(report['end_to_end_tps'], count / report['elapsed_s'], rel_tol=1e-10), path
    assert report['finish_reason'], path
    assert 'text_preview' not in report, path
    checked += 1

strata_file = root / 'data/strata-results-20261005.json'
if strata_file.exists():
    strata = json.loads(strata_file.read_text())
    for profile in strata['profiles']:
        assert profile['complete'], (profile['round'], profile['profile'])
        assert len(profile['quality']['cases']) == 9 and profile['quality']['passed']
        assert all(case['passed'] for case in profile['quality']['cases'])
        for name, case in profile['cases'].items():
            assert len(case['runs']) == 3, name
            for run in case['runs']:
                count = run['usage']['completion_tokens']
                assert count == strata['settings']['output_tokens']
                assert run['last_token_s'] > run['ttft_s'] > 0
                assert math.isclose(run['decode_tps'], (count - 1) / (run['last_token_s'] - run['ttft_s']), rel_tol=1e-10)
                assert math.isclose(run['end_to_end_tps'], count / run['elapsed_s'], rel_tol=1e-10)
                if not run['include_in_performance']:
                    assert run['exclusion_reason']
            included = [run for run in case['runs'] if run['include_in_performance']]
            assert included, name
            for metric in ('decode_tps', 'ttft_s', 'elapsed_s', 'end_to_end_tps'):
                assert math.isclose(case[f'median_{metric}'], statistics.median(run[metric] for run in included), rel_tol=1e-10)
    assert all(status.get('production_restored') for status in strata['production_restoration'].values())
    print(f"Checked {len(strata['profiles'])} complete Strata profiles, exclusions and derived medians.")

repo = root.parent.parent
private = re.compile(r'192\.168\.\d+\.\d+|/Users/|/home/vladimir|BEGIN (?:OPENSSH|RSA|EC) PRIVATE KEY|gh[pousr]_[A-Za-z0-9]{20,}')
for folder in (root, repo / 'docs/rtx5090', repo / 'deploy/rtx5090'):
    for path in folder.rglob('*'):
        if not path.is_file() or '__pycache__' in path.parts or path.suffix in ('.gz', '.pyc'):
            continue
        # The scanner itself names the prohibited patterns, not private values.
        if path == Path(__file__).resolve():
            continue
        assert private.search(path.read_text()) is None, f'Private value in {path}'
assert private.search(fixture.decode()) is None, 'Private value in fixture'
print(f'Checked {checked} raw timing records, fixture checksum and public package hygiene.')
print(f'Excluded {len(incomplete)} incomplete historical streams: {incomplete}')
