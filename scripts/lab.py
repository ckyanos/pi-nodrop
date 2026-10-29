"""Transfer sources, runtimes and results to a configured Linux test VM."""
import argparse
import shlex
import subprocess
import tarfile
from lab_config import ROOT, RUNTIME_ARCHIVE, SOURCE_ARCHIVE, guest_dir, required

OPTIONS = ['-o', 'StrictHostKeyChecking=yes', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10']


def ssh(command, check=True):
    return subprocess.run(['ssh', *OPTIONS, required('PI_NODROP_SSH_TARGET'), command], check=check)


def copy(source, destination, recursive=False):
    return subprocess.run(['scp', *OPTIONS, *(['-r'] if recursive else []),
                           str(source), str(destination)], check=True)


def sync():
    destination = shlex.quote(guest_dir())
    target = required('PI_NODROP_SSH_TARGET')
    SOURCE_ARCHIVE.parent.mkdir(parents=True, exist_ok=True)
    files = subprocess.check_output(
        ['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'], cwd=ROOT).decode().split('\0')
    with tarfile.open(SOURCE_ARCHIVE, 'w:gz') as tar:
        for name in files:
            if name and name.split('/')[0] != 'results' and (ROOT / name).is_file():
                tar.add(ROOT / name, arcname=name, recursive=False)
    ssh('mkdir -p ' + destination)
    copy(SOURCE_ARCHIVE, target + ':/tmp/pi-nodrop-source.tar.gz')
    ssh('tar -xzf /tmp/pi-nodrop-source.tar.gz -C ' + destination)


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('action', choices=['probe', 'sync', 'runtime', 'exec', 'fetch', 'shutdown'])
parser.add_argument('command', nargs='?', default='true')
args = parser.parse_args()
if args.action == 'probe':
    ssh('uname -a; command -v node npm cmake gcc; '
        'lsmod | grep nodrop || true; free -h')
elif args.action == 'sync':
    sync()
elif args.action == 'runtime':
    destination = shlex.quote(guest_dir())
    copy(RUNTIME_ARCHIVE, required('PI_NODROP_SSH_TARGET') + ':/tmp/pi-nodrop-runtime.tar.gz')
    ssh('tar -xzf /tmp/pi-nodrop-runtime.tar.gz -C ' + destination
        + ' && chmod +x ' + shlex.quote(guest_dir() + '/node'))
elif args.action == 'exec':
    ssh('cd ' + shlex.quote(guest_dir()) + ' && ' + args.command)
elif args.action == 'fetch':
    (ROOT / 'results').mkdir(exist_ok=True)
    copy(required('PI_NODROP_SSH_TARGET') + ':' + guest_dir() + '/results/.', ROOT / 'results', recursive=True)
elif args.action == 'shutdown':
    subprocess.run(['virsh', '-c', 'qemu:///system', 'shutdown', required('PI_NODROP_VM_NAME')], check=True)
