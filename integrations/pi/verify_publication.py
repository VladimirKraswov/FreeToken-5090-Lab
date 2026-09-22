"""Check published-source identity and public configuration/evidence hygiene."""
import hashlib
import json
import re
from pathlib import Path

root = Path(__file__).resolve().parent
report = json.loads((root / 'evidence/verification.json').read_text())
for relative, digest in report['files_sha256'].items():
    assert hashlib.sha256((root / relative).read_bytes()).hexdigest() == digest, relative
model = json.loads((root / 'examples/models.merge.json').read_text())['providers']['local-qwen']
assert model['baseUrl'] == 'http://<inference-host>:1919/v1'
assert model['apiKey'] == 'local'
assert model['models'][0]['maxTokens'] == 16384
assert model['models'][0]['contextWindow'] == 131072
assert json.loads((root / 'examples/settings.merge.json').read_text())['defaultThinkingLevel'] == 'medium'
private = re.compile(r'192\.168\.\d+\.\d+|/Users/|/opt/homebrew/|/home/vladimir|BEGIN (?:OPENSSH|RSA|EC) PRIVATE KEY|gh[pousr]_[A-Za-z0-9]{20,}')
for path in root.rglob('*'):
    if not path.is_file() or 'node_modules' in path.parts or '__pycache__' in path.parts:
        continue
    if path == Path(__file__).resolve() or path.name == 'live-smoke.json' and path.parent == root:
        continue
    assert private.search(path.read_text()) is None, f'Private machine value in {path}'
print('Published source hashes, portable examples and publication hygiene verified.')
