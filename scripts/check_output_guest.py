"""Check agent-supplied policy JSON through Pi, the executor and NoDrop on Linux 6.8."""
import argparse
from collections import Counter
import json
import os
import pathlib
import pwd
import re
import subprocess
from decode import decode

ROOT = pathlib.Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', type=pathlib.Path, default=ROOT / 'results/output-reference')
parser.add_argument('--tool-names', action='store_true', help='Check policy-bearing tool names')
args = parser.parse_args()
output = args.output.resolve()
assert os.geteuid() == 0 and os.uname().release.startswith('6.8.'), 'Run as root in the Linux 6.8 VM'
assert not pathlib.Path('/sys/module/nodrop').exists(), 'A NoDrop module is already loaded'
assert not output.exists(), 'Use a fresh output directory'
for name in ['audit', 'pi', 'work']:
    (output / name).mkdir(parents=True, exist_ok=True)
subprocess.run(['chown', '-R', '1000:1000', str(output)], check=True)


def run(command, log=None, check=True):
    result = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=180)
    if log:
        (output / log).write_text(result.stdout, encoding='utf-8')
    if check and result.returncode:
        raise RuntimeError(f'{command[0]} exited {result.returncode}: {result.stdout[-1500:]}')
    return result


loaded = mounted = False
host_audit = ROOT / 'results/audit'
host_audit.mkdir(parents=True, exist_ok=True)
before = run(['dmesg', '--color=never']).stdout.splitlines()
try:
    run(['mount', '--bind', str(output / 'audit'), str(host_audit)])
    mounted = True
    run(['insmod', str(ROOT / 'build/nodrop/nodrop.ko')], 'insmod.txt')
    loaded = True
    control = str(ROOT / 'build/nodrop/scripts/ctrl/ctrl')
    run([control, 'start'], 'start.txt')
    run([control, 'record'], 'record.txt')
    user = pwd.getpwuid(1000).pw_name
    run(['runuser', '-u', user, '--', 'env',
         'PI_NODROP_CONTROL_MODE=' + ('agent-names' if args.tool_names else 'agent'),
         str(ROOT / 'node'), 'tests/extension-loader.mjs'], 'extension-loader.txt')
    run(['runuser', '-u', user, '--', 'env', 'PI_NODROP_TEST_BACKEND=nodrop',
         f'PI_NODROP_TEST_WORKDIR={output / "work"}', str(ROOT / 'node'), '--test',
         'tests/policy-tools.test.mjs' if args.tool_names else 'tests/output-store.test.mjs'], 'tests.txt')
    run([control, 'stat'], 'statistics.txt')
    run(['rmmod', 'nodrop'], 'rmmod.txt')
    loaded = False
    metadata = []
    for path in sorted((output / 'work').glob('*/audit/calls.jsonl')):
        metadata.append(path.read_text())
    for path in sorted((output / 'work').glob('*/fixed-audit/calls.jsonl')):
        metadata.append(path.read_text())
    (output / 'pi/calls.jsonl').write_text(''.join(metadata), encoding='utf-8')
    calls, events, counts = decode(output)
    begins = {c['tool_call_id']: c for c in calls if c['kind'] == 'begin'}
    expected = 3 if args.tool_names else 2
    assert len(begins) == expected and sum(c['kind'] == 'end' for c in calls) == expected
    read_id, page_id = ('named-read', 'named-page') if args.tool_names else ('output-read', 'output-page')
    raw = Counter(e['tool_call_id'] for e in events)
    histogram = Counter()
    for c in counts:
        histogram[c['tool_call_id']] += c['count']
    assert raw[read_id] > 0 and histogram[read_id] == 0
    assert histogram[page_id] > 0 and raw[page_id] == 0
    if args.tool_names:
        assert raw['named-write'] > 0
        assert all(c['policy_source'] == 'agent-names' and 'audit_policy' not in c['input'] for c in begins.values())
    indexes = list((output / 'work').glob('*/audit/outputs/*/index.json'))
    assert len(indexes) == 1
    index = json.loads(indexes[0].read_text())
    assert index['call_ref'] == begins[read_id]['call_ref']
    assert index['tool_call_id'] == read_id
    assert pathlib.Path(begins[page_id]['input']['path']) == indexes[0]
    refs = {c['call_ref']: c for c in begins.values()}
    for e in events + counts:
        assert e['call_ref'] in refs and e['policy_id'] == refs[e['call_ref']]['policy_id']
    summary = {'kernel': os.uname().release, 'pi': '1.4.0', 'model': 'scripted protocol stream',
               'output_index': index, 'api_requests': 0, 'calls': len(begins), 'raw_events': len(events),
               'histogram_events': sum(c['count'] for c in counts), 'histogram_rows': len(counts),
               'calls_by_policy': {key: {'requested': c.get('model_tool_name', c['input'].get('audit_policy')), 'applied': c['policy_id'],
                                        'source': c['policy_source'], 'raw_events': raw[key],
                                        'histogram_events': histogram[key]} for key, c in begins.items()}}
    (output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary), flush=True)
finally:
    if loaded:
        run(['rmmod', 'nodrop'], 'rmmod.txt', check=False)
    after = run(['dmesg', '--color=never']).stdout.splitlines()
    diagnostic = '\n'.join(after[len(before):])
    (output / 'dmesg-new.txt').write_text(diagnostic + '\n')
    if mounted:
        run(['umount', str(host_audit)])
    cleanup = {'module_unloaded': not pathlib.Path('/sys/module/nodrop').exists(),
               'output_unmounted': not os.path.ismount(host_audit),
               'kernel_errors': bool(re.search(r'BUG:|Oops:|kernel panic|context inheritance failed', diagnostic, re.I))}
    (output / 'cleanup.json').write_text(json.dumps(cleanup, indent=2) + '\n')
