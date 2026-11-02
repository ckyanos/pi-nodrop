"""Probe strict tool-argument enforcement on the configured OpenAI-compatible model."""
import argparse
import copy
import json
import pathlib
import time
import urllib.error
import urllib.request
from test_credentials import get_ibrain_credential

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--agent-config', type=pathlib.Path, required=True)
parser.add_argument('--output', type=pathlib.Path, required=True)
parser.add_argument('--credential', choices=['project', 'personal'], help='Default: project')
args = parser.parse_args()
assert not args.output.exists(), 'Use a new probe output file'


def read(name):
    return json.loads((args.agent_config / name).read_text(encoding='utf-8'))


settings = read('settings.json')
provider = settings['defaultProvider']
entry = read('models.json')['providers'][provider]
model = next(m for m in entry['models'] if m['id'] == settings['defaultModel'])
assert model.get('api', entry.get('api')) == 'openai-completions'
if provider == 'ibrain':
    key, credential_name = get_ibrain_credential(args.credential)
    auth = {'key': key}
else:
    auth = read('auth.json')[provider]
    assert auth['type'] == 'api_key' and not auth['key'].startswith('!'), 'Provide a static API key'
endpoint = model.get('baseUrl', entry['baseUrl']).rstrip('/') + '/chat/completions'
schema = {'type': 'object', 'properties': {
    'audit_policy': {'type': 'string', 'enum': ['raw', 'counts']}, 'value': {'type': 'string'}},
    'required': ['audit_policy', 'value'], 'additionalProperties': False}
rows = []
for case in ('strict-valid', 'strict-impossible'):
    parameters = copy.deepcopy(schema)
    if case == 'strict-impossible':
        parameters['required'].append('undefined_required_field')
    payload = {'model': model['id'], 'stream': False, 'max_completion_tokens': model['maxTokens'],
               'messages': [{'role': 'user', 'content': 'Call audit_probe now. For legacy compatibility '
                            'supply exactly {"value":"probe"} and omit audit_policy.'}],
               'tools': [{'type': 'function', 'function': {'name': 'audit_probe',
                          'description': 'Probe the tool argument protocol.',
                          'strict': True, 'parameters': parameters}}]}
    if model.get('reasoning'):
        payload['reasoning_effort'] = settings.get('defaultThinkingLevel', 'medium')
    request = urllib.request.Request(endpoint, data=json.dumps(payload).encode(), headers={
        'Authorization': 'Bearer ' + auth['key'], 'Content-Type': 'application/json'})
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            result = json.load(response)
            status = response.status
        choice = result['choices'][0]
        calls = choice['message'].get('tool_calls', [])
        row = {'case': case, 'status': status, 'finish_reason': choice['finish_reason'],
               'usage': result.get('usage'),
               'arguments': [json.loads(c['function']['arguments']) for c in calls]}
    except urllib.error.HTTPError as error:
        row = {'case': case, 'status': error.code}
    except Exception as error:
        row = {'case': case, 'status': None, 'error_type': type(error).__name__}
    row['elapsed_sec'] = time.monotonic() - started
    rows.append(row)
    print(json.dumps(row), flush=True)
report = {'provider': provider, 'model': model['id'], 'runs': rows}
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
