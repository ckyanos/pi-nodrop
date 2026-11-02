"""Run five native Pi conditions against the original three Terminal-Bench tasks."""
import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from harbor.job import Job
from harbor.models.job.config import DatasetConfig, JobConfig
from harbor.models.trial.config import AgentConfig, EnvironmentConfig
from scripts.prepare_unlimited_tasks import prepare_unlimited_tasks

ROOT = Path(__file__).resolve().parents[1]
TASKS = ['openssl-selfsigned-cert', 'log-summary-date-ranges', 'fix-git']
MODES = ['baseline', 'agentsight', 'sentinel', 'fixed-raw', 'agent']


def command(args, output=None):
    p = subprocess.run(args, check=True, capture_output=True, text=True)
    if output:
        output.write_text(p.stdout + p.stderr)
    return p.stdout


async def main(args):
    out = args.output.resolve()
    assert os.uname().release.startswith('6.8.')
    assert not Path('/sys/module/nodrop').exists()
    assert importlib.metadata.version('harbor') == '0.25.0'
    out.mkdir(parents=True, exist_ok=True)
    settings = json.loads((args.agent_config / 'settings.json').read_text())
    model_name = settings['defaultProvider'] + '/' + settings['defaultModel']
    plans = [(mode, task) for task in args.tasks_names for mode in args.modes]
    if args.cases:
        plans = [tuple(case.split('--', 1)) for case in args.cases]
    if args.keep_module:
        assert len(plans) == 1 and plans[0][0] in ('fixed-raw', 'agent'), 'Retain the module only for one isolated NoDrop trial per boot'
    task_inputs, task_manifest = prepare_unlimited_tasks(
        args.tasks, out / 'task-inputs', [task for _, task in plans])
    provenance = {'model': model_name, 'pi': '1.4.0', 'harbor': '0.25.0',
        'kernel': os.uname().release, 'credential': 'project-ak-api',
        'business_tools': ['read', 'bash', 'edit', 'write'], 'native_pi_loop': True,
        'original_task_verifiers': True, 'original_task_resources': True,
        'attempts_per_case': 1, 'cumulative_token_turn_tool_limits': None,
        'automatic_trial_retries': False, 'task_timeout_override': True,
        'agent_timeout_sec': None, 'agent_max_timeout_sec': None,
        'task_input_preparation': task_manifest,
        'nodrop_module_lifetime': 'retained until VM restart' if args.keep_module else 'per-trial load and unload',
        'plans': [m + '--' + t for m, t in plans],
        'source_sha256': {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest()
            for p in ['scripts/run_fiveway_comparison.py', 'scripts/harbor_external_audit.py',
                      'src/sentinel-extension.mjs', 'src/extension.mjs', 'src/client.mjs', 'src/tools.mjs',
                      'build/context.node', 'build/nodrop/nodrop.ko', 'build/nodrop/monitor/monitor',
                      'scripts/analyze_agentsight_trial.py', 'scripts/harbor_cached_pi.py',
                      'scripts/prepare_unlimited_tasks.py']},
        'external_binary_sha256': {name: hashlib.sha256((args.external_root / name).read_bytes()).hexdigest()
            for name in ['agent-sentinel/agent-sentinel', 'agentsight-paper/bpf/sslsniff', 'agentsight-bin/agentsight']}}
    if args.install_cache:
        metadata = json.loads(args.install_cache_metadata.read_text())
        assert hashlib.sha256(args.install_cache.read_bytes()).hexdigest() == metadata['archive_sha256']
        provenance['official_installation_cache'] = metadata
    protocol = out / ('protocol-' + args.segment + '.json')
    assert not protocol.exists(), 'Preserve existing protocol segment'
    protocol.write_text(json.dumps(provenance, indent=2) + '\n')
    for mode, task in plans:
        name = mode + '--' + task
        request_label = name + ('~' + args.request_label_suffix if args.request_label_suffix else '')
        assert not (out / name).exists(), 'Preserve first attempt: ' + name
        shared = out / 'monitor' / name
        shared.mkdir(parents=True, exist_ok=False)
        (shared / 'request-label.json').write_text(json.dumps({'case': name, 'request_label': request_label}) + '\n')
        with tempfile.TemporaryDirectory(prefix='fiveway-config-', dir=ROOT / 'build') as private:
            config_dir = Path(private)
            for filename in ['settings.json', 'models.json', 'auth.json']:
                shutil.copy2(args.agent_config / filename, config_dir / filename)
            models = json.loads((config_dir / 'models.json').read_text())
            models['providers']['ibrain']['baseUrl'] = args.gateway_url + '/business/' + request_label + '/v1'
            (config_dir / 'models.json').write_text(json.dumps(models))
            kwargs = {'version': '1.4.0', 'reasoning_effort': 'medium'}
            agent_env = {'NODE_EXTRA_CA_CERTS': '/audit-ca.crt'}
            if args.install_cache:
                agent_env['PI_INSTALL_CACHE_METADATA'] = str(args.install_cache_metadata)
            agent = AgentConfig(name='pi', model_name=model_name, skip_model_parsing=True,
                                override_setup_timeout_sec=900, kwargs=kwargs, env=agent_env)
            mounts = [{'type': 'bind', 'source': str(config_dir), 'target': '/root/.pi/agent'},
                      {'type': 'bind', 'source': str(out / 'gateway.crt'), 'target': '/audit-ca.crt', 'read_only': True}]
            if args.install_cache:
                mounts.append({'type': 'bind', 'source': str(args.install_cache),
                               'target': '/tmp/pi-install-cache.tar', 'read_only': True})
                agent = AgentConfig(import_path='scripts.harbor_cached_pi:CachedPi', model_name=model_name,
                    skip_model_parsing=True, override_setup_timeout_sec=900, kwargs=kwargs, env=agent_env)
            if args.apt_sources:
                mounts.append({'type': 'bind', 'source': str(args.apt_sources / (task + '.sources')),
                               'target': '/etc/apt/sources.list.d/debian.sources', 'read_only': True})
            if mode in ('fixed-raw', 'agent'):
                agent = AgentConfig(import_path='scripts.harbor_cached_pi:CachedNoDropPi' if args.install_cache else 'scripts.harbor_agent:NoDropPi', model_name=model_name,
                    skip_model_parsing=True, override_setup_timeout_sec=900,
                    kwargs={**kwargs, 'audit_mode': mode}, env=agent_env)
                mounts.extend([{'type': 'bind', 'source': '/proc/nodrop', 'target': '/dev/pi-nodrop'},
                    {'type': 'bind', 'source': str(out / 'audit' / name), 'target': str(ROOT / 'results/audit')}])
            elif mode in ('agentsight', 'sentinel'):
                mounts.append({'type': 'bind', 'source': str(shared), 'target': '/audit-shared'})
                agent = AgentConfig(import_path='scripts.harbor_cached_pi:CachedExternalAuditPi' if args.install_cache else 'scripts.harbor_external_audit:ExternalAuditPi',
                    model_name=model_name, skip_model_parsing=True, override_setup_timeout_sec=900,
                    kwargs={**kwargs, 'audit_mode': mode, 'shared_dir': str(shared),
                        'external_root': str(args.external_root.resolve()),
                        'gateway_url': args.gateway_url, 'case_name': request_label}, env=agent_env)
            cfg = JobConfig(job_name=name, jobs_dir=out, n_attempts=1, n_concurrent_trials=1,
                skip_credential_checks=True, agents=[agent],
                datasets=[DatasetConfig(path=task_inputs, task_names=[task])],
                environment=EnvironmentConfig(type='docker', mounts=mounts))
            loaded = False
            try:
                if mode in ('fixed-raw', 'agent'):
                    command(['insmod', str(ROOT / 'build/nodrop/nodrop.ko'), 'nod_audit_uid=0'])
                    loaded = True
                    Path('/dev/pi-nodrop').touch(exist_ok=False)
                    command(['mount', '--bind', '/proc/nodrop', '/dev/pi-nodrop'])
                    audit = out / 'audit' / name
                    audit.mkdir(parents=True, exist_ok=False)
                    command(['mount', '--bind', str(audit), str(ROOT / 'results/audit')])
                    command(['mount', '--make-private', str(ROOT / 'results/audit')])
                    command([str(ROOT / 'build/nodrop/scripts/ctrl/ctrl'), 'start'])
                    command([str(ROOT / 'build/nodrop/scripts/ctrl/ctrl'), 'record'])
                print('START ' + name, flush=True)
                job = await Job.create(cfg)
                await job.run()
                print('DONE ' + name, flush=True)
                if mode == 'agentsight':
                    p = subprocess.run(['python3', str(ROOT / 'scripts/analyze_agentsight_trial.py'),
                        str(shared), str(args.external_root), args.gateway_url, request_label],
                        stdout=open(shared / 'analysis-stdout.log', 'w'), stderr=subprocess.STDOUT)
                    print('AgentSight analysis exit', p.returncode, flush=True)
            finally:
                if loaded:
                    try:
                        command([str(ROOT / 'build/nodrop/scripts/ctrl/ctrl'), 'stat'], out / (name + '-statistics.txt'))
                    finally:
                        for path in (ROOT / 'results/audit', Path('/dev/pi-nodrop')):
                            if subprocess.run(['mountpoint', '-q', str(path)]).returncode == 0:
                                command(['umount', str(path)])
                        Path('/dev/pi-nodrop').unlink(missing_ok=True)
                        if not args.keep_module:
                            command(['rmmod', 'nodrop'])
            assert args.keep_module or not Path('/sys/module/nodrop').exists()
    print('FIVE-WAY SEGMENT COMPLETE', flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--tasks', type=Path, required=True)
    p.add_argument('--agent-config', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--external-root', type=Path, required=True)
    p.add_argument('--gateway-url', required=True)
    p.add_argument('--apt-sources', type=Path)
    p.add_argument('--modes', nargs='+', choices=MODES, default=MODES)
    p.add_argument('--tasks-names', nargs='+', choices=TASKS, default=TASKS)
    p.add_argument('--cases', nargs='+')
    p.add_argument('--segment', default='main')
    p.add_argument('--install-cache', type=Path)
    p.add_argument('--install-cache-metadata', type=Path)
    p.add_argument('--keep-module', action='store_true', help='Keep the module resident until the isolated experiment VM reboots')
    p.add_argument('--request-label-suffix', default='')
    asyncio.run(main(p.parse_args()))
