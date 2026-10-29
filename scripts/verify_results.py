"""Compare captured IDs with an independent path-based test oracle.

Paths are used only to check this deterministic workload, never for production
attribution: decode.py joins event/context exclusively on the captured ID.
"""
import argparse
import json
import pathlib
import re
from decode import decode

parser = argparse.ArgumentParser()
parser.add_argument('results', nargs='?', default='results', type=pathlib.Path)
root = parser.parse_args().results
calls, events, counts = decode(root)
expected = {
    'A.txt': {'pi-write-A', 'pi-read-A'},
    'B.txt': {'pi-write-B', 'pi-edit-B'},
    'shell-child.txt': {'pi-shell-child'},
    'after-error.txt': {'pi-after-error'},
    'scope-A.txt': {'scope-A'},
    'scope-B.txt': {'scope-B'},
    'scope-background.txt': {'scope-parent'},
    'scope-overlap.txt': {'scope-overlap'},
}
checks = []
for basename, allowed in expected.items():
    matched = [event for event in events if event['name'] in ('open', 'openat', 'openat2') and
               any(isinstance(value, str) and value.endswith('/' + basename)
                   for value in event['args'].values())]
    observed = {event['tool_call_id'] for event in matched}
    checks.append({'check': basename, 'events': len(matched), 'expected': sorted(allowed),
                   'observed': sorted(str(x) for x in observed), 'pass': bool(matched) and observed == allowed})
for forbidden in ('outside-tool.txt', 'unbound-scope-A.txt', 'unbound-scope-B.txt'):
    found = [event for event in events if any(isinstance(value, str) and value.endswith('/' + forbidden)
             for value in event['args'].values())]
    checks.append({'check': 'not captured: ' + forbidden, 'events': len(found), 'pass': not found})
checks.append({'check': 'counts policy produces histogram records', 'rows': len(counts),
               'pass': bool(counts) and all(row['tool_call_id'] == 'pi-count-ls' for row in counts)})
checks.append({'check': 'counts call emits no raw events',
               'pass': not any(event['tool_call_id'] == 'pi-count-ls' for event in events)})
checks.append({'check': 'all raw records have declared identity',
               'pass': all(event['tool_call_id'] is not None and event['policy_id'] == 1 for event in events)})
begins = [call for call in calls if call['kind'] == 'begin']
checks.append({'check': 'parallel Pi write calls use separate execution subjects',
               'pass': len({call['worker_pid'] for call in begins if call['tool_call_id'] in
                            ('pi-write-A', 'pi-write-B')}) == 2})
diagnostic = (root / 'dmesg-new.txt').read_text()
checks.append({'check': 'no kernel crash or context inheritance error',
               'pass': not re.search(r'BUG:|Oops:|kernel panic|context inheritance failed', diagnostic, re.I)})
cleanup = json.loads((root / 'cleanup.json').read_text())
checks.append({'check': 'module unloaded', 'pass': cleanup['module_unloaded']})
stats_text = (root / 'statistics.txt').read_text().strip().splitlines()
stats = dict(zip(stats_text[0].split(), map(int, stats_text[1].split())))
checks.append({'check': 'NoDrop drop_unsolved is zero', 'pass': stats['drop_unsolved'] == 0})
checks.append({'check': 'captured event accounting matches raw plus histograms',
               'pass': stats['n_evts'] == len(events) + sum(row['count'] for row in counts)})
summary = {'pass': all(item['pass'] for item in checks), 'checks': checks, 'statistics': stats,
           'raw_events': len(events), 'histogram_rows': len(counts),
           'histogram_events': sum(row['count'] for row in counts),
           'raw_bytes': sum(p.stat().st_size for p in (root / 'audit').glob('*.buf')),
           'counts_bytes': sum(p.stat().st_size for p in (root / 'audit').glob('*.counts.jsonl'))}
(root / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
print(json.dumps(summary, indent=2))
raise SystemExit(0 if summary['pass'] else 1)
