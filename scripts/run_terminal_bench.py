"""Run a Terminal-Bench task root filesystem with Pi and NoDrop in a Linux 6.8 VM."""
import argparse
import hashlib
import json
import os
import pathlib
import re
import shutil
import signal
import subprocess
import time
from decode import decode
from test_credentials import get_ibrain_credential

ROOT = pathlib.Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('task', type=pathlib.Path, help='Terminal-Bench task directory')
parser.add_argument('--rootfs', type=pathlib.Path, required=True, help='Fresh exported task image filesystem')
parser.add_argument('--agent-config', type=pathlib.Path, help='Private model configuration for live sessions')
parser.add_argument('--credential', choices=['project', 'personal'], help='Default: project')
parser.add_argument('--replay', type=pathlib.Path, help='Saved Pi transcript; execute tools without model requests')
parser.add_argument('--verifier-python', type=pathlib.Path, required=True)
parser.add_argument('--output', type=pathlib.Path, required=True)
parser.add_argument('--timeout', type=int, default=900)
parser.add_argument('--workdir', default='/app', help='Task image working directory')
parser.add_argument('--audit', choices=['on', 'off'], default='on')
parser.add_argument('--policies', type=pathlib.Path, help='Tool-to-retention policy JSON for the control interface')
parser.add_argument('--control-mode', choices=['agent', 'agent-names', 'configured', 'fixed-raw'], default='agent')
parser.add_argument('--output-mode', choices=['inline', 'reference'], default='reference')
parser.add_argument('--inline-bytes', type=int, default=4096)
args = parser.parse_args()
assert bool(args.agent_config) != bool(args.replay), 'Provide either --agent-config or --replay'
assert not args.replay or args.audit == 'on', 'Tool replay uses the NoDrop execution backend'
policies = json.loads(args.policies.read_text()) if args.policies else {}
child_env = os.environ.copy()
if args.agent_config:
    settings = json.loads((args.agent_config / 'settings.json').read_text())
    if settings['defaultProvider'] == 'ibrain':
        key, credential_name = get_ibrain_credential(args.credential)
        child_env['PI_NODROP_API_CREDENTIAL'] = credential_name.removesuffix('-ak-api')
        # A shell may discard environment names containing hyphens; forward in memory.
        child_env['PI_NODROP_TEST_API_KEY'] = key
        child_env['PI_NODROP_TEST_API_CREDENTIAL_NAME'] = credential_name
assert isinstance(policies, dict) and all(v in ('raw', 'counts') for v in policies.values()), 'Invalid policies'
task, rootfs, output = [p.resolve() for p in (args.task, args.rootfs, args.output)]
assert os.geteuid() == 0 and os.uname().release.startswith('6.8.'), 'Run as root in the Linux 6.8 VM'
assert not pathlib.Path('/sys/module/nodrop').exists(), 'A NoDrop module is already loaded'
assert rootfs != pathlib.Path('/') and (rootfs / 'app').is_dir(), 'Provide an extracted task filesystem'
assert not output.exists(), 'Use a new trial output directory'
output.mkdir(parents=True)
(output / 'audit').mkdir()
subprocess.run(['chown', '-R', '1000:1000', str(output), str(rootfs / 'app')], check=True)
mounts = []


def run(command, log=None, check=True, **kwargs):
    result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **kwargs)
    if log:
        (output / log).write_text(result.stdout)
    if check and result.returncode:
        raise RuntimeError(f'{command[0]} exited {result.returncode}: {result.stdout[-600:]}')
    return result


def bind(source, destination, readonly=False):
    target = rootfs / str(destination).lstrip('/')
    if source.is_dir():
        target.mkdir(parents=True, exist_ok=True)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.touch(exist_ok=True)
    run(['mount', '--bind', str(source), str(target)])
    mounts.append(target)
    if readonly:
        run(['mount', '-o', 'remount,bind,ro', str(target)])


def stop_task_processes():
    stopped = []
    for proc in pathlib.Path('/proc').iterdir():
        if not proc.name.isdigit():
            continue
        try:
            if proc.stat().st_uid == 1000 and (proc / 'root').resolve() == rootfs:
                os.kill(int(proc.name), signal.SIGKILL)
                stopped.append(int(proc.name))
        except (ProcessLookupError, FileNotFoundError, PermissionError):
            continue
    return stopped


