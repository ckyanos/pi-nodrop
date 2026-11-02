"""Account for native Pi, independent auditors, task rewards, and captured facts."""
import argparse
from collections import Counter
import json
from pathlib import Path

from summarize_harbor_comparison import trial as nodrop_trial

TASKS = ['openssl-selfsigned-cert', 'log-summary-date-ranges', 'fix-git']
MODES = ['baseline', 'agentsight', 'sentinel', 'fixed-raw', 'agent']


def lines(path):
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()] if path.exists() else []


def provider_usage(rows):
    counts = Counter()
    for row in rows:
        usage = row.get('usage') or {}
        for key in ('prompt_tokens', 'completion_tokens', 'total_tokens'):
            counts[key] += usage.get(key, 0)
        counts['reasoning_tokens'] += usage.get('completion_tokens_details', {}).get('reasoning_tokens', 0)
        counts['cached_tokens'] += usage.get('prompt_tokens_details', {}).get('cached_tokens', 0)
    return {'requests': len(rows), 'requests_with_usage': sum(bool(x.get('usage')) for x in rows),
            'requests_without_usage': sum(not bool(x.get('usage')) for x in rows),
            'statuses': dict(Counter(str(x['status']) for x in rows)), 'usage': dict(counts),
            'finish_reasons': dict(Counter(str(x.get('finish_reason')) for x in rows)),
            'request_error_messages': dict(Counter(x['error'] for x in rows if x.get('error'))),
            'reasoning_only_empty_choices_requests': sum(
                str(x.get('error', '')).startswith('Upstream returned no choices:')
                and (x.get('usage') or {}).get('completion_tokens', 0) > 0
                and (x.get('usage') or {}).get('completion_tokens', 0) == (x.get('usage') or {}).get('completion_tokens_details', {}).get('reasoning_tokens', -1)
                for x in rows),
            'request_seconds': sum(x['seconds'] for x in rows)}


