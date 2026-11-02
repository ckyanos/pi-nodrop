"""Compare fresh baseline, fixed-raw and tool-name policy trials."""
import argparse
from collections import Counter
import json
import pathlib

from compare_live_modes import load
from verify_live_agent_policy import first_input_tokens, json_bytes, read
from verify_policy_names import verify

MODES = ('baseline', 'fixed-raw', 'agent-names')


def messages(directory):
    if (directory / 'transcript.json').exists():
        return read(directory / 'transcript.json')
    events = [json.loads(line) for line in (directory / 'agent-events.jsonl').read_text(encoding='utf-8').splitlines()]
    return [message for event in events if event['type'] == 'turn_end'
            for message in [event['message'], *event['toolResults']]]


def trial(directory, mode):
    summary = read(directory / 'summary.json')
    transcript = messages(directory)
    assistants = [m for m in transcript if m['role'] == 'assistant']
    calls = [c for m in assistants for c in m.get('content', []) if c['type'] == 'toolCall']
    metadata = [json.loads(line) for line in (directory / 'pi/calls.jsonl').read_text(encoding='utf-8').splitlines()]
    begins = [c for c in metadata if c['kind'] == 'begin']
    completed = (directory / 'agent-result.json').exists()
    events = [json.loads(line) for line in (directory / 'agent-events.jsonl').read_text(encoding='utf-8').splitlines()]
    assert not any(e['type'] == 'auto_retry_start' for e in events)
    if completed:
        result = load(directory, mode)
        agent = read(directory / 'agent-result.json')
        result['session_completed'] = summary['agent_exit_code'] == 0 and agent['stop'] is None and agent['error'] is None
    else:
        indexes = [read(p) for p in (directory / 'pi/outputs').glob('*/index.json')]
        usage = {k: sum(m.get('usage', {}).get(k, 0) for m in assistants)
                 for k in ('input', 'output', 'cacheRead', 'cacheWrite')}
        result = {'mode': mode, 'task': summary['task'], 'task_passed': bool(summary['reward']),
                  'tests': read(directory / 'ctrf.json')['results']['summary'],
                  'session_completed': False, 'total_tokens': sum(m.get('usage', {}).get('totalTokens', 0) for m in assistants),
                  'usage': usage, 'requests': len(list(directory.glob('request-*.json'))),
                  'model_tool_requests': len(calls), 'audit_calls': summary['calls'],
                  'raw_events': summary['raw_events'], 'histogram_events': summary['histogram_events'],
                  'audit_bytes': sum(p.stat().st_size for p in (directory / 'audit').iterdir() if p.suffix == '.buf' or p.name.endswith('.counts.jsonl')),
                  'metadata_bytes': (directory / 'pi/calls.jsonl').stat().st_size,
                  'stored_outputs': len(indexes), 'stored_output_bytes': sum(i['bytes'] for i in indexes),
                  'tool_result_text_chars': sum(len(c.get('text', '')) for m in transcript if m['role'] == 'toolResult' for c in m['content']),
                  'first_input_tokens': first_input_tokens(transcript),
                  'instruction_sha256': summary['instruction_sha256'], 'cleanup': read(directory / 'cleanup.json')}
    result.update({'final_result_recorded': completed, 'agent_exit_code': summary['agent_exit_code'],
                   'token_measurement': 'final session usage' if completed else 'completed turn records; partial',
                   'trial_elapsed_sec': summary['elapsed_sec'], 'environment': summary['environment'],
                   'statistics': summary['statistics'],
                   'policy_counts': dict(Counter({1: 'raw', 2: 'counts'}[c['policy_id']] for c in begins)),
                   'output_page_requests': sum(c['name'] in ('read', 'read_raw', 'read_counts') and 'output_page' in c['arguments'] for c in calls)})
    assert summary['audit'] == ('off' if mode == 'baseline' else 'on')
    assert {c['tool_call_id'] for c in begins} == {c['tool_call_id'] for c in metadata if c['kind'] == 'end'}
    if mode == 'baseline':
        assert not begins and not summary['raw_events'] and not summary['histogram_events']
    elif mode == 'fixed-raw':
        assert all(c['policy_id'] == 1 for c in begins)
        assert not summary['histogram_events']
        refs = {c['call_ref']: c for c in begins}
        for line in (directory / 'events.jsonl').read_text(encoding='utf-8').splitlines():
            event = json.loads(line)
            assert event['policy_id'] == 1 and refs[event['call_ref']]['tool_call_id'] == event['tool_call_id']
    return result