before = run(['dmesg', '--color=never']).stdout.splitlines()
loaded = False
started = time.time()
try:
    host_audit = ROOT / 'results/audit'
    host_audit.mkdir(parents=True, exist_ok=True)
    run(['mount', '--bind', str(output / 'audit'), str(host_audit)])
    mounts.append(host_audit)
    runner = 'scripts/replay_tools.mjs' if args.replay else 'scripts/terminal_bench.mjs'
    for name in ['src', 'node_modules', 'node', runner,
                 *(['scripts/test-credentials.mjs'] if not args.replay else []),
                 'build/context.node', 'build/nodrop/monitor/monitor']:
        bind(ROOT / name, ROOT / name, readonly=True)
    bind(output / 'audit', ROOT / 'results/audit')
    bind(output, '/run/pi-nodrop-output')
    if args.replay:
        bind(args.replay.resolve(), '/run/pi-nodrop-replay.json', readonly=True)
    else:
        bind(args.agent_config.resolve(), '/run/pi-nodrop-agent')
    bind(pathlib.Path('/proc'), '/proc')
    bind(pathlib.Path('/dev'), '/dev')
    bind(pathlib.Path('/etc/resolv.conf').resolve(), '/etc/resolv.conf', readonly=True)
    instruction = rootfs / 'run/pi-nodrop-instruction.md'
    instruction.write_bytes((task / 'instruction.md').read_bytes())
    home = rootfs / 'tmp/pi-home'
    home.mkdir(parents=True, exist_ok=True)
    if (rootfs / 'root/.gitconfig').is_file():
        shutil.copy2(rootfs / 'root/.gitconfig', home / '.gitconfig')
    run(['chown', '-R', '1000:1000', str(home)])
    control = str(ROOT / 'build/nodrop/scripts/ctrl/ctrl')
    if args.audit == 'on':
        run(['insmod', str(ROOT / 'build/nodrop/nodrop.ko')], 'insmod.txt')
        loaded = True
        run([control, 'start'], 'start.txt')
        run([control, 'record'], 'record.txt')
    command = ['chroot', '--userspec=1000:1000', str(rootfs), '/bin/sh', '-c',
               'cd "$1" && shift && exec "$@"', 'pi-nodrop', args.workdir,
               '/usr/bin/env', 'HOME=/tmp/pi-home',
               'PI_NODROP_AGENT_DIR=/run/pi-nodrop-agent', 'PI_NODROP_TRIAL_DIR=/run/pi-nodrop-output',
               f'PI_NODROP_AUDIT={args.audit}', f'PI_NODROP_POLICIES={json.dumps(policies)}',
               f'PI_NODROP_CONTROL_MODE={args.control_mode}',
               f'PI_NODROP_OUTPUT_MODE={args.output_mode}', f'PI_NODROP_INLINE_BYTES={args.inline_bytes}',
               f'PI_NODROP_TIMEOUT_SEC={args.timeout}', str(ROOT / 'node'),
               str(ROOT / runner), '/run/pi-nodrop-replay.json' if args.replay else '/run/pi-nodrop-instruction.md']
    with (output / 'agent.log').open('w') as log:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
                                   env=child_env)
        try:
            agent_status = process.wait(timeout=args.timeout + 90)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                agent_status = process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                agent_status = process.wait()
    stopped = stop_task_processes()
    if loaded:
        run([control, 'stat'], 'statistics.txt')
        run(['rmmod', 'nodrop'], 'rmmod.txt')
        loaded = False
    # The verifier files become available only after the agent has exited.
    bind(task / 'tests', '/tests', readonly=True)
    bind(args.verifier_python.resolve(), '/opt/pi-verifier', readonly=True)
    bind(output, '/logs/verifier')
    if (task / 'tests/test.py').is_file():
        shutil.copy2(task / 'tests/test.py', rootfs / 'app/test.py')
    verifier = run(['chroot', str(rootfs), '/bin/sh', '-c',
                    'cd /app && exec /usr/bin/env PYTHONHOME=/opt/pi-verifier '
                    'LD_LIBRARY_PATH=/opt/pi-verifier/lib '
                    'PATH=/opt/pi-verifier/bin:/usr/local/bin:/usr/bin:/bin '
                    '/opt/pi-verifier/bin/python3 -m pytest --ctrf /logs/verifier/ctrf.json '
                    '/tests/test_outputs.py -rA'], 'verifier.log', check=False, timeout=1200)
    (output / 'reward.txt').write_text('1\n' if verifier.returncode == 0 else '0\n')
    (output / 'pi').mkdir(exist_ok=True)
    (output / 'pi/calls.jsonl').touch(exist_ok=True)
    calls, events, counts = decode(output)
    if args.audit == 'on':
        lines = (output / 'statistics.txt').read_text().strip().splitlines()
        statistics = dict(zip(lines[0].split(), map(int, lines[1].split())))
    else:
        statistics = {'n_evts': 0, 'drop_evts': 0, 'drop_overflow': 0, 'drop_unsolved': 0}
    begins = [c for c in calls if c['kind'] == 'begin']
    ends = [c for c in calls if c['kind'] == 'end']
    summary = {'task': task.name, 'audit': args.audit, 'control_mode': args.control_mode,
               'execution': 'tool-replay' if args.replay else 'live-model',
               'policies': policies if args.audit == 'on' and args.control_mode == 'configured' else None,
               'agent_exit_code': agent_status, 'verifier_exit_code': verifier.returncode,
               'reward': int(verifier.returncode == 0), 'calls': len(begins),
               'call_ends': len(ends), 'raw_events': len(events), 'histogram_rows': len(counts),
               'histogram_events': sum(c['count'] for c in counts), 'statistics': statistics,
               'associated_events': sum(e['tool_call_id'] is not None for e in events),
               'event_accounting_matches': statistics['n_evts'] == len(events) + sum(c['count'] for c in counts),
               'forced_cleanup_pids': stopped, 'elapsed_sec': time.time() - started,
               'instruction_sha256': hashlib.sha256((task / 'instruction.md').read_bytes()).hexdigest(),
               'environment': {'kernel': os.uname().release, 'isolation': 'chroot', 'uid': 1000,
                               'workdir': args.workdir}}
    summary['audit_checks_passed'] = bool(begins) and len(ends) == len(begins) and all(
        e['tool_call_id'] is not None for e in events) and summary['event_accounting_matches'] and statistics['drop_unsolved'] == 0
    (output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary), flush=True)
finally:
    stop_task_processes()
    if loaded:
        run(['rmmod', 'nodrop'], 'rmmod.txt', check=False)
    after = run(['dmesg', '--color=never']).stdout.splitlines()
    diagnostic = '\n'.join(after[len(before):])
    (output / 'dmesg-new.txt').write_text(diagnostic + '\n')
    cleanup = {'module_unloaded': not pathlib.Path('/sys/module/nodrop').exists(),
               'kernel_errors': bool(re.search(r'BUG:|Oops:|kernel panic|context inheritance failed', diagnostic, re.I))}
    for mount in reversed(mounts):
        run(['umount', str(mount)], check=False)
    (output / 'cleanup.json').write_text(json.dumps(cleanup, indent=2) + '\n')
