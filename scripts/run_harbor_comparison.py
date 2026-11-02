"""Run three Pi conditions using upstream Harbor jobs and task verifiers."""
import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import shutil
import tempfile
from test_credentials import get_ibrain_credential

from harbor.job import Job
from harbor.models.job.config import DatasetConfig, JobConfig
from harbor.models.trial.config import AgentConfig, EnvironmentConfig

ROOT = Path(__file__).resolve().parents[1]
TASKS = ['openssl-selfsigned-cert', 'log-summary-date-ranges', 'fix-git']
MODES = ['baseline', 'fixed-raw', 'agent', 'agent-names']


def command(args, output=None):
    result = subprocess.run(args, check=True, capture_output=True, text=True)
    if output:
        output.write_text(result.stdout + result.stderr)
    return result.stdout


async def main(args):
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    assert os.uname().release.startswith('6.8.')
    assert not Path('/sys/module/nodrop').exists()
    settings = json.loads((args.agent_config / 'settings.json').read_text())
    model_name = settings['defaultProvider'] + '/' + settings['defaultModel']
    credential = get_ibrain_credential(args.credential) if settings['defaultProvider'] == 'ibrain' and not args.install_only else None
    model = json.loads((args.agent_config / 'models.json').read_text())['providers'][settings['defaultProvider']]['models'][0]
    assert model['maxTokens'] == 2048
    assert settings['retry']['enabled'] is False and settings['cacheWarming'] == 'off'
    plans = [('baseline', TASKS[0])] if args.install_only else (
        [tuple(case.split('--', 1)) for case in args.cases] if args.cases else [
            (mode, task) for mode in args.modes for task in args.task_names])
    provenance = {
        'harbor_version': importlib.metadata.version('harbor'),
        'kernel': os.uname().release,
        'docker_version': command(['docker', '--version']).strip(),
        'compose_version': command(['docker', 'compose', 'version']).strip(),
        'pi_version': '1.4.0', 'model': model_name, 'attempts_per_task_per_condition': 1,
        'credential_name': credential[1] if credential else None,
        'custom_output_presentation': False, 'custom_agent_loop': False,
        'custom_verifier': False, 'task_user_override': False,
        'baseline_agent_class': 'harbor.agents.installed.pi:Pi',
        'audited_agent_class': 'scripts.harbor_agent:NoDropPi',
        'apt_source_overrides': args.apt_sources is not None,
        'native_config_isolated_writable': True,
        'audit_output_mounted_in_host_and_container': True,
        'conditions': list(dict.fromkeys(mode for mode, _ in plans)),
        'cases': [mode + '--' + task for mode, task in plans],
        'agent_setup_timeout_sec': args.setup_timeout,
        'node_download_mirror': args.node_mirror,
        'source_sha256': {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                          for name in ['src/extension.mjs', 'src/client.mjs', 'src/tools.mjs', 'src/worker.mjs',
                                       'src/policy-tools.mjs', 'scripts/harbor_agent.py',
                                       'scripts/run_harbor_comparison.py',
                                       'scripts/test_credentials.py',
                                       'build/nodrop/nodrop.ko', 'build/context.node',
                                       'build/nodrop/monitor/monitor']},
    }
    (output / 'protocol.json').write_text(json.dumps(provenance, indent=2) + '\n')
    assert not Path('/dev/pi-nodrop').exists()
    for mode, task in plans:
        with tempfile.TemporaryDirectory(prefix='pi-nodrop-config-', dir=ROOT / 'build') as private:
            case_config = Path(private)
            for filename in ['settings.json', 'models.json', 'auth.json']:
                shutil.copyfile(args.agent_config / filename, case_config / filename)
                (case_config / filename).chmod(0o600)
            if credential:
                auth_path = case_config / 'auth.json'
                auth = json.loads(auth_path.read_text())
                auth['ibrain'] = {'type': 'api_key', 'key': credential[0]}
                auth_path.write_text(json.dumps(auth) + '\n')
            job_name = mode + '--' + task
            kwargs = {'version': '1.4.0', 'reasoning_effort': 'medium'}
            if args.node_mirror:
                kwargs['extra_env'] = {'NVM_NODEJS_ORG_MIRROR': args.node_mirror}
            agent = AgentConfig(name='pi', model_name=model_name, skip_model_parsing=True,
                                override_setup_timeout_sec=args.setup_timeout, kwargs=kwargs)
            if mode != 'baseline':
                agent = AgentConfig(import_path='scripts.harbor_agent:NoDropPi', model_name=model_name,
                                    skip_model_parsing=True, override_setup_timeout_sec=args.setup_timeout,
                                    kwargs={**kwargs, 'audit_mode': mode})
            config = JobConfig(
                job_name=job_name, jobs_dir=output, n_attempts=1, n_concurrent_trials=1,
                skip_credential_checks=True, install_only=args.install_only,
                agents=[agent], datasets=[DatasetConfig(path=args.tasks.resolve(),
                    task_names=[task])],
                environment=EnvironmentConfig(type='docker', mounts=[{
                    'type': 'bind', 'source': str(case_config),
                    'target': '/root/.pi/agent',
                }, *([{'type': 'bind', 'source': str((args.apt_sources / (task + '.sources')).resolve()),
                       'target': '/etc/apt/sources.list.d/debian.sources', 'read_only': True}]
                     if args.apt_sources else []),
                    *([{'type': 'bind', 'source': '/proc/nodrop', 'target': '/dev/pi-nodrop'},
                       {'type': 'bind', 'source': str(output / 'audit' / job_name),
                        'target': str(ROOT / 'results/audit')}]
                     if mode != 'baseline' else [])]),
            )
            loaded = False
            alias_created = False
            try:
                if mode != 'baseline':
                    command(['insmod', str(ROOT / 'build/nodrop/nodrop.ko'), 'nod_audit_uid=0'])
                    loaded = True
                    Path('/dev/pi-nodrop').touch(exist_ok=False)
                    alias_created = True
                    command(['mount', '--bind', '/proc/nodrop', '/dev/pi-nodrop'])
                    audit = output / 'audit' / job_name
                    audit.mkdir(parents=True, exist_ok=False)
                    command(['mount', '--bind', str(audit), str(ROOT / 'results/audit')])
                    command(['mount', '--make-private', str(ROOT / 'results/audit')])
                    command([str(ROOT / 'build/nodrop/scripts/ctrl/ctrl'), 'start'])
                    command([str(ROOT / 'build/nodrop/scripts/ctrl/ctrl'), 'record'])
                print('START ' + job_name, flush=True)
                job = await Job.create(config)
                await job.run()
                print('DONE ' + job_name, flush=True)
            finally:
                if loaded:
                    try:
                        command([str(ROOT / 'build/nodrop/scripts/ctrl/ctrl'), 'stat'], output / (job_name + '-statistics.txt'))
                    finally:
                        for mount in [ROOT / 'results/audit', Path('/dev/pi-nodrop')]:
                            if subprocess.run(['mountpoint', '-q', str(mount)]).returncode == 0:
                                command(['umount', str(mount)])
                        if alias_created:
                            Path('/dev/pi-nodrop').unlink()
                        command(['rmmod', 'nodrop'])
                assert not Path('/sys/module/nodrop').exists()
    print('HARBOR JOBS COMPLETE', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tasks', type=Path, required=True)
    parser.add_argument('--agent-config', type=Path, required=True)
    parser.add_argument('--credential', choices=['project', 'personal'], help='Default: project')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--install-only', action='store_true', help='Validate upstream installation without model calls')
    parser.add_argument('--modes', nargs='+', choices=MODES,
                        default=['baseline', 'fixed-raw', 'agent'])
    parser.add_argument('--task-names', nargs='+', choices=TASKS, default=TASKS)
    parser.add_argument('--cases', nargs='+', choices=[mode + '--' + task
                        for mode in MODES for task in TASKS])
    parser.add_argument('--apt-sources', type=Path, help='Optional common installation mirror configuration directory')
    parser.add_argument('--setup-timeout', type=float, default=900, help='Installation timeout; task execution timeouts stay in task.toml')
    parser.add_argument('--node-mirror', help='Optional common NVM download mirror')
    asyncio.run(main(parser.parse_args()))