def summarize(root):
    ledger = lines(root / 'gateway-requests.jsonl')
    runs = []
    for task in TASKS:
        for mode in MODES:
            case = mode + '--' + task
            paths = list((root / case).glob('*/result.json'))
            if not paths:
                continue
            assert len(paths) == 1, case
            path = paths[0]
            result = json.loads(path.read_text())
            reward = (result.get('verifier_result') or {}).get('rewards') or {}
            info = result.get('agent_result') or {}
            events = [e for p in path.parent.glob('agent/pi/sessions/*.jsonl') for e in lines(p)]
            messages = [e['message'] for e in events if e.get('type') == 'message']
            assistants = [m for m in messages if m.get('role') == 'assistant']
            usage = Counter()
            for event in events:
                u = (event.get('message') or {}).get('usage') if event.get('type') == 'message' else event.get('usage')
                if u:
                    for key in ('input', 'output', 'cacheRead', 'cacheWrite', 'totalTokens', 'reasoning'):
                        usage[key] += u.get(key, 0)
            native_input = usage['input'] + usage['cacheRead'] + usage['cacheWrite']
            native_total = native_input + usage['output']
            native_match = info.get('n_input_tokens') == native_input and info.get('n_output_tokens') == usage['output']
            shared = root / 'monitor' / case
            label_path = shared / 'request-label.json'
            request_label = json.loads(label_path.read_text())['request_label'] if label_path.exists() else case
            requests = [e for e in ledger if e['case'] == request_label]
            business = [e for e in requests if e['role'] == 'business']
            observer = [e for e in requests if e['role'] != 'business']
            audit = provider_usage(observer)
            api_business = provider_usage(business)
            first = assistants[0].get('usage', {}) if assistants else {}
            monitor = lines(shared / 'monitor.jsonl')
            row = {'mode': mode, 'task': task, 'case': case, 'request_label': request_label, 'task_checksum': result.get('task_checksum'),
                'task_passed': bool(reward) and all(v == 1 for v in reward.values()), 'rewards': reward,
                'exception': result.get('exception_info'),
                'pi_session_completed': not result.get('exception_info') and bool(assistants) and assistants[-1].get('stopReason') == 'stop',
                'native_final_stop_reason': assistants[-1].get('stopReason') if assistants else None,
                'native_usage': dict(usage), 'business_tokens': native_total,
                'observer_tokens': audit['usage'].get('total_tokens', 0),
                'reported_total_tokens': native_total + audit['usage'].get('total_tokens', 0),
                'harbor_pi_usage_match': native_match,
                'pi_gateway_usage_match': native_total == api_business['usage'].get('total_tokens', 0),
                'business_api': api_business, 'observer_api': audit,
                'observer_roles': {role: provider_usage([e for e in observer if e['role'] == role])
                                   for role in sorted(set(e['role'] for e in observer))},
                'first_input_tokens': sum(first.get(k, 0) for k in ('input', 'cacheRead', 'cacheWrite')),
                'model_responses': len(assistants),
                'model_tool_calls': sum(c.get('type') == 'toolCall' for m in assistants for c in m.get('content', [])),
                'business_tool_output_characters': sum(len(c.get('text', '')) for m in messages if m.get('role') == 'toolResult' for c in m.get('content', []) if c.get('type') == 'text'),
                'model_tool_names': dict(Counter(c.get('name') for m in assistants for c in m.get('content', []) if c.get('type') == 'toolCall')),
                'business_span_seconds': (max(e['started'] + e['seconds'] for e in business) - min(e['started'] for e in business)) if business else None,
                'timing': {key: result.get(key) for key in ('agent_setup', 'agent_execution', 'verifier')},
                'monitor_cache_hits': sum('cache hit' in e.get('message', '') for e in monitor),
                'monitor_event_records': dict(Counter(e.get('message') for e in monitor if e.get('message', '').endswith('_event_record'))),
                'monitor_diagnostic_bytes': (shared / 'monitor.jsonl').stat().st_size if (shared / 'monitor.jsonl').exists() else 0,
                'monitor_error_message_counts': dict(Counter(e.get('message') for e in monitor if e.get('level') == 'error')),
                'monitor_errors': [{k: e.get(k) for k in ('message', 'error')} for e in monitor if e.get('level') == 'error']}
            if (shared / 'capture-summary.json').exists():
                row['capture'] = json.loads((shared / 'capture-summary.json').read_text())
                row['capture']['matches_business_request_count'] = row['capture']['http_pairs'] == len(business)
                processes = lines(shared / 'process-trace.jsonl')
                row['capture']['process_comm_counts'] = dict(Counter(p.get('comm') for p in processes))
                row['capture']['gateway_process_records'] = sum(p.get('comm') == 'pi-audit-gw' for p in processes)
            if mode == 'sentinel':
                hooks = lines(shared / 'extension-events.jsonl')
                calls = [h['tool_call_id'] for h in hooks if h.get('kind') == 'tool_call']
                expected_calls = [c['id'] for m in assistants for c in m.get('content', []) if c.get('type') == 'toolCall']
                row['sentinel_connection'] = {
                    'client_ready': (shared / 'client-ready').exists(),
                    'native_connected': any(e.get('message') == 'computer_monitor_server: agent connected' for e in monitor),
                    'native_passive_tracing': any(e.get('message') == 'handler: start passive tracing' for e in monitor),
                    'notified_tool_calls': len(calls),
                    'tool_call_ids_match': calls == expected_calls,
                    'connection_failure': (shared / 'connection-failure.json').exists()}
                queries = [e.get('message', '') for e in monitor if e.get('message', '').startswith('audit: new security query')]
                row['native_security_operations'] = len(queries)
                row['pycache_security_operations'] = sum('__pycache__' in q for q in queries)
                row['grep_execution_security_operations'] = sum('execute binary /usr/bin/grep ' in q for q in queries)
                row['instrumentation_security_operations'] = [q for q in queries if any(s in q for s in ('/audit-shared', 'extension-events', 'client-ready', 'pi-audit-extension'))]
            if mode in ('fixed-raw', 'agent'):
                try:
                    native = nodrop_trial(root, mode, task)
                    row['nodrop'] = {k: native[k] for k in ('executed_audit_calls', 'raw_events', 'count_rows',
                        'counted_events', 'audit_bytes', 'metadata_bytes', 'policy_counts',
                        'retained_event_identity_policy_match', 'missing_policy_rejections')}
                except Exception as exc:
                    row['nodrop_validation_error'] = str(exc)
            runs.append(row)
    for task in TASKS:
        hashes = {r['task_checksum'] for r in runs if r['task'] == task}
        assert len(hashes) <= 1, 'Task inputs differ: ' + task
    totals = {}
    for mode in MODES:
        group = [r for r in runs if r['mode'] == mode]
        totals[mode] = {'completed_trials': len(group), 'passed_tasks': sum(r['task_passed'] for r in group),
            **{k: sum(r[k] for r in group) for k in ('business_tokens', 'observer_tokens', 'reported_total_tokens',
                                                  'model_responses', 'model_tool_calls', 'business_tool_output_characters')}}
    labels = {r['request_label'] for r in runs}
    return {'runs': runs, 'totals': totals, 'additional_attempt_usage': provider_usage([r for r in ledger if r['case'] not in labels]), 'expected_trials': 15,
            'completed_trials': len(runs), 'protocols': [json.loads(p.read_text()) for p in sorted(root.glob('protocol-*.json'))]}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('root', type=Path)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    result = summarize(args.root)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result['totals'], indent=2), flush=True)
