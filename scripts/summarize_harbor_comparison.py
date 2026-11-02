"""Verify Harbor Pi trial records and summarize native token accounting."""
import argparse
from collections import Counter
import json
from pathlib import Path

from harbor.agents.installed.pi import Pi
from decode import decode_file, schema

MODES = ['baseline', 'fixed-raw', 'agent', 'agent-names']
TASKS = ['openssl-selfsigned-cert', 'log-summary-date-ranges', 'fix-git']


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def lines(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def trial(root, mode, task):
    job_name = mode + '--' + task
    job = root / job_name
    paths = list(job.glob('*/result.json'))
    assert len(paths) == 1, job_name
    directory = paths[0].parent
    result = read(paths[0])
    sessions = list((directory / 'agent/pi/sessions').glob('*.jsonl'))
    assert len(sessions) <= 1
    events = Pi._active_session_events(list(enumerate(lines(sessions[0]), 1))) if sessions else []
    messages = [e['message'] for _, e in events if e.get('type') == 'message']
    assistants = [m for m in messages if m.get('role') == 'assistant']
    calls = {c['id']: c for m in assistants for c in m.get('content', []) if c['type'] == 'toolCall'}
    tool_results = {m['toolCallId']: m for m in messages if m.get('role') == 'toolResult'}
    usage = {key: sum(m.get('usage', {}).get(key, 0) for m in assistants)
             for key in ['input', 'output', 'cacheRead', 'cacheWrite', 'totalTokens']}
    assert usage['totalTokens'] == sum(usage[key] for key in ['input', 'output', 'cacheRead', 'cacheWrite'])
    context = result.get('agent_result')
    if context:
        assert context['n_input_tokens'] == usage['input'] + usage['cacheRead'] + usage['cacheWrite']
        assert context['n_output_tokens'] == usage['output'] and context['n_cache_tokens'] == usage['cacheRead']
    metadata_path = directory / 'agent/nodrop/calls.jsonl'
    metadata = lines(metadata_path) if metadata_path.exists() else []
    begins = {c['tool_call_id']: c for c in metadata if c['kind'] == 'begin'}
    ends = {c['tool_call_id']: c for c in metadata if c['kind'] == 'end'}
    assert begins.keys() == ends.keys()
    refs = {c['call_ref']: c for c in begins.values()}
    assert len(refs) == len(begins)
    for identity, item in begins.items():
        proposed = calls[identity]
        assert proposed['arguments'] == item['input']
        assert item['policy_source'] == mode
        if mode == 'agent-names':
            tool, policy = proposed['name'].rsplit('_', 1)
            assert tool in ['read', 'bash', 'edit', 'write'] and policy in ['raw', 'counts']
            assert item['model_tool_name'] == proposed['name'] and item['tool_name'] == tool
            assert item['policy_id'] == {'raw': 1, 'counts': 2}[policy]
            assert 'audit_policy' not in proposed['arguments']
        elif mode == 'agent':
            assert item['tool_name'] == proposed['name']
            policy = proposed['arguments']['audit_policy']
            assert item['policy_id'] == {'raw': 1, 'counts': 2}[policy]
        else:
            assert item['tool_name'] == proposed['name'] and item['policy_id'] == 1
    audit = root / 'audit' / job_name
    raw = [e for p in audit.glob('*.buf') for e in decode_file(p, schema())]
    counts = [e for p in audit.glob('*.counts.jsonl') for e in lines(p)]
    for event in raw:
        assert event['policy_id'] == refs[event['call_ref']]['policy_id'] == 1
    for event in counts:
        assert event['policy_id'] == refs[event['call_ref']]['policy_id'] == 2
    rejected = []
    if mode != 'baseline':
        for identity, proposed in calls.items():
            if identity not in begins:
                returned = tool_results.get(identity, {})
                arguments = proposed.get('arguments')
                reason = 'tool_arguments_or_execution'
                if mode == 'agent' and proposed['name'] in ['read', 'bash', 'edit', 'write']:
                    if isinstance(arguments, dict) and 'audit_policy' not in arguments:
                        reason = 'missing_policy'
                    elif not isinstance(arguments, dict) or arguments.get('audit_policy') not in ['raw', 'counts']:
                        reason = 'invalid_policy'
                rejected.append({'tool_call_id': identity, 'tool': proposed['name'],
                                 'reason': reason, 'is_error': returned.get('isError'),
                                 'returned_text_chars': sum(len(c.get('text', '')) for c in returned.get('content', []))})
    else:
        assert not metadata and not raw and not counts
    if mode != 'baseline':
        assert begins and (raw or counts), f'No retained audit events: {job_name}'
    rewards = (result.get('verifier_result') or {}).get('rewards') or {}
    first = assistants[0].get('usage', {}) if assistants else {}
    exception = result.get('exception_info')
    statistics_path = root / (job_name + '-statistics.txt')
    statistics = {}
    if statistics_path.exists():
        rows = statistics_path.read_text(encoding='utf-8').strip().splitlines()
        statistics = dict(zip(rows[0].split(), map(int, rows[1].split())))
    return {'mode': mode, 'task': task, 'task_checksum': result['task_checksum'],
            'agent_info': result['agent_info'], 'exception_type': exception['exception_type'] if exception else None,
            'rewards': rewards, 'task_passed': bool(rewards) and all(v == 1 for v in rewards.values()),
            'session_completed': bool(assistants) and assistants[-1].get('stopReason') == 'stop' and exception is None,
            'usage': usage, 'total_tokens': usage['totalTokens'], 'model_responses': len(assistants),
            'model_tool_calls': len(calls), 'executed_audit_calls': len(begins),
            'first_input_tokens': sum(first.get(k, 0) for k in ['input', 'cacheRead', 'cacheWrite']),
            'business_tool_result_chars': sum(len(c.get('text', '')) for m in tool_results.values() for c in m['content']),
            'policy_counts': dict(Counter({1: 'raw', 2: 'counts'}[c['policy_id']] for c in begins.values())),
            'rejected_calls': rejected, 'raw_events': len(raw),
            'missing_policy_rejections': sum(c['reason'] == 'missing_policy' and c['is_error'] is True for c in rejected),
            'invalid_policy_rejections': sum(c['reason'] == 'invalid_policy' and c['is_error'] is True for c in rejected),
            'count_rows': len(counts), 'counted_events': sum(c['count'] for c in counts),
            'audit_bytes': sum(p.stat().st_size for p in audit.glob('*') if p.name.endswith(('.buf', '.counts.jsonl'))),
            'metadata_bytes': metadata_path.stat().st_size if metadata_path.exists() else 0,
            'statistics': statistics, 'audit_exercised': bool(begins),
            'harbor_native_usage_match': bool(context), 'retained_event_identity_policy_match': True,
            'timing': {k: result.get(k) for k in ['environment_setup', 'agent_setup', 'agent_execution', 'verifier']}}


def summarize(root):
    modes = [mode for mode in MODES if any(root.glob(mode + '--*'))]
    assert modes, 'No Harbor comparison trials found'
    runs = [trial(root, mode, task) for mode in modes for task in TASKS]
    for task in TASKS:
        assert len({r['task_checksum'] for r in runs if r['task'] == task}) == 1
    totals = {}
    for mode in modes:
        group = [r for r in runs if r['mode'] == mode]
        totals[mode] = {key: sum(r[key] for r in group) for key in ['total_tokens', 'model_responses',
            'model_tool_calls', 'executed_audit_calls', 'raw_events', 'count_rows', 'counted_events', 'audit_bytes',
            'metadata_bytes', 'business_tool_result_chars', 'missing_policy_rejections', 'invalid_policy_rejections']}
        totals[mode].update({'passed_tasks': sum(r['task_passed'] for r in group),
                            'completed_sessions': sum(r['session_completed'] for r in group),
                            'rejected_calls': sum(len(r['rejected_calls']) for r in group)})
    report = {'protocol': read(root / 'protocol.json'), 'runs': runs, 'totals': totals}
    if (root / 'reused-trials.json').exists():
        report['reused_trials'] = read(root / 'reused-trials.json')
        report['reused_trials_protocol'] = read(root / 'baseline-protocol.json')
    extra = root / 'extra-trials'
    report['supplemental_runs'] = [trial(extra, mode, task) for mode in MODES for task in TASKS
                                 if (extra / (mode + '--' + task)).exists()]
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('results', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = summarize(args.results)
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report['totals']))
