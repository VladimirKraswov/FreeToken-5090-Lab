import base64
import os
import json
import struct
import time
import urllib.request
import zlib
from pathlib import Path

BASE = os.environ.get('FT_BASE', 'http://127.0.0.1:1919')
OUT = Path(os.environ.get('FT_VALIDATION_OUT', 'validation.json'))

def call(payload):
    payload = dict(model=os.environ.get('FT_MODEL', 'qwen38-flash-next'), temperature=0,
                   max_tokens=1024, reasoning_effort='medium', **payload)
    req = urllib.request.Request(BASE + '/v1/chat/completions',
                                 data=json.dumps(payload).encode(),
                                 headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + os.environ.get('FT_API_KEY', 'local')})
    start = time.perf_counter()
    with urllib.request.urlopen(req, timeout=1800) as response:
        result = json.load(response)
    choice = result['choices'][0]
    return {'elapsed_s': time.perf_counter() - start, 'usage': result['usage'],
            'finish_reason': choice['finish_reason'],
            'content': choice['message'].get('content'),
            'tool_calls': choice['message'].get('tool_calls')}

report = {'timestamp': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
with urllib.request.urlopen(BASE + '/health', timeout=10) as response:
    report['health'] = json.load(response)

def save(name, result):
    report[name] = result
    OUT.write_text(json.dumps(report, indent=2))
    print(json.dumps({name: result}), flush=True)

pad_per_half = int(os.environ.get('FT_LONG_PADDING_PER_HALF', '52500'))
if not 1 <= pad_per_half <= 120000:
    raise ValueError('FT_LONG_PADDING_PER_HALF must be between 1 and 120000')

# Different keys at the start, middle and end exercise retrieval across the prompt.
long_prompt = ('A reference contains three labels. Read it and report their values.\n'
               'ALPHA = HARBOR-5826\n' + ' test' * pad_per_half +
               '\nBETA = ORBIT-9417\n' + ' test' * pad_per_half +
               '\nGAMMA = CEDAR-3072\n'
               'Return ALPHA, BETA and GAMMA with their exact values. No explanation.')
r = call({'messages': [{'role': 'user', 'content': long_prompt}]})
r['passed'] = (r['usage']['prompt_tokens'] > 100000 and
               all(x in (r['content'] or '') for x in ['HARBOR-5826', 'ORBIT-9417', 'CEDAR-3072'])
               and r['finish_reason'] == 'stop')
save('long_context_retrieval', r)

def chunk(tag, data):
    return struct.pack('!I', len(data)) + tag + data + struct.pack('!I', zlib.crc32(tag + data))

vision_size = int(os.environ.get('FT_VISION_SIZE', '1536'))
if not 1 <= vision_size <= 4096:
    raise ValueError('FT_VISION_SIZE must be between 1 and 4096')

png = (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('!2I5B', vision_size, vision_size, 8, 2, 0, 0, 0))
       + chunk(b'IDAT', zlib.compress((b'\x00' + b'\xff\x00\x00' * vision_size) * vision_size))
       + chunk(b'IEND', b''))
r = call({'messages': [{'role': 'user', 'content': [
    {'type': 'text', 'text': 'What color is this image? Answer with one English word.'},
    {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,' + base64.b64encode(png).decode()}}
]}]})
r['image_size_px'] = [vision_size, vision_size]
r['passed'] = 'red' in (r['content'] or '').lower() and r['finish_reason'] == 'stop'
save('vision', r)

r = call({'messages': [{'role': 'user', 'content': 'Use the get_weather tool to get the weather in Moscow.'}],
          'tools': [{'type': 'function', 'function': {
              'name': 'get_weather', 'description': 'Get weather for a city.',
              'parameters': {'type': 'object', 'properties': {'city': {'type': 'string'}}, 'required': ['city']}}}]})
calls = r['tool_calls'] or []
r['passed'] = (len(calls) == 1 and calls[0]['function']['name'] == 'get_weather'
               and 'moscow' in calls[0]['function']['arguments'].lower()
               and r['finish_reason'] == 'tool_calls')
save('tools', r)
req = urllib.request.Request(BASE + '/v1/responses', data=json.dumps({
    'model': os.environ.get('FT_MODEL', 'qwen38-flash-next'), 'input': 'Reply with exactly: READY',
    'max_output_tokens': 512, 'reasoning': {'effort': 'medium'},
}).encode(), headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + os.environ.get('FT_API_KEY', 'local')})
started = time.perf_counter()
with urllib.request.urlopen(req, timeout=180) as response:
    result = json.load(response)
text = ''.join(part.get('text', '') for item in result.get('output', [])
               for part in item.get('content', []) if part.get('type') == 'output_text')
save('responses_api', {'elapsed_s': time.perf_counter() - started,
                       'usage': result.get('usage'), 'content': text,
                       'passed': 'READY' in text and result.get('status') == 'completed'})
report['passed'] = all(report[name]['passed'] for name in ['long_context_retrieval', 'vision', 'tools', 'responses_api'])
OUT.write_text(json.dumps(report, indent=2))
raise SystemExit(0 if report['passed'] else 1)
