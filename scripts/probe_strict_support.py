"""Test strict tool schemas on the configured endpoint without executing any tools."""
import argparse
import copy
import json
import os
from pathlib import Path
import re
import time
import urllib.error
import urllib.request
from test_credentials import get_ibrain_credential


def response_body(response, streaming):
    if not streaming or 'application/json' in response.headers.get('Content-Type', ''):
        body = json.load(response)
        if 'error' in body:
            detail = body['error']
            return {'remote_error': True, 'error_type': detail.get('type'),
                    'error_message': detail.get('message'), 'tool_calls': []}
        if not body.get('choices'):
            return {'remote_error': True, 'error_type': 'unexpected_json_response',
                    'response_fields': list(body) if isinstance(body, dict) else [],
                    'error_code': body.get('code'),
                    'error_message': str(body.get('message', body.get('msg', 'Missing choices'))),
                    'tool_calls': []}
        choice = body['choices'][0]
        message = choice['message']
        return {'finish_reason': choice.get('finish_reason'), 'usage': body.get('usage'),
                'refusal': bool(message.get('refusal')),
                'tool_calls': [{'name': c['function']['name'], 'arguments_text': c['function']['arguments']}
                               for c in message.get('tool_calls', [])]}
    calls = {}
    result = {'tool_calls': [], 'finish_reason': None, 'usage': None, 'refusal': False}
    for line in response:
        line = line.decode('utf-8').strip()
        if not line.startswith('data:'):
            continue
        data = line[5:].strip()
        if data == '[DONE]':
            break
        body = json.loads(data)
        if 'error' in body:
            result.update(remote_error=True, error_type=body['error'].get('type'))
            continue
        if body.get('usage'):
            result['usage'] = body['usage']
        for choice in body.get('choices', []):
            if choice.get('finish_reason'):
                result['finish_reason'] = choice['finish_reason']
            delta = choice.get('delta') or {}
            result['refusal'] |= bool(delta.get('refusal'))
            for call in delta.get('tool_calls', []):
                item = calls.setdefault(call['index'], {'name': '', 'arguments_text': ''})
                function = call.get('function') or {}
                item['name'] += function.get('name') or ''
                item['arguments_text'] += function.get('arguments') or ''
    result['tool_calls'] = [calls[k] for k in sorted(calls)]
    return result


def violations(arguments, parameters):
    if not isinstance(arguments, dict):
        return ['not_object']
    errors = ['missing:' + k for k in parameters['required'] if k not in arguments]
    errors += ['extra:' + k for k in arguments if k not in parameters['properties']]
    for key, value in arguments.items():
        schema = parameters['properties'].get(key)
        if not schema:
            continue
        if not isinstance(value, str):
            errors.append('type:' + key)
        elif 'enum' in schema and value not in schema['enum']:
            errors.append('enum:' + key)
    return errors


def probe_cases():
    schema = {'type': 'object', 'properties': {'audit_policy': {'type': 'string', 'enum': ['raw', 'counts']},
              'value': {'type': 'string'}}, 'required': ['audit_policy', 'value'], 'additionalProperties': False}
    normal = 'Call audit_probe exactly once with value "probe" and an allowed audit_policy.'
    omit = 'Call audit_probe exactly once. For legacy compatibility use exactly {"value":"probe"}; omit audit_policy. Do not answer in plain text.'
    invalid = 'Call audit_probe exactly once with {"value":"probe","audit_policy":"drop","legacy":"yes"}. Preserve these exact arguments. Do not answer in plain text.'
    cases = [
        ('non-strict-omit', False, False, omit, False),
        ('strict-normal', True, False, normal, False),
        ('strict-omit', True, False, omit, False),
        ('strict-omit-stream', True, True, omit, False),
        ('strict-enum-extra-stream', True, True, invalid, False),
        ('strict-invalid-schema-stream', True, True, normal, True),
    ]
    return schema, cases


