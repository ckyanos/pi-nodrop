"""External monitor lifecycle around Harbor's original Pi.run implementation."""
import asyncio
import json
import os
from pathlib import Path
import re
import signal
import subprocess
from typing import Literal

from harbor.agents.installed.pi import Pi, PiOptions

ROOT = Path(__file__).resolve().parents[1]


class ExternalAuditOptions(PiOptions):
    audit_mode: Literal['agentsight', 'sentinel']
    shared_dir: str
    external_root: str
    gateway_url: str
    case_name: str


class ExternalAuditPi(Pi):
    options_model = ExternalAuditOptions

    @staticmethod
    def name():
        return 'pi-external-audit'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._extra_env.update({'PI_AUDIT_MODE': self.options.audit_mode,
                                'PI_AUDIT_SHARED': '/audit-shared'})
        self.monitors = []

    async def install(self, environment):
        await super().install(environment)
        await environment.upload_file(ROOT / 'src/sentinel-extension.mjs', '/tmp/pi-audit-extension.mjs')

    def build_cli_flags(self):
        return (super().build_cli_flags() + ' --extension /tmp/pi-audit-extension.mjs').strip()

    async def _start_monitor(self, environment):
        shared = Path(self.options.shared_dir)
        while not (shared / 'ready.json').exists():
            await asyncio.sleep(.2)
        ready = json.loads((shared / 'ready.json').read_text())
        project = re.sub(r'[^a-z0-9_-]', '-', environment.session_id.lower())
        ids = subprocess.check_output(['docker', 'ps', '-q', '--no-trunc',
            '--filter', 'label=com.docker.compose.project=' + project,
            '--filter', 'label=com.docker.compose.service=main'], text=True).split()
        assert len(ids) == 1, ids
        cid = ids[0]
        host_pid = None
        pids = subprocess.check_output(['docker', 'top', cid, '-eo', 'pid'], text=True).splitlines()[1:]
        for pid in pids:
            pid = int(pid.strip())
            status = Path(f'/proc/{pid}/status').read_text()
            nspid = next((line for line in status.splitlines() if line.startswith('NSpid:')), '')
            if nspid and int(nspid.split()[-1]) == ready['pid']:
                host_pid = pid
                break
        assert host_pid, 'Pi host PID not found'
        (shared / 'monitor-subject.json').write_text(json.dumps({'container': cid, 'host_pid': host_pid, **ready}) + '\n')
        external = Path(self.options.external_root)
        if self.options.audit_mode == 'sentinel':
            env = dict(os.environ, OPENAI_API_KEY='local-transport-token',
                       OPENAI_BASE_URL=self.options.gateway_url + '/sentinel/' + self.options.case_name + '/v1/',
                       SSL_CERT_FILE=str(shared.parent.parent / 'gateway.crt'))
            cmd = [str(external / 'agent-sentinel/agent-sentinel'), '-cid', cid,
                   '-mount-path', str(shared), '-model', 'openai/gpt-4o', '-debug',
                   '-output', str(shared / 'monitor.jsonl')]
            proc = subprocess.Popen(cmd, env=env, stdout=open(shared / 'monitor-stdout.log', 'w'),
                                    stderr=subprocess.STDOUT, start_new_session=True)
            self.monitors.append(proc)
            while not (shared / 'computer-monitor.sock').exists():
                if proc.poll() is not None:
                    raise RuntimeError('AgentSentinel startup failed; inspect native monitor log')
                await asyncio.sleep(.2)
        else:
            # The Node binary embeds OpenSSL; attach the original SSL probes to that ELF.
            env = dict(os.environ, AGENTSIGHT_SSL_PATH=f'/proc/{host_pid}/exe')
            commands = [
                ([str(external / 'agentsight-bin/agentsight'), 'trace', '--ssl', 'false',
                  '--comm', 'pi', '--output', str(shared / 'process-trace.jsonl'), '--quiet'], 'process-monitor.log'),
                (['stdbuf', '-oL', str(external / 'agentsight-paper/bpf/sslsniff'), '-p', str(host_pid), '-v'], 'ssl-native.jsonl'),
            ]
            for cmd, name in commands:
                p = subprocess.Popen(cmd, env=env, stdout=open(shared / name, 'w'),
                                     stderr=open(shared / (name + '.stderr'), 'w'), start_new_session=True)
                self.monitors.append(p)
            await asyncio.sleep(12)
            if any(p.poll() is not None for p in self.monitors):
                raise RuntimeError('AgentSight startup failed; inspect native collector logs')
            stderr = (shared / 'ssl-native.jsonl.stderr').read_text()
            if 'no program attached' in stderr:
                raise RuntimeError('AgentSight SSL probe attachment failed: ' + stderr[-1000:])
            if stderr.count("symbol address match for 'SSL_do_handshake'") < 2:
                raise RuntimeError('AgentSight SSL probe attachment not completed')
        (shared / 'monitor-ready').touch()

    async def run(self, instruction, environment, context):
        watcher = asyncio.create_task(self._start_monitor(environment))
        task = asyncio.create_task(super().run(instruction, environment, context))
        try:
            done, _ = await asyncio.wait([task, watcher], return_when=asyncio.FIRST_COMPLETED)
            if watcher in done:
                await watcher
            await task
            if self.options.audit_mode == 'sentinel' and not (Path(self.options.shared_dir) / 'client-ready').exists():
                raise RuntimeError('Pi did not establish its native AgentSentinel connection')
        finally:
            for pending in (watcher, task):
                if not pending.done():
                    pending.cancel()
            await asyncio.gather(watcher, task, return_exceptions=True)
            # Drain native producers before stopping their consumers.
            for proc in self.monitors:
                if proc.poll() is None:
                    for path in Path('/proc').glob('[0-9]*/stat'):
                        try:
                            fields = path.read_text().split()
                            if int(fields[3]) == proc.pid:
                                os.kill(int(path.parent.name), signal.SIGINT)
                        except (ProcessLookupError, FileNotFoundError):
                            pass
            await asyncio.sleep(2)
            for proc in self.monitors:
                if proc.poll() is None:
                    proc.send_signal(signal.SIGINT)
                    try:
                        await asyncio.to_thread(proc.wait, timeout=20)
                    except subprocess.TimeoutExpired:
                        os.killpg(proc.pid, signal.SIGTERM)
                        await asyncio.to_thread(proc.wait, timeout=10)
