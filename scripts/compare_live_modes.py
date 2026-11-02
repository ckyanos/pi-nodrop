"""Compare independent live-model modes with matching tasks and model settings."""
import argparse
import json
import pathlib
from collections import Counter
from verify_live_agent_policy import first_input_tokens, json_bytes, normalize_policy_request, read


def load(directory, mode):
    summary = read(directory / 'summary.json')
    agent = read(directory / 'agent-result.json')
    cleanup = read(directory / 'cleanup.json')
    assert cleanup['module_unloaded'] and not cleanup['kernel_errors']
    messages = read(directory / 'transcript.json')
    tests = read(directory / 'ctrf.json')['results']['summary']
    assistants = [m for m in messages if m['role'] == 'assistant']
    thinking_chars = sum(len(c.get('thinking', '')) for m in assistants
                         for c in m.get('content', []) if c['type'] == 'thinking')
    message_bytes = Counter()
    for path in directory.glob('request-*.json'):
        for message in read(path)['messages']:
            message_bytes[message['role']] += json_bytes(message)
    assert sum(m['usage']['totalTokens'] for m in assistants) == agent['totalTokens']
    assert all(sum(m['usage'].get(key, 0) for m in assistants) == value
               for key, value in agent['usage'].items())
    tool_calls = [c for m in messages if m['role'] == 'assistant'
                  for c in m.get('content', []) if c['type'] == 'toolCall']
    tool_result_sizes = [sum(len(c.get('text', '')) for c in m.get('content', []) if c.get('type') == 'text')
                         for m in messages if m['role'] == 'toolResult']
    assert all(agent['limits'][key] is None for key in ('tokens', 'turns', 'tools'))
    assert agent['requests'] == len(list(directory.glob('request-*.json')))
    events = [json.loads(line) for line in (directory / 'agent-events.jsonl').read_text(encoding='utf-8').splitlines()]
    assert not any(event['type'] == 'auto_retry_start' for event in events)
    assert summary['audit'] == ('off' if mode == 'baseline' else 'on')
    if mode != 'baseline':
        assert agent['controlMode'] == ('agent' if mode == 'agent-before' else mode)
    raw_bytes = sum(p.stat().st_size for p in (directory / 'audit').glob('*.buf'))
    counts_bytes = sum(p.stat().st_size for p in (directory / 'audit').glob('*.counts.jsonl'))
    index_paths = list((directory / 'pi/outputs').glob('*/index.json'))
    indexes = [read(p) for p in index_paths]
    call_records = [json.loads(line) for line in (directory / 'pi/calls.jsonl').read_text(encoding='utf-8').splitlines()]
    audit_refs = {c['call_ref'] for c in call_records if c['kind'] == 'begin'}
    shown_results = {m['toolCallId']: m for m in messages if m['role'] == 'toolResult'}
    original_text_chars = sum(tool_result_sizes)
    for path, index in zip(index_paths, indexes):
        assert index['output_ref'] == path.parent.name
        assert (path.parent / 'output.txt').stat().st_size == index['bytes']
        assert index['tool_call_id'] in {c['id'] for c in tool_calls}
        assert index['call_ref'] is None if mode == 'baseline' else index['call_ref'] in audit_refs
        original = read(path.parent / 'result.json')
        shown = shown_results[index['tool_call_id']]
        original_text_chars += sum(len(c.get('text', '')) for c in original['content'] if c['type'] == 'text')
        original_text_chars -= sum(len(c.get('text', '')) for c in shown['content'] if c['type'] == 'text')
    return {'mode': mode, 'task': summary['task'], 'task_passed': bool(summary['reward']),
            'tests': tests,
            'cleanup': cleanup,
            'provider': agent['provider'], 'model': agent['model'], 'api': agent['api'],
            'max_output_tokens': agent['maxOutputTokens'],
            'limits': agent['limits'], 'stop': agent['stop'], 'error': agent['error'],
            'instruction_sha256': summary['instruction_sha256'],
            'total_tokens': agent['totalTokens'], 'usage': agent['usage'],
            'first_input_tokens': first_input_tokens(messages), 'requests': agent['requests'],
            'model_tool_requests': len(tool_calls),
            'assistant_thinking_chars': thinking_chars,
            'request_message_json_bytes_by_role': dict(message_bytes),
            'tool_result_text_chars': sum(tool_result_sizes),
            'original_tool_result_text_chars': original_text_chars,
            'largest_tool_result_text_chars': max(tool_result_sizes, default=0),
            'tool_counts': dict(Counter(c['name'] for c in tool_calls)),
            'model_policy_choices': dict(Counter(c['arguments'].get('audit_policy', 'missing')
                                                for c in tool_calls)) if mode in ('agent', 'agent-before') else None,
            'shared_guideline': agent.get('auditPolicyGuideline'),
            'output_mode': agent.get('outputMode', 'inline'),
            'output_inline_bytes': agent.get('outputInlineBytes'),
            'stored_outputs': len(indexes),
            'stored_output_bytes': sum(index['bytes'] for index in indexes),
            'output_page_requests': sum(c['name'] == 'read' and 'output_page' in c['arguments'] for c in tool_calls),
            'audit_calls': summary['calls'], 'raw_events': summary['raw_events'],
            'histogram_events': summary['histogram_events'], 'raw_bytes': raw_bytes,
            'counts_bytes': counts_bytes, 'audit_bytes': raw_bytes + counts_bytes,
            'metadata_bytes': (directory / 'pi/calls.jsonl').stat().st_size,
            'agent_elapsed_sec': agent['elapsedSec'],
            'drop_unsolved': summary['statistics']['drop_unsolved']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', required=True, type=pathlib.Path)
    parser.add_argument('--fixed-raw', required=True, type=pathlib.Path)
    parser.add_argument('--agent', required=True, type=pathlib.Path)
    parser.add_argument('--previous-agent', type=pathlib.Path)
    parser.add_argument('--output', required=True, type=pathlib.Path)
    args = parser.parse_args()
    sources = {'baseline': args.baseline, 'fixed-raw': args.fixed_raw, 'agent': args.agent}
    if args.previous_agent:
        sources['agent-before'] = args.previous_agent
    tasks = {mode: {d.name for d in root.iterdir() if (d / 'summary.json').exists()}
             for mode, root in sources.items()}
    assert all(value == tasks['baseline'] for value in tasks.values())
    pairs = []
    for task in sorted(tasks['baseline']):
        runs = {mode: load(root / task, mode) for mode, root in sources.items()}
        for key in ('provider', 'model', 'api', 'max_output_tokens', 'limits', 'instruction_sha256'):
            assert len({json.dumps(run[key], sort_keys=True) for run in runs.values()}) == 1, (task, key)
        payloads = {mode: read(root / task / 'request-1.json') for mode, root in sources.items()}
        for key in ('output_mode', 'output_inline_bytes'):
            assert len({runs[mode][key] for mode in ('baseline', 'fixed-raw', 'agent')}) == 1, (task, key)
        assert payloads['baseline'] == payloads['fixed-raw'], task
        for mode in sources.keys() - {'baseline', 'fixed-raw'}:
            strip_output = runs[mode]['output_mode'] if runs['baseline']['output_mode'] != runs[mode]['output_mode'] else None
            assert normalize_policy_request(payloads[mode], runs[mode]['shared_guideline'], strip_output) == payloads['baseline'], task
        assert runs['baseline']['first_input_tokens'] == runs['fixed-raw']['first_input_tokens']
        pairs.append({'task': task, 'runs': runs,
                      'first_request_checks': {'baseline_equals_fixed_raw': True,
                          'agent_equals_baseline_after_removing_policy_additions': True,
                          'policy_payload_bytes': json_bytes(payloads['agent']) - json_bytes(payloads['baseline']),
                          'policy_input_tokens': runs['agent']['first_input_tokens'] - runs['baseline']['first_input_tokens']}})
    totals = {}
    for mode in sources:
        runs = [p['runs'][mode] for p in pairs]
        keys = ('total_tokens', 'requests', 'model_tool_requests', 'audit_calls', 'raw_events',
                'histogram_events', 'raw_bytes', 'counts_bytes', 'audit_bytes', 'metadata_bytes',
                'agent_elapsed_sec', 'drop_unsolved', 'tool_result_text_chars',
                'stored_outputs', 'stored_output_bytes', 'output_page_requests', 'original_tool_result_text_chars')
        totals[mode] = {key: sum(run[key] for run in runs) for key in keys}
        totals[mode]['passed_tasks'] = sum(run['task_passed'] for run in runs)
        totals[mode]['usage'] = {key: sum(run['usage'][key] for run in runs)
                               for key in ('input', 'output', 'cacheRead', 'cacheWrite')}
    comparisons = {}
    for candidate, reference in [('fixed-raw', 'baseline'), ('agent', 'baseline'), ('agent', 'fixed-raw')]:
        value, base = totals[candidate], totals[reference]
        comparisons[candidate + '_vs_' + reference] = {
            'token_delta': value['total_tokens'] - base['total_tokens'],
            'token_delta_percent': 100 * (value['total_tokens'] / base['total_tokens'] - 1)}
    if args.previous_agent:
        value, base = totals['agent'], totals['agent-before']
        comparisons['agent_vs_agent-before'] = {
            'token_delta': value['total_tokens'] - base['total_tokens'],
            'token_delta_percent': 100 * (value['total_tokens'] / base['total_tokens'] - 1)}
    report = {'design': {'replicates_per_task_per_mode': 1,
                        'execution': 'independent live-model runs',
                        'local_token_turn_tool_limits': None},
              'pairs': pairs, 'totals': totals, 'comparisons': comparisons,
              'runtime_sha256': {mode: read(root / 'runtime.json') for mode, root in sources.items()},
              'environment_cleanup': {mode: read(root / 'environment-cleanup.json') for mode, root in sources.items()}}
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'totals': totals, 'comparisons': comparisons}))
