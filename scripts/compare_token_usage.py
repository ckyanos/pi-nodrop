"""Compare three paired audit-on/off trials from saved API usage and request payloads."""
import argparse
import hashlib
import json
import pathlib
from collections import Counter

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('results', type=pathlib.Path)
parser.add_argument('--output', type=pathlib.Path, required=True)
args = parser.parse_args()


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


trials = {}
for directory in sorted(args.results.iterdir()):
    if not (directory / 'summary.json').is_file():
        continue
    summary = read(directory / 'summary.json')
    agent = read(directory / 'agent-result.json')
    calls = [json.loads(line) for line in (directory / 'pi/calls.jsonl').read_text(encoding='utf-8').splitlines()]
    begins = [c for c in calls if c['kind'] == 'begin']
    assert len(begins) == summary['calls'], directory.name
    for call in begins:
        expected = 2 if summary['policies'].get(call['tool_name'], 'raw') == 'counts' else 1
        assert call['policy_id'] == expected, directory.name
    transcript = read(directory / 'transcript.json')
    first_assistant = next(m for m in transcript if m['role'] == 'assistant')
    tool_result_sizes = [sum(len(c.get('text', '')) for c in m.get('content', []) if c.get('type') == 'text')
                         for m in transcript if m['role'] == 'toolResult']
    usage = {k: sum(m.get('usage', {}).get(k, 0) for m in transcript if m['role'] == 'assistant')
             for k in ('input', 'output', 'cacheRead', 'cacheWrite', 'totalTokens')}
    assert usage['totalTokens'] == agent['totalTokens'], directory.name
    assert all(usage[k] == agent['usage'][k] for k in agent['usage']), directory.name
    requests = [json.loads(line) for line in (directory / 'requests.jsonl').read_text().splitlines()]
    bodies = [read(directory / f'request-{r["index"]}.json') for r in requests]
    assert len(bodies) == agent['requests'] and bodies, directory.name
    totals = summary['raw_events'] + summary['histogram_events']
    trial = {'trial': directory.name, 'task': summary['task'], 'audit': summary['audit'],
             'policies': summary['policies'], 'usage': usage, 'turns': agent['turns'],
             'first_prompt_tokens': first_assistant['usage']['totalTokens'] - first_assistant['usage']['output'],
             'tool_result_text_chars': sum(tool_result_sizes),
             'largest_tool_result_text_chars': max(tool_result_sizes, default=0),
             'tool_requests': agent['tools'], 'requests': agent['requests'],
             'executed_tool_counts': dict(Counter(c['tool_name'] for c in begins)),
             'task_passed': bool(summary['reward']), 'stop': agent['stop'], 'error': agent['error'],
             'agent_elapsed_sec': agent['elapsedSec'], 'limits': agent['limits'],
             'max_output_tokens': agent['maxOutputTokens'], 'model': agent['model'], 'api': agent['api'],
             'instruction_sha256': summary['instruction_sha256'], 'environment': summary['environment'],
             'raw_events': summary['raw_events'], 'histogram_events': summary['histogram_events'],
             'raw_bytes': sum(p.stat().st_size for p in (directory / 'audit').glob('*.buf')),
             'counts_bytes': sum(p.stat().st_size for p in (directory / 'audit').glob('*.counts.jsonl')),
             'metadata_bytes': (directory / 'pi/calls.jsonl').stat().st_size,
             'statistics': summary['statistics'], 'cleanup': read(directory / 'cleanup.json'),
             'first_request_sha256': digest(bodies[0]),
             'first_request_tools_sha256': digest(bodies[0].get('tools')),
             'all_request_tools_sha256': sorted({digest(b.get('tools')) for b in bodies}),
             'all_system_messages_sha256': sorted({digest([m for m in b.get('messages', [])
                                                         if m.get('role') in ('system', 'developer')]) for b in bodies}),
             'request_bytes': sum(r['bytes'] for r in requests), 'retained_events': totals}
    if summary['audit'] == 'off':
        assert totals == 0 and summary['calls'] == 0, directory.name
    else:
        assert summary['calls'] > 0 and totals > 0, directory.name
    pair = trials.setdefault(summary['task'], {})
    assert summary['audit'] not in pair, directory.name
    pair[summary['audit']] = trial

pairs = []
for task, conditions in trials.items():
    assert set(conditions) == {'on', 'off'}, task
    on, off = conditions['on'], conditions['off']
    assert on['instruction_sha256'] == off['instruction_sha256'], task
    delta = on['usage']['totalTokens'] - off['usage']['totalTokens']
    pairs.append({'task': task, 'off': off, 'on': on,
                  'total_token_delta': delta,
                  'total_token_delta_percent': 100 * delta / off['usage']['totalTokens'],
                  'first_request_identical': on['first_request_sha256'] == off['first_request_sha256'],
                  'first_prompt_token_delta': on['first_prompt_tokens'] - off['first_prompt_tokens'],
                  'tool_definitions_identical': on['all_request_tools_sha256'] == off['all_request_tools_sha256'],
                  'system_messages_identical': on['all_system_messages_sha256'] == off['all_system_messages_sha256']})
assert len(pairs) == 3, f'Expected 3 paired tasks, got {len(pairs)}'
off_total = sum(p['off']['usage']['totalTokens'] for p in pairs)
on_total = sum(p['on']['usage']['totalTokens'] for p in pairs)
report = {'tasks': len(pairs), 'trials': 2 * len(pairs), 'pairs': pairs,
          'totals': {'off_tokens': off_total, 'on_tokens': on_total,
                     'delta_tokens': on_total - off_total,
                     'delta_percent': 100 * (on_total - off_total) / off_total},
          'design': {'replicates_per_condition': 1,
                     'audit_off': 'Original Pi tools; no audit extension or NoDrop module',
                     'audit_on': 'Pi audit extension; execution identity and retention policy submitted through ioctl',
                     'comparison': 'Independent live model sessions on fresh task filesystems',
                     'inference': 'Observed session token deltas include different model execution paths'}}
if (args.results / 'runtime.json').is_file():
    report['runtime_sha256'] = read(args.results / 'runtime.json')
if (args.results / 'environment-cleanup.json').is_file():
    report['environment_cleanup'] = read(args.results / 'environment-cleanup.json')
args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
print(json.dumps({'totals': report['totals'], 'pairs': [
    {k: p[k] for k in ('task', 'total_token_delta', 'total_token_delta_percent',
                       'first_request_identical', 'tool_definitions_identical', 'system_messages_identical')}
    for p in pairs]}))
