"""Send vendor-documented tool parameters through configured iBrain routes; record mapping limits."""
import argparse
import copy
import io
import json
from pathlib import Path
import re
import time
import urllib.error
import urllib.request

from probe_strict_support import probe_cases, response_body, violations
from test_credentials import get_ibrain_credential


def read_raw_response(response, streaming):
    if not streaming or 'json' in response.headers.get('Content-Type', '').lower():
        return response.read().decode('utf-8', errors='replace')
    lines = []
    for line in response:
        text = line.decode('utf-8', errors='replace')
        lines.append(text)
        if text.strip() == 'data: [DONE]':
            break
        if text.startswith('data:'):
            try:
                event = json.loads(text[5:].strip())
            except ValueError:
                continue
            if event.get('error') or event.get('type') == 'error':
                break
    return ''.join(lines)


def cases_for(family):
    _, cases = probe_cases()
    normal, omit, invalid = cases[1][3], cases[2][3], cases[4][3]
    rows = [('normal', False, normal), ('omit', False, omit),
            ('omit-stream', True, omit), ('enum-extra-stream', True, invalid)]
    if family == 'qwen':
        rows += [('named-omit', False, omit), ('named-omit-stream', True, omit),
                 ('named-enum-extra-stream', True, invalid)]
    if family == 'doubao':
        rows += [('invalid-schema', True, normal)]
    rows += [('invalid-native-option', False, normal)]
    return rows


def parse_response(status, content_type, raw, streaming):
    if not streaming or 'json' in content_type.lower():
        body = json.loads(raw)
        if not isinstance(body, dict) or not body.get('choices'):
            detail = body.get('error') or {} if isinstance(body, dict) else {}
            return {'remote_error': True, 'response_fields': list(body) if isinstance(body, dict) else [],
                    'error_type': detail.get('type') if isinstance(detail, dict) else None,
                    'error_message': (detail.get('message') if isinstance(detail, dict) else str(detail))
                                     or body.get('msg', 'Missing choices'), 'tool_calls': []}
        choice = body['choices'][0]
        msg = choice['message']
        return {'finish_reason': choice.get('finish_reason'), 'usage': body.get('usage'),
                'response_model': body.get('model'), 'text': msg.get('content'),
                'has_reasoning_content': bool(msg.get('reasoning_content')),
                'tool_calls': [{'name': c['function']['name'], 'arguments_text': c['function']['arguments']}
                               for c in msg.get('tool_calls', [])]}
    # Reuse the existing SSE tool-argument assembly without SDK repair.
    stream = io.BytesIO(raw.encode())
    stream.headers = {'Content-Type': content_type}
    result = response_body(stream, True)
    if result.get('remote_error') and not result.get('error_message'):
        for line in raw.splitlines():
            if not line.startswith('data:'):
                continue
            try:
                body = json.loads(line[5:].strip())
            except ValueError:
                continue
            if isinstance(body.get('error'), dict):
                result['error_message'] = body['error'].get('message')
                result['error_code'] = body['error'].get('code')
    return result