def compare(root):
    tasks = {mode: {p.name for p in (root / mode).iterdir() if (p / 'summary.json').exists()} for mode in MODES}
    assert len(tasks['baseline']) == 3 and all(t == tasks['baseline'] for t in tasks.values())
    pairs = []
    checks = []
    for task in sorted(tasks['baseline']):
        runs = {mode: trial(root / mode / task, mode) for mode in MODES}
        payloads = {mode: read(root / mode / task / 'request-1.json') for mode in MODES}
        assert payloads['baseline'] == payloads['fixed-raw']
        assert len({r['instruction_sha256'] for r in runs.values()}) == 1
        checked = verify(root / 'agent-names' / task, root / 'fixed-raw')
        checks.append(checked)
        pairs.append({'task': task, 'runs': runs, 'first_request_checks': {
            'baseline_equals_fixed_raw': True,
            'business_parameters_reused': checked['first_request_comparison']['business_parameters_reused'],
            'model_options_equal': checked['first_request_comparison']['model_options_equal'],
            'user_messages_equal': checked['first_request_comparison']['user_messages_equal'],
            'policy_input_tokens': runs['agent-names']['first_input_tokens'] - runs['baseline']['first_input_tokens'],
            'policy_payload_bytes': json_bytes(payloads['agent-names']) - json_bytes(payloads['baseline'])}})
    totals = {}
    for mode in MODES:
        runs = [p['runs'][mode] for p in pairs]
        keys = ('total_tokens', 'requests', 'model_tool_requests', 'audit_calls', 'raw_events',
                'histogram_events', 'audit_bytes', 'metadata_bytes', 'stored_outputs',
                'stored_output_bytes', 'output_page_requests', 'tool_result_text_chars', 'trial_elapsed_sec')
        totals[mode] = {k: sum(r[k] for r in runs) for k in keys}
        totals[mode].update({'passed_tasks': sum(r['task_passed'] for r in runs),
                             'completed_sessions': sum(r['session_completed'] for r in runs),
                             'all_usage_final': all(r['final_result_recorded'] for r in runs),
                             'policy_counts': dict(sum((Counter(r['policy_counts']) for r in runs), Counter()))})
    comparisons = {}
    for candidate, reference in (('fixed-raw', 'baseline'), ('agent-names', 'baseline'), ('agent-names', 'fixed-raw')):
        value, base = totals[candidate], totals[reference]
        comparable = value['completed_sessions'] == base['completed_sessions'] == 3
        comparisons[candidate + '_vs_' + reference] = {'complete_sessions_comparable': comparable,
            'token_delta': value['total_tokens'] - base['total_tokens'] if comparable else None,
            'token_delta_percent': 100 * (value['total_tokens'] / base['total_tokens'] - 1) if comparable else None}
    runtime = {mode: read(root / mode / 'runtime.json') for mode in MODES}
    assert all(r == runtime['baseline'] for r in runtime.values())
    return {'design': {'replicates_per_task_per_mode': 1, 'fresh_trials': 9,
                       'execution': 'independent live-model runs', 'control_mode': 'agent-names',
                       'local_token_turn_tool_limits': None, 'automatic_retries': False, 'automatic_reruns': False},
            'pairs': pairs, 'totals': totals, 'comparisons': comparisons,
            'policy_verification': {'runs': checks}, 'runtime_sha256': runtime,
            'environment_cleanup': {mode: read(root / mode / 'environment-cleanup.json') for mode in MODES}}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('results', type=pathlib.Path)
    parser.add_argument('--output', required=True, type=pathlib.Path)
    args = parser.parse_args()
    report = compare(args.results)
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'totals': report['totals'], 'comparisons': report['comparisons']}))
