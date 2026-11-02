"""Verify saved live-model policy decisions against execution and audit output."""
import argparse
import copy
import json
import pathlib
from collections import Counter


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def json_bytes(value):
    return len(json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode())


def first_input_tokens(messages):
    usage = next(m['usage'] for m in messages if m['role'] == 'assistant')
    return sum(usage.get(k, 0) for k in ('input', 'cacheRead', 'cacheWrite'))


def normalize_policy_request(request, guideline=None, output_mode=None):
    stripped = copy.deepcopy(request)
    for tool in stripped['tools']:
        prefix = 'Include audit_policy on every call. Example: '
        description = tool['function']['description']
        if description.startswith(prefix):
            example, original = description[len(prefix):].split('\n', 1)
            assert json.loads(example)['audit_policy'] in ('raw', 'counts')
            tool['function']['description'] = original
        parameters = tool['function']['parameters']
        del parameters['properties']['audit_policy']
        parameters['required'].remove('audit_policy')
        if not parameters['required']:
            del parameters['required']
        if output_mode == 'reference' and tool['function']['name'] == 'read':
            del parameters['properties']['output_page']
    if guideline:
        systems = [m for m in stripped['messages'] if m['role'] in ('system', 'developer')]
        line = '- ' + guideline + '\n'
        assert sum(m['content'].count(line) for m in systems) == 1
        for message in systems:
            message['content'] = message['content'].replace(line, '', 1)
    return stripped


def verify(directory, baseline):
    agent = read(directory / 'agent-result.json')
    assert agent['controlMode'] == 'agent'
    assert all(agent['limits'][k] is None for k in ('turns', 'tools', 'tokens'))
    transcript = read(directory / 'transcript.json')
    proposed = {c['id']: c for m in transcript if m['role'] == 'assistant'
                for c in m.get('content', []) if c['type'] == 'toolCall'}
    stop_reasons = {c['id']: m.get('stopReason') for m in transcript if m['role'] == 'assistant'
                    for c in m.get('content', []) if c['type'] == 'toolCall'}
    results = {m['toolCallId']: m for m in transcript if m['role'] == 'toolResult'}
    metadata = [json.loads(line) for line in (directory / 'pi/calls.jsonl').read_text(encoding='utf-8').splitlines()]
    begins = {c['tool_call_id']: c for c in metadata if c['kind'] == 'begin'}
    refs = {c['call_ref']: c for c in begins.values()}
    assert len(refs) == len(begins)
    policy_ids = {'raw': 1, 'counts': 2}
    for identity, call in begins.items():
        source = proposed[identity]
        assert call['input'] == source['arguments']
        assert call['tool_name'] == source['name']
        assert call['policy_source'] == 'agent'
        assert call['policy_id'] == policy_ids[call['input']['audit_policy']]
    raw = Counter()
    for line in (directory / 'events.jsonl').read_text(encoding='utf-8').splitlines():
        event = json.loads(line)
        call = refs[event['call_ref']]
        assert event['policy_id'] == call['policy_id'] == 1
        assert event['tool_call_id'] == call['tool_call_id']
        raw[event['call_ref']] += 1
    counts = Counter()
    for row in read(directory / 'counts.json'):
        call = refs[row['call_ref']]
        assert row['policy_id'] == call['policy_id'] == 2
        assert row['tool_call_id'] == call['tool_call_id']
        counts[row['call_ref']] += row['count']
    rejected = []
    for identity, call in proposed.items():
        if identity in begins:
            continue
        result = results[identity]
        assert result['isError']
        text = '\n'.join(c.get('text', '') for c in result['content'])
        if stop_reasons[identity] == 'length' and 'output token limit' in text:
            rejection_kind = 'truncated_response'
        elif text.startswith('Set audit_policy'):
            rejection_kind = 'missing_policy' if 'audit_policy' not in call['arguments'] else 'invalid_policy'
        else:
            rejection_kind = 'invalid_arguments'
        rejected.append({'tool': call['name'],
                         'rejection_kind': rejection_kind,
                         'model_stop_reason': stop_reasons[identity],
                         'requested_policy': call['arguments'].get('audit_policy'),
                         'missing_policy': 'audit_policy' not in call['arguments'],
                         'error_bytes': len(text.encode('utf-8')),
                         'validation_error': text.split('\n\nReceived arguments:')[0]})
    requests = sorted(directory.glob('request-*.json'))
    assert len(requests) == agent['requests']
    for path in requests:
        request = read(path)
        assert request['max_completion_tokens'] == agent['maxOutputTokens']
        if agent.get('auditPolicyGuideline'):
            assert sum(m['content'].count(agent['auditPolicyGuideline'])
                       for m in request['messages'] if m['role'] in ('system', 'developer')) == 1
        assert len(request['tools']) == 7
        for tool in request['tools']:
            parameters = tool['function']['parameters']
            assert 'audit_policy' in parameters['required']
            assert parameters['properties']['audit_policy']['enum'] == ['raw', 'counts']
    events = [json.loads(line) for line in (directory / 'agent-events.jsonl').read_text(encoding='utf-8').splitlines()]
    assert not any(e['type'] == 'auto_retry_start' for e in events)
    report = {'task': directory.name, 'requests': len(requests),
              'model_tool_requests': len(proposed), 'executed_calls': len(begins),
              'policies': dict(Counter(c['input']['audit_policy'] for c in begins.values())),
              'rejected_calls': rejected, 'request_execution_output_match': True,
              'automatic_retry_events': 0,
              'calls': [{'tool': c['tool_name'], 'policy': c['input']['audit_policy'],
                         'raw_events': raw[c['call_ref']], 'counted_events': counts[c['call_ref']]}
                        for c in begins.values()]}
    if baseline:
        other = baseline / directory.name
        previous = read(other / 'request-1.json')
        current = read(directory / 'request-1.json')
        baseline_mode = read(other / 'agent-result.json').get('outputMode', 'inline')
        strip_output = agent.get('outputMode') if baseline_mode != agent.get('outputMode') else None
        stripped = normalize_policy_request(current, agent.get('auditPolicyGuideline'), strip_output)
        assert stripped == previous
        report['first_request_comparison'] = {
            'payload_equal_after_removing_policy_additions': normalize_policy_request(current, agent.get('auditPolicyGuideline')) == previous,
            'payload_equal_after_removing_adapter_additions': stripped == previous,
            'messages_equal': current['messages'] == previous['messages'],
            'shared_guideline': agent.get('auditPolicyGuideline'),
            'added_payload_bytes': json_bytes(current) - json_bytes(previous),
            'fixed_raw_input_tokens': first_input_tokens(read(other / 'transcript.json')),
            'agent_policy_input_tokens': first_input_tokens(transcript)}
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('results', type=pathlib.Path)
    parser.add_argument('--baseline', type=pathlib.Path)
    parser.add_argument('--output', type=pathlib.Path, required=True)
    args = parser.parse_args()
    report = {'runs': [verify(d, args.baseline) for d in sorted(args.results.iterdir())
                       if (d / 'summary.json').exists()]}
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'verified_trials': len(report['runs'])}))
