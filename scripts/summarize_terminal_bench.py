"""Summarize task outcomes and audit accounting from saved trial files."""
import argparse
import json
import pathlib
from collections import Counter

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('results', type=pathlib.Path)
parser.add_argument('--output', type=pathlib.Path)
parser.add_argument('--legacy-output-tokens', type=int, help='Known output budget for trials saved by an older runner')
args = parser.parse_args()


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


runs = []
for directory in sorted(args.results.iterdir()):
    if not (directory / 'summary.json').exists():
        continue
    summary = read(directory / 'summary.json')
    agent = read(directory / 'agent-result.json')
    messages = read(directory / 'transcript.json')
    assistant = next((m for m in reversed(messages) if m.get('role') == 'assistant'), {})
    calls = [json.loads(line) for line in (directory / 'pi/calls.jsonl').read_text(encoding='utf-8').splitlines()]
    begins = [c for c in calls if c['kind'] == 'begin']
    ends = [c for c in calls if c['kind'] == 'end']
    stats = summary['statistics']
    retained = summary['raw_events'] + summary['histogram_events']
    assert summary['calls'] == len(begins) and summary['call_ends'] == len(ends), directory.name
    assert sum(1 for _ in (directory / 'events.jsonl').open(encoding='utf-8')) == summary['raw_events'], directory.name
    ctrf = read(directory / 'ctrf.json')
    tests = ctrf['results']['summary']
    raw_bytes = sum(p.stat().st_size for p in (directory / 'audit').glob('*.buf'))
    counts_bytes = sum(p.stat().st_size for p in (directory / 'audit').glob('*.counts.jsonl'))
    run = {'trial': directory.name, 'task': summary['task'],
           'execution': summary.get('execution', 'live-model'),
           'audit': summary['audit'],
           'control_mode': agent.get('controlMode', summary.get('control_mode')) if summary['audit'] == 'on' else None,
           'output_mode': agent.get('outputMode', 'inline'),
           'output_inline_bytes': agent.get('outputInlineBytes'),
           'provider': agent['provider'], 'model': agent['model'], 'api': agent['api'],
           'max_output_tokens': agent.get('maxOutputTokens', args.legacy_output_tokens),
           'model_stop_reason': assistant.get('stopReason'),
           'run_stop': agent.get('stop'), 'agent_error': agent.get('error'), 'limits': agent['limits'],
           'model_output_limit': assistant.get('stopReason') == 'length',
           'task_passed': bool(summary['reward']), 'tests': tests,
           'model_tool_requests': agent['tools'], 'executed_calls': len(begins),
           'tool_counts': dict(Counter(c['tool_name'] for c in begins)),
           'policy_counts': dict(Counter({1: 'raw', 2: 'counts'}.get(c['policy_id'], 'unknown') for c in begins)),
           'completed_calls': len(ends), 'total_reported_tokens': agent['totalTokens'],
           'usage': agent.get('usage'),
           'raw_events': summary['raw_events'], 'histogram_events': summary['histogram_events'],
           'associated_events': summary['associated_events'], 'statistics': stats,
           'event_accounting_matches': summary['event_accounting_matches'],
           'accounting_with_unsolved_matches': stats['n_evts'] == retained + stats['drop_unsolved'],
           'audit_checks_passed': summary['audit_checks_passed'],
           'audit_status': 'not_exercised' if not begins else ('complete' if summary['audit_checks_passed'] else 'incomplete'),
           'raw_bytes': raw_bytes, 'counts_bytes': counts_bytes, 'audit_bytes': raw_bytes + counts_bytes,
           'call_metadata_bytes': (directory / 'pi/calls.jsonl').stat().st_size,
           'agent_elapsed_sec': agent['elapsedSec'], 'trial_elapsed_sec': summary['elapsed_sec'],
           'instruction_sha256': summary['instruction_sha256'], 'environment': summary['environment'],
           'cleanup': read(directory / 'cleanup.json')}
    runs.append(run)

report = {'dataset': 'Terminal-Bench 2.1', 'runs': runs,
          'totals': {'tasks': len({r['task'] for r in runs}), 'trials': len(runs),
                     'passed_trials': sum(r['task_passed'] for r in runs),
                     'passed_tasks': len({r['task'] for r in runs if r['task_passed']}),
                     'executed_calls': sum(r['executed_calls'] for r in runs),
                     'raw_events': sum(r['raw_events'] for r in runs),
                     'histogram_events': sum(r['histogram_events'] for r in runs),
                     'associated_events': sum(r['associated_events'] for r in runs),
                     'drop_unsolved': sum(r['statistics']['drop_unsolved'] for r in runs),
                     'raw_bytes': sum(r['raw_bytes'] for r in runs),
                     'counts_bytes': sum(r['counts_bytes'] for r in runs),
                     'audit_bytes': sum(r['audit_bytes'] for r in runs),
                     'call_metadata_bytes': sum(r['call_metadata_bytes'] for r in runs),
                     'total_reported_tokens': sum(r['total_reported_tokens'] for r in runs)}}
if (args.results / 'runtime.json').exists():
    report['runtime_sha256'] = read(args.results / 'runtime.json')
if (args.results / 'environment-cleanup.json').exists():
    report['environment_cleanup'] = read(args.results / 'environment-cleanup.json')
text = json.dumps(report, indent=2) + '\n'
if args.output:
    args.output.write_text(text, encoding='utf-8')
print(json.dumps(report['totals']))