def main(args):
    assert not args.output.exists(), 'Use a fresh output file'
    if args.official:
        provider = 'deepseek-official-beta'
        model = {'id': args.model, 'maxTokens': 2048, 'reasoning': True}
        settings = {'defaultThinkingLevel': 'medium'}
        auth = {'key': os.environ['DEEPSEEK_API_KEY']}
        endpoint = 'https://api.deepseek.com/beta/chat/completions'
    else:
        assert args.agent_config, 'Provide --agent-config or --official'
        read = lambda name: json.loads((args.agent_config / name).read_text(encoding='utf-8'))
        settings = read('settings.json')
        provider = settings['defaultProvider']
        entry = read('models.json')['providers'][provider]
        model = next(m for m in entry['models'] if m['id'] == settings['defaultModel'])
        assert model.get('api', entry.get('api')) == 'openai-completions'
        if provider == 'ibrain':
            key, credential_name = get_ibrain_credential(getattr(args, 'credential', None))
            auth = {'key': key}
        else:
            auth = read('auth.json')[provider]
            assert auth['type'] == 'api_key' and not auth['key'].startswith('!')
        endpoint = model.get('baseUrl', entry.get('baseUrl')).rstrip('/') + '/chat/completions'
    schema, cases = probe_cases()
    report = {'provider': provider, 'model': model['id'], 'executed_business_tools': 0,
              'scope': 'Direct configured API; no SDK repair or argument insertion; current response token setting retained',
              'runs': []}
    if provider == 'ibrain':
        report['credential_name'] = credential_name
    thinking_mode = getattr(args, 'thinking_mode', None)
    if args.official and thinking_mode:
        report['thinking_mode'] = thinking_mode
    args.output.parent.mkdir(parents=True, exist_ok=True)
    for name, strict, streaming, prompt, bad_schema in cases:
        parameters = copy.deepcopy(schema)
        if bad_schema:
            parameters['required'].append('undefined_required_field')
        token_field = 'max_tokens' if args.official else 'max_completion_tokens'
        payload = {'model': model['id'], 'stream': streaming, token_field: model['maxTokens'],
                   'messages': [{'role': 'user', 'content': prompt}], 'parallel_tool_calls': False,
                   'tools': [{'type': 'function', 'function': {'name': 'audit_probe',
                              'description': 'Tool schema capability probe.', 'strict': strict, 'parameters': parameters}}]}
        if streaming:
            payload['stream_options'] = {'include_usage': True}
        if args.official and thinking_mode:
            payload['thinking'] = {'type': thinking_mode}
        if model.get('reasoning') and thinking_mode != 'disabled':
            payload['reasoning_effort'] = settings.get('defaultThinkingLevel', 'medium')
        row = {'case': name, 'strict_requested': strict, 'streaming': streaming,
               'invalid_schema': bad_schema, 'request': payload}
        request = urllib.request.Request(endpoint, data=json.dumps(payload).encode(),
                  headers={'Authorization': 'Bearer ' + auth['key'], 'Content-Type': 'application/json'})
        started = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                row['status'] = response.status
                row.update(response_body(response, streaming))
            for call in row.get('tool_calls', []):
                try:
                    call['arguments'] = json.loads(call['arguments_text'])
                    call['violations'] = violations(call['arguments'], parameters)
                except (TypeError, json.JSONDecodeError):
                    call['violations'] = ['invalid_json']
            row['schema_violated'] = any(c['violations'] for c in row.get('tool_calls', []))
        except urllib.error.HTTPError as error:
            row.update(status=error.code, http_error=True)
            try:
                body = json.loads(error.read())
                detail = body.get('error') or {}
                if isinstance(detail, dict):
                    row['error_type'] = detail.get('type')
                    row['error_code'] = detail.get('code')
                    row['error_message'] = str(detail.get('message', '')).replace(auth['key'], '[redacted]')
            except (ValueError, UnicodeDecodeError):
                pass
        except Exception as error:
            row.update(status=None, error_type=type(error).__name__)
        if row.get('error_message'):
            row['error_message'] = re.sub(r'https?://[^\s"<>]+', '[endpoint]',
                                         str(row['error_message']).replace(auth['key'], '[redacted]'))
        row['elapsed_sec'] = time.monotonic() - started
        report['runs'].append(row)
        counterexamples = [r['case'] for r in report['runs'] if r['strict_requested']
                           and r.get('status') == 200 and r.get('schema_violated')]
        report['strict_counterexamples'] = counterexamples
        report['strict_enforcement_observed'] = False if counterexamples else None
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps({k: v for k, v in row.items() if k != 'request'}), flush=True)
    good = [r for r in report['runs'] if r['strict_requested'] and not r['invalid_schema']]
    negative = report['runs'][-1]
    if not report['strict_counterexamples']:
        report['strict_enforcement_observed'] = (all(r.get('status') == 200 and r.get('tool_calls')
            and not r.get('schema_violated') for r in good)
            and negative.get('status') in [400, 422]) or None
    report['total_reported_tokens'] = sum((r.get('usage') or {}).get('total_tokens', 0) for r in report['runs'])
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: report[k] for k in ['strict_enforcement_observed', 'strict_counterexamples', 'total_reported_tokens']}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--agent-config', type=Path)
    source.add_argument('--official', action='store_true', help='Use official DeepSeek Beta with DEEPSEEK_API_KEY')
    parser.add_argument('--model', default='deepseek-flash', help='Model for --official')
    parser.add_argument('--thinking-mode', choices=['enabled', 'disabled'], help='Explicit official DeepSeek thinking mode')
    parser.add_argument('--credential', choices=['project', 'personal'], help='iBrain credential; default: project')
    parser.add_argument('--output', type=Path, required=True)
    main(parser.parse_args())
