#!/usr/bin/env python3
"""Check the selected Pi model without generating tokens or probing other GPUs."""
import argparse
import json
import os
from pathlib import Path
import sys
import urllib.request

def selected(argv, settings):
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--provider')
    parser.add_argument('--model')
    args, _ = parser.parse_known_args(argv)
    provider = args.provider or settings.get('defaultProvider')
    model = args.model or settings.get('defaultModel')
    if args.model and '/' in args.model:
        provider, model = args.model.split('/', 1)
    return provider, model

def validate(provider_id, model_id, providers, request_json):
    provider = providers.get(provider_id)
    if not provider:
        return {'provider': provider_id, 'model': model_id, 'check': 'not a custom local provider'}
    model = next((m for m in provider.get('models', []) if m.get('id') == model_id), None)
    if model is None:
        raise ValueError(f'Model {provider_id}/{model_id} is absent from models.json')
    base = provider['baseUrl'].rstrip('/')
    headers = {'Accept': 'application/json'}
    key = provider.get('apiKey')
    if isinstance(key, str) and key and not key.startswith('!'):
        headers['Authorization'] = 'Bearer ' + os.environ.get(key, key)
    catalog = request_json(base + '/models', headers)
    served = next((m for m in catalog.get('data', []) if m.get('id') == model_id), None)
    if served is None:
        raise ValueError(f'The selected endpoint is not serving {model_id}')
    configured = model.get('contextWindow')
    actual = served.get('context_length', served.get('max_model_len'))
    if actual and configured and configured > actual:
        raise ValueError(f'Configured context {configured} exceeds server context {actual}')
    if model.get('maxTokens', 0) >= (configured or 131072):
        raise ValueError('Output budget leaves no space for input')
    return {'provider':provider_id,'model':model_id,'context':actual or configured,'max_output':model.get('maxTokens'),'inferenceStarted':False}

def request_json(url, headers):
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=10) as response:
        return json.load(response)

def main(argv=None, agent_dir=None):
    argv = sys.argv[1:] if argv is None else argv
    if any(arg in argv for arg in ['--help', '-h', '--version', '-v', '--list-models']):
        return
    agent_dir = Path(agent_dir or Path(__file__).resolve().parents[2])
    settings = json.loads((agent_dir / 'settings.json').read_text())
    providers = json.loads((agent_dir / 'models.json').read_text())['providers']
    report = validate(*selected(argv, settings), providers, request_json)
    print('Local model ready: ' + json.dumps(report, ensure_ascii=False), file=sys.stderr)

if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'LOCAL_MODEL_CHECK_FAILED: {type(exc).__name__}: {exc}', file=sys.stderr)
        sys.exit(1)
