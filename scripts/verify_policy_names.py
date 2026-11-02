"""Verify policy choices encoded in model tool names against NoDrop records."""
import argparse
from collections import Counter
import json
import pathlib
from verify_live_agent_policy import first_input_tokens, json_bytes, read

BUSINESS = ('bash', 'read', 'write', 'edit', 'grep', 'find', 'ls')
NAMES = {f'{tool}_{policy}' for tool in BUSINESS for policy in ('raw', 'counts')}


def selection(name):
    if name not in NAMES:
        return None
    tool, policy = name.rsplit('_', 1)
    return tool, policy, {'raw': 1, 'counts': 2}[policy]


def verify(directory, baseline):
    paths = list(directory.glob('request-*.json'))
    summary = read(directory / 'summary.json')
    event_records = [json.loads(line) for line in (directory / 'agent-events.jsonl').read_text(encoding='utf-8').splitlines()]
    completed = (directory / 'agent-result.json').exists()
    if completed:
        agent = read(directory / 'agent-result.json')
        messages = read(directory / 'transcript.json')
        assert all(agent['limits'][key] is None for key in ('tokens', 'turns', 'tools'))
    else:
        first = read(directory / 'request-1.json')
        messages = [message for event in event_records if event['type'] == 'turn_end'
                    for message in [event['message'], *event['toolResults']]]
        guidelines = [line[2:] for m in first['messages'] if m['role'] in ('system', 'developer')
                      for line in m['content'].splitlines() if line.startswith('- Choose the _raw or _counts variant')]
        assert len(guidelines) == 1
        agent = {'controlMode': summary['control_mode'], 'requests': len(paths),
                 'maxOutputTokens': first['max_completion_tokens'], 'auditPolicyGuideline': guidelines[0]}
    assert agent['controlMode'] == 'agent-names'
    proposed = {c['id']: c for m in messages if m['role'] == 'assistant'
                for c in m.get('content', []) if c['type'] == 'toolCall'}
    stops = {c['id']: m.get('stopReason') for m in messages if m['role'] == 'assistant'
             for c in m.get('content', []) if c['type'] == 'toolCall'}
    results = {m['toolCallId']: m for m in messages if m['role'] == 'toolResult'}
    metadata = [json.loads(line) for line in (directory / 'pi/calls.jsonl').read_text(encoding='utf-8').splitlines()]
    begins = {c['tool_call_id']: c for c in metadata if c['kind'] == 'begin'}
    ends = {c['tool_call_id']: c for c in metadata if c['kind'] == 'end'}
    assert begins.keys() == ends.keys()
    refs = {c['call_ref']: c for c in begins.values()}
    assert len(refs) == len(begins)
    for identity, call in begins.items():
        source = proposed[identity]
        tool, policy, number = selection(source['name'])
        assert call['model_tool_name'] == source['name']
        assert call['tool_name'] == tool and call['policy_id'] == number
        assert call['policy_source'] == 'agent-names'
        assert call['input'] == source['arguments'] and 'audit_policy' not in source['arguments']
    raw = Counter()
    for line in (directory / 'events.jsonl').read_text(encoding='utf-8').splitlines():
        event = json.loads(line); call = refs[event['call_ref']]
        assert event['policy_id'] == call['policy_id'] == 1
        assert event['tool_call_id'] == call['tool_call_id']
        raw[event['call_ref']] += 1
    counts = Counter()
    for event in read(directory / 'counts.json'):
        call = refs[event['call_ref']]
        assert event['policy_id'] == call['policy_id'] == 2
        assert event['tool_call_id'] == call['tool_call_id']
        counts[event['call_ref']] += event['count']
    rejected = []
    for identity, call in proposed.items():
        if identity in begins:
            continue
        result = results[identity]; assert result['isError']
        text = '\n'.join(c.get('text', '') for c in result['content'])
        kind = ('truncated_response' if stops[identity] == 'length' and 'output token limit' in text
                else 'unknown_tool_name' if selection(call['name']) is None
                else 'conflicting_policy_field' if 'audit_policy' in call['arguments'] else 'invalid_arguments')
        rejected.append({'tool': call['name'], 'rejection_kind': kind, 'model_stop_reason': stops[identity],
                         'error_bytes': len(text.encode()),
                         'validation_error': text.split('\n\nReceived arguments:')[0]})
    assert len(paths) == agent['requests']
    for path in paths:
        request = read(path)
        assert request['max_completion_tokens'] == agent['maxOutputTokens']
        assert {t['function']['name'] for t in request['tools']} == NAMES and len(request['tools']) == 14
        for tool in request['tools']:
            assert 'audit_policy' not in tool['function']['parameters']['properties']
        assert sum(m['content'].count(agent['auditPolicyGuideline']) for m in request['messages']
                   if m['role'] in ('system', 'developer')) == 1
    assert not any(e['type'] == 'auto_retry_start' for e in event_records)
    report = {'task': directory.name, 'model_tool_requests': len(proposed), 'executed_calls': len(begins),
              'final_result_recorded': completed, 'agent_exit_code': summary['agent_exit_code'],
              'message_source': 'transcript.json' if completed else 'completed turn_end records in agent-events.jsonl',
              'recorded_requests': len(paths),
              'recorded_total_tokens': sum(m.get('usage', {}).get('totalTokens', 0) for m in messages if m['role'] == 'assistant'),
              'policies': dict(Counter(selection(c['model_tool_name'])[1] for c in begins.values())),
              'rejected_calls': rejected, 'request_execution_output_match': True,
              'automatic_retry_events': 0,
              'calls': [{'model_tool': c['model_tool_name'], 'business_tool': c['tool_name'],
                         'policy': selection(c['model_tool_name'])[1],
                         'raw_events': raw[c['call_ref']], 'counted_events': counts[c['call_ref']]}
                        for c in begins.values()]}
    if baseline:
        other = baseline / directory.name
        previous, current = read(other / 'request-1.json'), read(directory / 'request-1.json')
        base_tools = {t['function']['name']: t['function'] for t in previous['tools']}
        for tool in current['tools']:
            definition = tool['function']; base, policy, _ = selection(definition['name'])
            assert definition['parameters'] == base_tools[base]['parameters']
            assert definition['description'].split('\n', 1)[1] == base_tools[base]['description']
        assert {k: v for k, v in previous.items() if k not in ('tools', 'messages')} == {
            k: v for k, v in current.items() if k not in ('tools', 'messages')}
        assert [m for m in previous['messages'] if m['role'] == 'user'] == [
            m for m in current['messages'] if m['role'] == 'user']
        report['first_request_comparison'] = {
            'business_parameters_reused': True, 'model_options_equal': True, 'user_messages_equal': True,
            'tool_count': 14, 'baseline_tool_count': len(previous['tools']),
            'tools_json_bytes': json_bytes(current['tools']), 'baseline_tools_json_bytes': json_bytes(previous['tools']),
            'added_payload_bytes': json_bytes(current) - json_bytes(previous),
            'fixed_raw_input_tokens': first_input_tokens(read(other / 'transcript.json')),
            'policy_names_input_tokens': first_input_tokens(messages)}
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
