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

concurrency_file = root / 'data/concurrency-results-20261006.json'
if concurrency_file.exists():
    concurrency = json.loads(concurrency_file.read_text())
    payloads = {}
    for record in concurrency['records']:
        rows = record.get('requests') or [row for turn in record['rounds'] for row in turn['requests']]
        assert all(row['done'] and row['finish'] and row['usage']['completion_tokens'] > 0 for row in rows)
        assert all('content' not in row and 'reasoning' not in row for row in rows)
        accounting = record['accounting']
        assert accounting['deltas'] == accounting['expected']
        assert accounting['deltas']['completed'] == len(rows)
        assert accounting['deltas']['prompt_tokens_total'] == sum(row['usage']['prompt_tokens'] for row in rows)
        assert accounting['deltas']['completion_tokens_total'] == sum(row['usage']['completion_tokens'] for row in rows)
        assert accounting['before']['active'] == accounting['after']['active'] == 0
        wall = max(row['end'] for row in rows) - min(row['start'] for row in rows)
        assert math.isclose(record['metrics']['wall_s'], wall, rel_tol=1e-10)
        assert math.isclose(record['metrics']['e2e_tps'], sum(row['usage']['completion_tokens'] for row in rows) / wall, rel_tol=1e-10)
        if record['kind'] == 'fixed':
            assert len({row['usage']['completion_tokens'] for row in rows}) == 1
            assert all(row['finish'] == 'length' for row in rows)
        corpus = record.get('corpus', {})
        if corpus.get('corpus_version') is not None:
            assert all(row.get('cached_prompt_tokens') == 0 for row in rows)
            key = (record['kind'], record['corpus_id'], corpus['corpus_repeat'],
                   record['padding_requested'], record['concurrency'])
            identity = tuple((row['id'], row['payload_sha256']) for row in sorted(rows, key=lambda row: row['id']))
            assert key not in payloads or payloads[key] == identity, key
            payloads[key] = identity
        if 'steady_generation' in record:
            steady = record['steady_generation']
            left, right = steady['first_sample'], steady['last_sample']
            delta = right['requests']['completion_tokens_total'] - left['requests']['completion_tokens_total']
            span = right['t'] - left['t']
            assert span >= 5 and delta >= 32 and steady['completion_tokens'] == delta
            assert left['t'] >= max(row['first'] for row in rows) + 5
            assert math.isclose(steady['elapsed_s'], span, rel_tol=1e-10)
            assert math.isclose(steady['aggregate_tps'], delta / span, rel_tol=1e-10)
            assert math.isclose(steady['per_active_request_tps'], delta / span / record['concurrency'], rel_tol=1e-10)
            assert math.isclose(steady['aggregate_tps_lower_bound'], delta / (right['poll_end'] - left['poll_start']), rel_tol=1e-10)
            assert math.isclose(steady['aggregate_tps_upper_bound'], delta / (right['poll_start'] - left['poll_end']), rel_tol=1e-10)
            for sample in (left, right):
                assert sample['instance_id'] == accounting['instance_id']
                assert sample['requests']['active'] == record['concurrency']
                assert sample['requests']['completed'] == accounting['before']['completed']
                assert sample['requests']['prompt_tokens_total'] - accounting['before']['prompt_tokens_total'] == sum(row['usage']['prompt_tokens'] for row in rows)
    for group in concurrency['steady_groups']:
        rows = [record for record in concurrency['records'] if record['profile'] == group['profile'] and
                record['concurrency'] == group['concurrency'] and 'steady_generation' in record]
        assert len(rows) == group['repeats']
        assert math.isclose(group['aggregate_tps'], statistics.median(row['steady_generation']['aggregate_tps'] for row in rows), rel_tol=1e-10)
    for group in concurrency['stats_poll_groups']:
        polls = [value for record in concurrency['records'] if record['profile'] == group['profile']
                 for value in record.get('stats_poll_latencies_s', [])]
        assert len(polls) == group['polls'] and all(value >= 0 for value in polls)
        assert math.isclose(group['median_ms'], 1000 * statistics.median(polls), rel_tol=1e-10)
        assert math.isclose(group['max_ms'], 1000 * max(polls), rel_tol=1e-10)
    for group in concurrency['fixed_groups']:
        rows = [record for record in concurrency['records'] if record['kind'] == 'fixed' and
                all(record[key] == group[key] for key in ('profile', 'padding_requested', 'concurrency', 'corpus_id'))]
        assert len(rows) == group['repeats']
        for key in ('wall_s', 'e2e_tps', 'ttft_median_s'):
            assert math.isclose(group['metrics'][key]['median'], statistics.median(row['metrics'][key] for row in rows), rel_tol=1e-10)
    assert all(group['payload_identity_ok'] for group in concurrency['matched_corpora'])
    assert all(all(item['checks'].values()) and item['counter_deltas'] == item['expected'] and
               item['semantic_passed'] and item['tool_passed'] and item['mixed_passed'] and item['queued_json_passed']
               for item in concurrency['quality'])
    assert all(all(item['checks'].values()) for item in concurrency['cancellation'])
    assert len(concurrency['excluded']) == 6 and all(item['reasons'] for item in concurrency['excluded'])
    print(f"Checked {len(concurrency['records'])} concurrent probe records, matched payloads and counter arithmetic.")

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
