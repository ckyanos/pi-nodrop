"""Fetch pinned Terminal-Bench fixtures and export task images for the VM runner."""
import argparse
import hashlib
import json
import os
import pathlib
import subprocess
import uuid

ROOT = pathlib.Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--cache', type=pathlib.Path, default=ROOT / 'build/terminal-bench')
parser.add_argument('--direct', action='store_true', help='Use skopeo with proxy variables unset for image downloads')
args = parser.parse_args()
cache = args.cache.expanduser().resolve()
cache.mkdir(parents=True, exist_ok=True)
manifest = json.loads((ROOT / 'experiments/terminal-bench.json').read_text())
source = cache / 'source'
if not source.exists():
    autocrlf = str(manifest.get('checkout', {}).get('core.autocrlf', False)).lower()
    subprocess.run(['git', 'clone', '--config', 'core.autocrlf=' + autocrlf, '--no-checkout',
                    manifest['repository'], str(source)], check=True)
    subprocess.run(['git', '-C', str(source), 'checkout', '--detach', manifest['revision']], check=True)
revision = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
assert revision == manifest['revision'], 'Dataset revision differs from the manifest'

for task in manifest['tasks']:
    task_source = source / 'tasks' / task['name']
    for filename, digest in task['files'].items():
        assert hashlib.sha256((task_source / filename).read_bytes()).hexdigest() == digest, filename
    image = task['image']
    reference = image + '@' + task['image_digest'] if task.get('image_digest') else image
    rootfs_archive = cache / (task['name'] + '.rootfs.tar')
    if rootfs_archive.exists():
        print('Cached:', rootfs_archive, flush=True)
        continue
    if args.direct:
        environment = {k: v for k, v in os.environ.items() if k.lower() not in
                       ('http_proxy', 'https_proxy', 'all_proxy')}
        archive = cache / (task['name'] + '.docker.tar')
        subprocess.run(['skopeo', 'copy', 'docker://' + reference,
                        'docker-archive:' + str(archive) + ':' + image], env=environment, check=True)
        subprocess.run(['docker', 'load', '-i', str(archive)], check=True)
    else:
        subprocess.run(['docker', 'pull', reference], check=True)
    container = 'pi-nodrop-export-' + uuid.uuid4().hex[:12]
    subprocess.run(['docker', 'create', '--name', container, reference if not args.direct else image], check=True)
    try:
        subprocess.run(['docker', 'export', container, '-o', str(rootfs_archive)], check=True)
    finally:
        subprocess.run(['docker', 'rm', container], check=True)
    print('Exported:', rootfs_archive, flush=True)

verifier = cache / 'verifier/python'
if not verifier.exists():
    verifier.parent.mkdir(parents=True, exist_ok=True)
    image = manifest['tasks'][0]['image']
    if not args.direct and manifest['tasks'][0].get('image_digest'):
        image += '@' + manifest['tasks'][0]['image_digest']
    container = 'pi-nodrop-verifier-' + uuid.uuid4().hex[:12]
    subprocess.run(['docker', 'create', '--name', container, image], check=True)
    try:
        subprocess.run(['docker', 'cp', container + ':/usr/local', str(verifier)], check=True)
    finally:
        subprocess.run(['docker', 'rm', container], check=True)
    subprocess.run(['docker', 'run', '--rm', '-v', str(verifier) + ':/out', image,
                    'python', '-m', 'pip', 'install', '--target', '/out/lib/python3.13/site-packages',
                    'pytest==8.4.1', 'pytest-json-ctrf==0.3.5'], check=True)
print('Task fixtures:', source / 'tasks')
print('Verifier Python:', verifier)
