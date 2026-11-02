"""Summarize fixed-raw and configured retention on identical saved tool-call plans."""
import argparse
import hashlib
import json
import pathlib
from collections import Counter
from decode import HEADER, MAGIC

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('results', type=pathlib.Path)
parser.add_argument('--output', type=pathlib.Path, required=True)
args = parser.parse_args()


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


tasks = {}
for directory in sorted(args.results.iterdir()):
    if not (directory / 'summary.json').is_file():
        continue
    summary = read(directory / 'summary.json')
    replay = read(directory / 'agent-result.json')
    calls = [json.loads(l) for l in (directory / 'pi/calls.jsonl').read_text(encoding='utf-8').splitlines()]
    begins = [c for c in calls if c['kind'] == 'begin']
    ends = [c for c in calls if c['kind'] == 'end']
    identities = {c['call_ref']: c for c in begins}
    executed = [json.loads(l) for l in (directory / 'replay-results.jsonl').read_text(encoding='utf-8').splitlines()]
    plan = sorted([{'id': c['toolCallId'], 'tool': c['tool'], 'arguments': c['arguments']} for c in executed],
                  key=lambda c: c['id'])
    mode = summary['control_mode']
    assert replay['mode'] == 'tool-replay' and replay['apiRequests'] == 0 and replay['totalTokens'] == 0
    assert len(begins) == len(ends) == replay['tools'] == replay['expectedTools'] == len(executed)
    assert not replay['error'] and not replay['stop'] and not replay['expectedErrorMismatches'], directory.name
    for c in begins:
        expected = 2 if mode == 'configured' and replay['policies'].get(c['tool_name'], 'raw') == 'counts' else 1
        assert c['policy_id'] == expected, directory.name
    retained_policies = Counter()
    audit_bytes_by_tool = Counter()
    for path in (directory / 'audit').glob('*.buf'):
        data = path.read_bytes()
        offset = 0
        while offset < len(data):
            header = HEADER.unpack_from(data, offset)
            length, magic, ref = header[4], header[6], header[7]
            assert magic == MAGIC and length >= HEADER.size and offset + length <= len(data), path
            call = identities[f'{ref:016x}']
            audit_bytes_by_tool[call['tool_name']] += length
            offset += length
    for path in (directory / 'audit').glob('*.counts.jsonl'):
        for line in path.read_bytes().splitlines(keepends=True):
            event = json.loads(line)
            audit_bytes_by_tool[identities[event['call_ref']]['tool_name']] += len(line)
    for line in (directory / 'events.jsonl').read_text(encoding='utf-8').splitlines():
        event = json.loads(line)
        call = identities[event['call_ref']]
        assert call['tool_call_id'] == event['tool_call_id'] and call['policy_id'] == event['policy_id'] == 1
        retained_policies['raw'] += 1
    for event in read(directory / 'counts.json'):
        call = identities[event['call_ref']]
        assert call['tool_call_id'] == event['tool_call_id'] and call['policy_id'] == event['policy_id'] == 2
        retained_policies['counts'] += event['count']
    assert retained_policies['raw'] == summary['raw_events']
    assert retained_policies['counts'] == summary['histogram_events']
    cleanup = read(directory / 'cleanup.json')
    assert cleanup['module_unloaded'] and not cleanup['kernel_errors'], directory.name
    ctrf = read(directory / 'ctrf.json')['results']['summary']
    raw_bytes = sum(p.stat().st_size for p in (directory / 'audit').glob('*.buf'))
    counts_bytes = sum(p.stat().st_size for p in (directory / 'audit').glob('*.counts.jsonl'))
    assert sum(audit_bytes_by_tool.values()) == raw_bytes + counts_bytes
    trial = {'trial': directory.name, 'task': summary['task'], 'control_mode': mode,
             'source_sha256': replay['sourceSha256'],
             'plan_sha256': hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest(),
             'groups': replay['groups'], 'calls': len(begins),
             'tool_counts': dict(Counter(c['tool_name'] for c in begins)),
             'tool_errors': replay['toolErrors'], 'expected_error_mismatches': replay['expectedErrorMismatches'],
             'api_requests': replay['apiRequests'], 'total_tokens': replay['totalTokens'],
             'replay_elapsed_sec': replay['elapsedSec'], 'trial_elapsed_sec': summary['elapsed_sec'],
             'task_passed': bool(summary['reward']), 'tests': ctrf,
             'raw_events': summary['raw_events'], 'histogram_events': summary['histogram_events'],
             'raw_bytes': raw_bytes, 'counts_bytes': counts_bytes, 'audit_bytes': raw_bytes + counts_bytes,
             'audit_bytes_by_tool': dict(audit_bytes_by_tool),
             'call_metadata_bytes': (directory / 'pi/calls.jsonl').stat().st_size,
             'statistics': summary['statistics'], 'environment': summary['environment'], 'cleanup': cleanup}
    pair = tasks.setdefault(summary['task'], {})
    assert mode not in pair, directory.name
    pair[mode] = trial

pairs = []
for task, modes in tasks.items():
    assert set(modes) == {'fixed-raw', 'configured'}, task
    fixed, configured = modes['fixed-raw'], modes['configured']
    assert fixed['source_sha256'] == configured['source_sha256'] and fixed['plan_sha256'] == configured['plan_sha256']
    assert fixed['calls'] == configured['calls'] and fixed['groups'] == configured['groups']
    pairs.append({'task': task, **modes,
                  'same_source_and_call_plan': True,
                  'audit_byte_delta': configured['audit_bytes'] - fixed['audit_bytes'],
                  'replay_time_delta_sec': configured['replay_elapsed_sec'] - fixed['replay_elapsed_sec']})
assert len(pairs) == 3, f'Expected 3 paired tasks, got {len(pairs)}'
report = {'execution': 'tool-replay', 'tasks': 3, 'trials': 6,
          'replicates_per_condition': 1, 'api_requests': 0, 'total_tokens': 0,
          'fixed_raw_scope': 'Call identity, worker executor and NoDrop capture remain enabled; tool-policy selection is bypassed',
          'configured_scope': 'Select raw/counts per tool through the existing call-level control interface',
          'pairs': pairs}
for name, key in [('runtime.json', 'runtime_sha256'), ('environment-cleanup.json', 'environment_cleanup')]:
    if (args.results / name).is_file():
        report[key] = read(args.results / name)
args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
print(json.dumps({'tasks': 3, 'trials': 6, 'api_requests': 0, 'total_tokens': 0,
                  'passed_trials': sum(p[m]['task_passed'] for p in pairs for m in ('fixed-raw', 'configured')),
                  'pairs': [{k: p[k] for k in ('task', 'audit_byte_delta', 'replay_time_delta_sec')} for p in pairs]}))
