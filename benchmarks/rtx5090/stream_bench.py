import argparse
import gzip
import os
import hashlib
import json
import statistics
import time
import urllib.request
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument('--base', default='http://127.0.0.1:1919')
p.add_argument('--label', required=True)
p.add_argument('--lengths', default='0,75000,105000')
p.add_argument('--output', required=True)
p.add_argument('--tokens', type=int, default=384)
p.add_argument('--repeats', type=int, default=1)
p.add_argument('--thinking', default='medium')
p.add_argument('--seed', default='')
p.add_argument('--temperature', type=float, default=0)
p.add_argument('--prompt-file')
p.add_argument('--model', default='qwen38-flash-next')
a = p.parse_args()
out = Path(a.output)
out.mkdir(parents=True, exist_ok=True)
for length in map(int, a.lengths.split(',')):
    for rep in range(a.repeats):
        nonce = ('run-' + a.seed + '-' + str(rep)) if a.seed else 'run-' + str(time.time_ns())
        prompt = nonce + '\nReference padding follows.\n' + ' test' * length
        prompt += '\nIgnore the reference padding. Write a complete Python LRU cache implementation with type hints, a doubly linked list, get and put methods, and detailed unit tests. Output code only. Continue until every method and test is complete.'
        if a.prompt_file:
            prompt = nonce + '\n' + (gzip.decompress(Path(a.prompt_file).read_bytes()).decode() if a.prompt_file.endswith('.gz') else Path(a.prompt_file).read_text())
        payload = {'model': a.model, 'messages': [{'role': 'user', 'content': prompt}], 'stream': True, 'stream_options': {'include_usage': True}, 'max_tokens': a.tokens, 'ignore_eos': True, 'temperature': a.temperature, 'reasoning_effort': a.thinking}
        req = urllib.request.Request(a.base + '/v1/chat/completions', data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + os.environ.get('FT_API_KEY', 'local')})
        report = {'label': a.label, 'repeat': rep, 'padding_tokens': length, 'requested_output': a.tokens, 'reasoning_effort': a.thinking, 'temperature': a.temperature, 'started_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'nonce': nonce, 'base': a.base}
        events = []
        usage = {}
        parts = []
        first_event = None
        first_token = None
        last_token = None
        finish = None
        done = False
        started = time.perf_counter()
        print(json.dumps({'starting': report}), flush=True)
        with urllib.request.urlopen(req, timeout=1800) as response:
            for line in response:
                now = time.perf_counter() - started
                if not line.startswith(b'data:'):
                    continue
                if first_event is None:
                    first_event = now
                raw = line[5:].strip()
                if raw == b'[DONE]':
                    done = True
                    break
                event = json.loads(raw)
                if event.get('error'):
                    raise RuntimeError(event['error'])
                if event.get('usage'):
                    usage = event['usage']
                for choice in event.get('choices', []):
                    delta = choice.get('delta', {})
                    text = (delta.get('reasoning_content') or '') + (delta.get('content') or '')
                    if text or delta.get('tool_calls'):
                        if first_token is None:
                            first_token = now
                        last_token = now
                        events.append({'t': now, 'chars': len(text), 'delta': delta})
                        parts.append(text)
                    finish = choice.get('finish_reason') or finish
        elapsed = time.perf_counter() - started
        count = usage.get('completion_tokens', 0)
        if not done or not finish or count <= 1 or first_token is None or last_token <= first_token:
            raise RuntimeError('Incomplete stream or missing token usage; refusing to report throughput')
        intervals = [b['t'] - x['t'] for x, b in zip(events, events[1:])]
        report.update({'elapsed_s': elapsed, 'first_event_s': first_event, 'ttft_s': first_token, 'last_token_s': last_token, 'usage': usage, 'finish_reason': finish, 'nonempty_chunks': len(events), 'end_to_end_tps': count / elapsed, 'decode_tps': (count - 1) / (last_token - first_token) if last_token and last_token > first_token else None, 'median_chunk_interval_ms': statistics.median(intervals) * 1000 if intervals else None, 'max_chunk_interval_ms': max(intervals) * 1000 if intervals else None, 'text_sha256': hashlib.sha256(''.join(parts).encode()).hexdigest(), 'text_preview': ''.join(parts)[-700:]})
        stem = f'{a.label}-{length}-{rep}'
        (out / (stem + '.json')).write_text(json.dumps(report, indent=2))
        (out / (stem + '.events.json')).write_text(json.dumps(events))
        (out / (stem + '.txt')).write_text(''.join(parts))
        print(json.dumps({k: v for k, v in report.items() if k != 'text_preview'}), flush=True)
