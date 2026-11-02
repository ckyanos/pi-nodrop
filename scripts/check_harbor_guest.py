"""Check NoDrop raw/counts capture as root in an unprivileged task container."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess

from decode import decode_file, schema

ROOT = Path(__file__).resolve().parents[1]


def run(args):
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode:
        (output / 'failure.json').write_text(json.dumps({'exit_code': result.returncode,
            'stdout': result.stdout, 'stderr': result.stderr}, indent=2) + '\n')
        raise RuntimeError(result.stderr + result.stdout)
    return result.stdout


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', required=True, type=Path)
args = parser.parse_args()
assert os.geteuid() == 0 and not Path('/sys/module/nodrop').exists()
output = args.output.resolve()
(output / 'audit').mkdir(parents=True, exist_ok=False)
before = run(['dmesg', '--color=never']).splitlines()
code = r"""
const b=require('./build/context.node'); const fs=require('node:fs'); const cp=require('node:child_process');
(async()=>{
 b.setContext(0x686172626f720001n,1);
 fs.writeFileSync('/tmp/harbor-nodrop-check','native-root-check');
 cp.execFileSync('/bin/sh',['-c','cat /tmp/harbor-nodrop-check >/tmp/harbor-nodrop-child']);
 await b.flush(); b.setContext(0n,0);
 b.setContext(0x686172626f720002n,2);
 if(fs.readFileSync('/tmp/harbor-nodrop-child','utf8')!=='native-root-check')throw new Error('child output');
 await b.flush(); b.setContext(0n,0);
 console.log(JSON.stringify({uid:process.getuid(),raw:true,counts:true}));
})().catch(e=>{console.error(e);process.exitCode=1});
"""
try:
    run(['insmod', str(ROOT / 'build/nodrop/nodrop.ko'), 'nod_audit_uid=0'])
    Path('/dev/pi-nodrop').touch(exist_ok=False)
    run(['mount', '--bind', '/proc/nodrop', '/dev/pi-nodrop'])
    run(['mount', '--bind', str(output / 'audit'), str(ROOT / 'results/audit')])
    run(['mount', '--make-private', str(ROOT / 'results/audit')])
    ctrl = str(ROOT / 'build/nodrop/scripts/ctrl/ctrl')
    run([ctrl, 'start']); run([ctrl, 'record'])
    stdout = run(['docker', 'run', '--rm', '--cpus', '1', '--memory', '2g',
                  '--mount', f'type=bind,source={ROOT},target={ROOT},readonly',
                  '--mount', f'type=bind,source={output / "audit"},target={ROOT / "results/audit"}',
                  '--mount', 'type=bind,source=/proc/nodrop,target=/dev/pi-nodrop',
                  '-w', str(ROOT), '-e', 'UV_THREADPOOL_SIZE=1', '-e', 'PI_NODROP_IOCTL_PATH=/dev/pi-nodrop',
                  'alexgshaw/openssl-selfsigned-cert:20251031', str(ROOT / 'node'), '-e', code])
    (output / 'container.log').write_text(stdout)
    (output / 'statistics.txt').write_text(run([ctrl, 'stat']))
finally:
    for path in [ROOT / 'results/audit', Path('/dev/pi-nodrop')]:
        if subprocess.run(['mountpoint', '-q', str(path)]).returncode == 0:
            run(['umount', str(path)])
    Path('/dev/pi-nodrop').unlink(missing_ok=True)
    if Path('/sys/module/nodrop').exists():
        run(['rmmod', 'nodrop'])
    diagnostic = '\n'.join(run(['dmesg', '--color=never']).splitlines()[len(before):])
    (output / 'dmesg-new.txt').write_text(diagnostic + '\n')
    assert not re.search(r'BUG:|Oops:|kernel panic', diagnostic)
events = [event for p in (output / 'audit').glob('*.buf') for event in decode_file(p, schema())]
counts = [json.loads(line) for p in (output / 'audit').glob('*.counts.jsonl') for line in p.read_text().splitlines()]
assert events and counts
assert all(e['call_ref'] == '686172626f720001' and e['policy_id'] == 1 for e in events)
assert all(e['call_ref'] == '686172626f720002' and e['policy_id'] == 2 for e in counts)
result = {'uid': 0, 'privileged_container': False, 'raw_events': len(events),
          'counted_events': sum(e['count'] for e in counts), 'count_rows': len(counts),
          'module_unloaded': not Path('/sys/module/nodrop').exists(), 'model_requests': 0}
(output / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result))
