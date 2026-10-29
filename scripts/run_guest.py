"""Bounded root setup, unprivileged real-Pi test, evidence and module cleanup."""
import json
import os
import pathlib
import pwd
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
RESULTS = ROOT / 'results'
USER = pwd.getpwuid(1000).pw_name

def command(args, log=None, check=True):
    result = subprocess.run(args, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if log: (RESULTS / log).write_text(result.stdout)
    print(result.stdout[-5000:], flush=True)
    if check and result.returncode: raise RuntimeError(f'{args} exited {result.returncode}')
    return result

assert os.geteuid() == 0, 'run sudo python3 scripts/run_guest.py'
assert os.uname().release.startswith('6.8.'), 'This experiment targets the 6.8 guest'
assert not pathlib.Path('/sys/module/nodrop').exists(), 'Refusing to replace an already loaded module'
assert not RESULTS.exists(), 'Move previous results aside before a new run'
RESULTS.mkdir()
(RESULTS / 'audit').mkdir()
subprocess.run(['chown', '-R', '1000:1000', str(RESULTS)], check=True)
environment = { 'kernel': os.uname().release, 'node': subprocess.check_output([str(ROOT / 'node'), '--version'], text=True).strip(),
  'pi_version': json.loads((ROOT / 'node_modules/@earendil-works/pi-coding-agent/package.json').read_text())['version'],
  'uid': 1000, 'buffer_bytes': 1048576,
  'model': 'deterministic scripted stream; no network model call', 'started_at_ns': time.time_ns() }
(RESULTS / 'environment.json').write_text(json.dumps(environment, indent=2) + '\n')
before = command(['dmesg', '--color=never'], 'dmesg-before.txt').stdout.splitlines()
loaded = False
try:
    command(['insmod', str(ROOT / 'build/nodrop/nodrop.ko')], 'insmod.txt')
    loaded = True
    command([str(ROOT / 'build/nodrop/scripts/ctrl/ctrl'), 'start'], 'start.txt')
    command([str(ROOT / 'build/nodrop/scripts/ctrl/ctrl'), 'record'], 'record.txt')
    command(['runuser', '-u', USER, '--', str(ROOT / 'node'), 'tests/integration.mjs'], 'integration.txt')
    command(['runuser', '-u', USER, '--', 'env', 'UV_THREADPOOL_SIZE=1',
             str(ROOT / 'node'), 'tests/native-scope.mjs'], 'native-scope.txt')
finally:
    if loaded:
        command([str(ROOT / 'build/nodrop/scripts/ctrl/ctrl'), 'stat'], 'statistics.txt', check=False)
        command(['rmmod', 'nodrop'], 'rmmod.txt')
    after = command(['dmesg', '--color=never'], 'dmesg-after.txt').stdout.splitlines()
    (RESULTS / 'dmesg-new.txt').write_text('\n'.join(after[len(before):]) + '\n')
    (RESULTS / 'cleanup.json').write_text(json.dumps({'module_unloaded': not pathlib.Path('/sys/module/nodrop').exists()}))
