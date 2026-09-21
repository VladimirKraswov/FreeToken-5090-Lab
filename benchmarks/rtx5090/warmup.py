#!/usr/bin/env python3
import base64
import os
import json
import struct
import time
import urllib.request
import zlib
from pathlib import Path

URL = os.environ.get('FT_BASE', 'http://127.0.0.1:1919')
OUT = Path(os.environ.get('FT_WARMUP_OUT', 'warmup.json'))

def request(path, payload=None, timeout=10):
    req = urllib.request.Request(URL + path,
                                 data=None if payload is None else json.dumps(payload).encode(),
                                 headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + os.environ.get('FT_API_KEY', 'local')})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)

for _ in range(180):
    try:
        health = request('/health')
        if health.get('maintenance') == 'serving':
            break
    except OSError:
        pass
    time.sleep(5)
else:
    raise SystemExit('FreeToken did not become ready for warmup')

def chunk(tag, data):
    return struct.pack('!I', len(data)) + tag + data + struct.pack('!I', zlib.crc32(tag + data))

png = (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('!2I5B', 128, 128, 8, 2, 0, 0, 0))
       + chunk(b'IDAT', zlib.compress((b'\x00' + b'\xff\x00\x00' * 128) * 128)) + chunk(b'IEND', b''))
cases = [
    ('greedy', 'Write a complete Python LRU cache with type hints and tests.', 0, 256),
    ('sampling', 'Explain how a hash table handles collisions, with a Python example.', 1, 128),
    ('prefill', ' test' * 16000 + '\nWrite a Python function for binary search.', 1, 64),
    ('vision', [
        {'type': 'text', 'text': 'What color is this image?'},
        {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,' + base64.b64encode(png).decode()}}
    ], 0, 64),
]
report = {'instance_id': health.get('instance_id'), 'status': 'warming', 'cases': []}
OUT.write_text(json.dumps(report, indent=2))
for name, content, temperature, tokens in cases:
    started = time.perf_counter()
    result = request('/v1/chat/completions', {
        'model': os.environ.get('FT_MODEL', 'qwen38-flash-next'), 'messages': [{'role': 'user', 'content': content}],
        'temperature': temperature, 'max_tokens': tokens, 'ignore_eos': True,
        'reasoning_effort': 'medium',
    }, timeout=600)
    if not result.get('usage', {}).get('completion_tokens'):
        raise RuntimeError(f'Warmup {name} produced no tokens')
    report['cases'].append({'name': name, 'elapsed_s': time.perf_counter() - started, 'usage': result['usage']})
    OUT.write_text(json.dumps(report, indent=2))
report.update(status='warm', timestamp=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
OUT.write_text(json.dumps(report, indent=2))
print(json.dumps(report), flush=True)
