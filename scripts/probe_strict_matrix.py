"""Probe representative non-Claude iBrain models using their configured API protocols."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import copy
import json
from pathlib import Path
import re
import threading
import time
import urllib.error
import urllib.request

from probe_strict_support import probe_cases, response_body, violations
from test_credentials import get_ibrain_credential


MODELS = [
    'gpt-5.6-luna', 'gpt-5.6-sol', 'gpt-5.6-terra', 'gpt-6-astra',
    'gpt-6.1-sol', 'gpt-6.1-terra',
    'Deepseek-v4-pro-al', 'deepseek-v4.1-flash-al', 'self-innovate-DeepSeek-V4.1-Flash-public',
    'self-innovate-GLM-5.3-public', 'self-innovate-GLM-5.3-Flash-public', 'glm-5.3',
    'qwen3.8-max', 'qwen3.8-flash', 'self-innovate-Qwen3.8-Flash-Next-public',
    'gemini-3.1-pro-preview', 'gemini-3.8-flash',
    'Doubao-Seed-2.1-pro-260628', 'doubao-seed-2.1-lite-260915',
]
PRINT_LOCK = threading.Lock()
RATE_LOCK = threading.Lock()
NEXT_REQUEST = 0.0


def pace_request():
    global NEXT_REQUEST
    with RATE_LOCK:
        now = time.monotonic()
        wait = max(0, NEXT_REQUEST - now)
        NEXT_REQUEST = max(now, NEXT_REQUEST) + 2.6
    if wait:
        time.sleep(wait)


def emit(value):
    with PRINT_LOCK:
        print(json.dumps(value, ensure_ascii=False), flush=True)


def responses_body(response, streaming):
    items, body, terminal = {}, None, False
    if streaming:
        for line in response:
            line = line.decode('utf-8').strip()
            if not line.startswith('data:') or line[5:].strip() == '[DONE]':
                continue
            event = json.loads(line[5:].strip())
            kind = event.get('type', '')
            if kind == 'response.output_item.done':
                items[event['output_index']] = event['item']
            elif kind in ('response.completed', 'response.incomplete', 'response.failed'):
                body = event['response']
                terminal = True
            elif kind == 'error':
                detail = event.get('error') or event
                return {'remote_error': True, 'error_type': detail.get('type'),
                        'error_code': detail.get('code'),
                        'error_message': detail.get('message'), 'tool_calls': []}
        if body is None:
            body = {'output': [items[k] for k in sorted(items)], 'status': 'stream_without_terminal_event'}
    else:
        body = json.load(response)
        terminal = body.get('status') in ('completed', 'incomplete', 'failed')
    calls, text = [], []
    for item in body.get('output', []):
        if item.get('type') == 'function_call':
            calls.append({'name': item.get('name'), 'arguments_text': item.get('arguments', '')})
        elif item.get('type') == 'message':
            text.extend(c.get('text', c.get('refusal', '')) for c in item.get('content', []))
    status = body.get('status')
    details = body.get('incomplete_details')
    finish = 'tool_calls' if calls else 'stop'
    if status != 'completed':
        finish = 'length' if (details or {}).get('reason') == 'max_output_tokens' else status
    result = {'tool_calls': calls, 'finish_reason': finish, 'response_status': status,
              'terminal_response_observed': terminal, 'incomplete_details': details,
              'usage': body.get('usage'), 'text': '\n'.join(text), 'refusal': False}
    if body.get('error'):
        result.update(remote_error=True, error_type=body['error'].get('code'),
                      error_message=body['error'].get('message'))
    return result


def make_request(model, api, tokens, reasoning, case, schema):
    name, strict, streaming, prompt, bad_schema = case
    parameters = copy.deepcopy(schema)
    if bad_schema:
        parameters['required'].append('undefined_required_field')
    function = {'name': 'audit_probe', 'description': 'Tool schema capability probe.',
                'strict': strict, 'parameters': parameters}
    payload = {'model': model, 'stream': streaming, 'parallel_tool_calls': False}
    if api == 'openai-responses':
        payload.update(input=[{'role': 'user', 'content': prompt}], store=False,
                       max_output_tokens=tokens, tools=[{'type': 'function', **function}])
        if reasoning:
            payload['reasoning'] = {'effort': 'medium'}
    else:
        payload.update(messages=[{'role': 'user', 'content': prompt}], max_tokens=tokens,
                       tools=[{'type': 'function', 'function': function}])
        if streaming:
            payload['stream_options'] = {'include_usage': True}
        if reasoning:
            payload['reasoning_effort'] = 'medium'
    return parameters, payload


def classify(report):
    runs = report['runs']
    valid = [r for r in runs if r['strict_requested'] and not r['invalid_schema']]
    completed = [r for r in valid if r.get('status') == 200 and not r.get('remote_error')
                 and r.get('finish_reason') in ('tool_calls', 'stop')]
    counterexamples = [r['case'] for r in completed if r.get('schema_violated')]
    invalid = next((r for r in runs if r['invalid_schema']), {})
    message = str(invalid.get('error_message') or '').lower()
    schema_rejected = bool((invalid.get('status') in (400, 422) or invalid.get('remote_error'))
                           and any(s in message for s in ('schema', 'required', 'property', 'properties')))
    if counterexamples:
        verdict = 'strict_counterexample'
    elif len(completed) == 4 and all(r.get('tool_calls') for r in completed) and schema_rejected:
        verdict = 'passed_observed_cases'
    elif valid and all(r.get('http_error') or r.get('remote_error') for r in valid):
        verdict = 'request_rejected'
    else:
        verdict = 'inconclusive'
    return {'verdict': verdict, 'strict_counterexamples': counterexamples,
            'valid_strict_requests': len(valid), 'completed_valid_strict_requests': len(completed),
            'schema_validation_rejection_observed': schema_rejected,
            'no_tool_call_cases': [r['case'] for r in completed if not r.get('tool_calls')],
            'total_reported_tokens': sum((r.get('usage') or {}).get('total_tokens', 0) for r in runs)}


def probe_model(model_id, entry, settings, key, out_dir, resume_from=None):
    assert 'claude' not in model_id.lower() and 'anthropic' not in model_id.lower()
    configured = next((m for m in entry['models'] if m['id'] == model_id), {})
    is_gpt = model_id.startswith('gpt-')
    api = configured.get('api', entry['api']) if configured else 'openai-completions'
    root = next(m['baseUrl'] for m in entry['models'] if m.get('api') == 'openai-completions')
    base = configured.get('baseUrl', entry['baseUrl'] if configured else root).rstrip('/')
    suffix = '/responses' if api == 'openai-responses' else '/chat/completions'
    endpoint = base + suffix
    tokens = configured.get('maxTokens', 4096 if is_gpt else 2048)
    reasoning = configured.get('reasoning', is_gpt)
    report = {'model': model_id, 'api': api, 'route': 'direct' if '/proxy/direct/' in base else 'root',
              'max_response_tokens': tokens, 'reasoning_effort': 'medium' if reasoning else 'omitted',
              'executed_business_tools': 0, 'runs': []}
    schema, cases = probe_cases()
    path = out_dir / (re.sub(r'[^a-zA-Z0-9_.-]', '_', model_id) + '.json')
    assert not path.exists(), 'Use a fresh output directory'
    previous = {}
    if resume_from and (resume_from / path.name).exists():
        previous_report = json.loads((resume_from / path.name).read_text(encoding='utf-8'))
        if previous_report['api'] == api and previous_report['route'] == report['route']:
            previous = {r['case']: r for r in previous_report['runs']}
    for case in cases:
        name, strict, streaming, prompt, bad_schema = case
        old = previous.get(name, {})
        if (old.get('status') == 200 and not old.get('remote_error') and
                old.get('finish_reason') in ('tool_calls', 'stop')) or (
                bad_schema and (old.get('status') in (400, 422) or old.get('remote_error')) and
                any(w in str(old.get('error_message') or '').lower() for w in ('schema', 'required', 'property'))):
            row = copy.deepcopy(old)
            row['reused_completed_result'] = True
            report['runs'].append(row)
            report['summary'] = classify(report)
            path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            emit({'model': model_id, 'case': name, 'reused_completed_result': True})
            continue
        parameters, payload = make_request(model_id, api, tokens, reasoning, case, schema)
        row = {'case': name, 'strict_requested': strict, 'streaming': streaming,
               'invalid_schema': bad_schema, 'request': payload}
        request = urllib.request.Request(endpoint, data=json.dumps(payload).encode(),
                  headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
        pace_request()
        started = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                row['status'] = response.status
                row.update(responses_body(response, streaming) if api == 'openai-responses' else response_body(response, streaming))
            for call in row.get('tool_calls', []):
                try:
                    call['arguments'] = json.loads(call['arguments_text'])
                    call['violations'] = violations(call['arguments'], parameters)
                except (TypeError, json.JSONDecodeError):
                    call['violations'] = ['invalid_json']
            row['schema_violated'] = any(c['violations'] for c in row.get('tool_calls', []))
        except urllib.error.HTTPError as error:
            row.update(status=error.code, http_error=True)
            raw = error.read().decode('utf-8', errors='replace')
            try:
                detail = json.loads(raw).get('error') or {}
                row.update(error_type=detail.get('type'), error_code=detail.get('code'),
                           error_message=str(detail.get('message', '')))
            except (ValueError, AttributeError):
                row['error_message'] = raw[:1000]
        except Exception as error:
            row.update(status=None, error_type=type(error).__name__)
        if row.get('error_message'):
            row['error_message'] = re.sub(r'https?://[^\s"<>]+', '[endpoint]',
                                         row['error_message'].replace(key, '[redacted]'))[:1500]
        row['elapsed_sec'] = time.monotonic() - started
        report['runs'].append(row)
        report['summary'] = classify(report)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        emit({'model': model_id, 'case': name, 'status': row.get('status'),
              'finish_reason': row.get('finish_reason'), 'calls': len(row.get('tool_calls', [])),
              'violations': [c['violations'] for c in row.get('tool_calls', [])],
              'error_type': row.get('error_type'), 'elapsed_sec': round(row['elapsed_sec'], 2)})
    emit({'model': model_id, **report['summary']})
    return report


def main(args):
    assert not args.output_dir.exists(), 'Use a fresh output directory'
    read = lambda name: json.loads((args.agent_config / name).read_text(encoding='utf-8'))
    settings = read('settings.json')
    entry = read('models.json')['providers']['ibrain']
    key, credential_name = get_ibrain_credential(args.credential)
    args.output_dir.mkdir(parents=True)
    models = args.models or MODELS
    assert all('claude' not in m.lower() and 'anthropic' not in m.lower() for m in models)
    reports = {}
    if args.initial_wait:
        emit({'initial_cooldown_seconds': args.initial_wait})
        time.sleep(args.initial_wait)
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(probe_model, m, entry, settings, key, args.output_dir, args.resume_from): m for m in models}
        for future in as_completed(futures):
            model = futures[future]
            reports[model] = future.result()
    report = {'provider': 'ibrain', 'models': [reports[m] for m in models],
              'credential_name': credential_name,
              'scope': 'Direct API, three concurrent models, globally spaced requests (2.6 seconds), no business tool execution or argument repair',
              'selected_model_count': len(models), 'claude_requests': 0,
              'total_requests': sum(len(r['runs']) for r in reports.values()),
              'reused_completed_results': sum(bool(r.get('reused_completed_result')) for m in reports.values() for r in m['runs']),
              'total_reported_tokens': sum(r['summary']['total_reported_tokens'] for r in reports.values())}
    serialized = json.dumps(report, ensure_ascii=False, indent=2) + '\n'
    assert key not in serialized
    (args.output_dir / 'summary.json').write_text(serialized, encoding='utf-8')
    emit({k: v for k, v in report.items() if k != 'models'})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--agent-config', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--models', nargs='+', help='Override the representative model selection; Claude is excluded')
    parser.add_argument('--resume-from', type=Path, help='Reuse completed responses; rerun only infrastructure failures or interrupted cases')
    parser.add_argument('--initial-wait', type=int, default=0, help='Cooldown before requests')
    parser.add_argument('--credential', choices=['project', 'personal'], help='Default: project')
    main(parser.parse_args())