def probe(family, model, endpoint, key, output, selected_cases=None):
    assert not any(x in model.lower() for x in ('claude', 'anthropic'))
    assert not output.exists(), 'Use a fresh output file'
    schema, _ = probe_cases()
    report = {'family': family, 'model': model, 'scope': 'Vendor-documented body through iBrain Chat Completions',
              'upstream_native_mode_activation_confirmed': False, 'executed_business_tools': 0, 'runs': []}
    for name, streaming, prompt in cases_for(family):
        if selected_cases is not None and name not in selected_cases:
            continue
        params = copy.deepcopy(schema)
        if name == 'invalid-schema':
            params['required'].append('undefined_required_field')
        function = {'name': 'audit_probe', 'description': 'Tool schema capability probe.', 'parameters': params}
        if family == 'doubao':
            function['strict'] = True
        payload = {'model': model, 'messages': [{'role': 'user', 'content': prompt}],
                   'tools': [{'type': 'function', 'function': function}],
                   'tool_choice': {'type': 'function', 'function': {'name': 'audit_probe'}}
                                  if name.startswith('named-') else 'auto',
                   'stream': streaming, 'max_tokens': 2048}
        if streaming:
            payload['stream_options'] = {'include_usage': True}
        if family == 'qwen':
            payload['enable_thinking'] = 'pi_nodrop_invalid_boolean' if name == 'invalid-native-option' else False
        else:
            payload['thinking'] = {'type': 'PI_NODROP_INVALID_MODE' if name == 'invalid-native-option'
                                           else ('disabled' if family == 'doubao' else 'enabled')}
        row = {'case': name, 'request': payload, 'streaming': streaming,
               'invalid_control': name in ('invalid-schema', 'invalid-native-option')}
        req = urllib.request.Request(endpoint, data=json.dumps(payload).encode(),
                                     headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
        started = time.monotonic()
        try:
            try:
                with urllib.request.urlopen(req, timeout=180) as response:
                    status, content_type = response.status, response.headers.get('Content-Type', '')
                    raw = read_raw_response(response, streaming)
            except urllib.error.HTTPError as error:
                status, content_type = error.code, error.headers.get('Content-Type', '')
                raw = error.read().decode('utf-8', errors='replace')
            # Preserve the entire response, redacting credentials and internal URLs first.
            clean = re.sub(r'https?://[^\s"<>]+', '[endpoint]', raw.replace(key, '[redacted]'))
            row.update(status=status, content_type=content_type, raw_response=clean)
            try:
                row.update(parse_response(status, content_type, clean, streaming))
            except (ValueError, KeyError, TypeError, AttributeError) as error:
                row['parse_error'] = type(error).__name__
            for call in row.get('tool_calls', []):
                try:
                    call['arguments'] = json.loads(call['arguments_text'])
                    call['violations'] = violations(call['arguments'], params)
                except (TypeError, ValueError):
                    call['violations'] = ['invalid_json']
        except Exception as error:
            row.update(status=None, error_type=type(error).__name__)
        row['elapsed_sec'] = time.monotonic() - started
        report['runs'].append(row)
        report['total_reported_tokens'] = sum((r.get('usage') or {}).get('total_tokens', 0) for r in report['runs'])
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps({'family': family, 'model': model, 'case': name, 'status': row.get('status'),
                          'finish_reason': row.get('finish_reason'), 'error': row.get('error_message'),
                          'violations': [c.get('violations') for c in row.get('tool_calls', [])]},
                         ensure_ascii=True), flush=True)
        time.sleep(2.6)
    return report


def main(args):
    assert not args.output_dir.exists(), 'Use a fresh output directory'
    args.output_dir.mkdir(parents=True)
    p = args.agent_config
    entry = json.loads((p / 'models.json').read_text(encoding='utf-8'))['providers']['ibrain']
    key, credential_name = get_ibrain_credential(args.credential)
    base = next(m['baseUrl'] for m in entry['models'] if m.get('api') == 'openai-completions').rstrip('/')
    compact = {'doubao': ['invalid-schema', 'invalid-native-option'],
               'qwen': ['normal', 'named-omit-stream', 'invalid-native-option'],
               'glm': ['normal', 'omit-stream', 'invalid-native-option']}
    reports = [probe(family, model, base + '/chat/completions', key, args.output_dir / (family + '.json'),
                     [name for name, _, _ in cases_for(family)
                      if name not in args.skip_cases and (args.full or name in compact[family])])
               for family, model in [('doubao', 'Doubao-Seed-2.1-pro-260628'),
                                      ('qwen', 'qwen3.8-max'), ('glm', 'glm-5.3')]]
    summary = {'reports': reports, 'claude_requests': 0, 'credential_name': credential_name,
               'total_requests': sum(len(r['runs']) for r in reports),
               'total_reported_tokens': sum(r['total_reported_tokens'] for r in reports)}
    serialized = json.dumps(summary, ensure_ascii=False, indent=2) + '\n'
    assert key not in serialized
    (args.output_dir / 'summary.json').write_text(serialized, encoding='utf-8')
    print(json.dumps({k: v for k, v in summary.items() if k != 'reports'}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--agent-config', required=True, type=Path)
    parser.add_argument('--output-dir', required=True, type=Path)
    parser.add_argument('--credential', choices=['project', 'personal'], help='Default: project')
    parser.add_argument('--full', action='store_true', help='Run every case rather than the compact route checks')
    parser.add_argument('--skip-cases', nargs='*', default=[], help='Explicitly omit already attempted cases')
    main(parser.parse_args())
