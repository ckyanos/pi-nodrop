"""WSL host transport for the existing 6.8 test VM; never loads a host module."""
import argparse
import pathlib
import shlex
import subprocess
import tarfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
TARGET = 'kmoddebug@192.168.123.142'
GUEST = '/home/kmoddebug/pi-nodrop'
OPTIONS = ['-i', '/root/.ssh/kernel_module_lab', '-o',
           'UserKnownHostsFile=/root/.ssh/kernel_module_lab_known_hosts', '-o',
           'StrictHostKeyChecking=yes', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10',
           '-o', 'ControlMaster=auto', '-o', 'ControlPersist=300', '-o',
           'ControlPath=/tmp/pi-nodrop-ssh']

def ssh(command, check=True):
    return subprocess.run(['ssh', *OPTIONS, TARGET, command], check=check)

def sync():
    archive = pathlib.Path('/tmp/pi-nodrop-source.tar.gz')
    with tarfile.open(archive, 'w:gz') as tar:
        for path in ROOT.iterdir():
            if path.name not in ('.git', 'node_modules', 'build', 'results'):
                tar.add(path, arcname=path.name, filter=lambda info: None if '__pycache__' in info.name else info)
    ssh('mkdir -p ' + GUEST)
    subprocess.run(['scp', *OPTIONS, str(archive), TARGET + ':/tmp/pi-nodrop-source.tar.gz'], check=True)
    ssh('tar -xzf /tmp/pi-nodrop-source.tar.gz -C ' + GUEST)

parser = argparse.ArgumentParser()
parser.add_argument('action', choices=['probe', 'sync', 'runtime', 'exec', 'fetch', 'shutdown'])
parser.add_argument('command', nargs='?', default='true')
args = parser.parse_args()
if args.action == 'probe':
    ssh('uname -a; command -v node npm cmake gcc; ls -d /home/kmoddebug/*; '
        'sudo -n ls /root; lsmod | grep nodrop || true; free -h')
elif args.action == 'sync': sync()
elif args.action == 'runtime':
    subprocess.run(['scp', *OPTIONS, '/tmp/pi-nodrop-runtime.tar.gz', TARGET + ':/tmp/pi-nodrop-runtime.tar.gz'], check=True)
    ssh('tar -xzf /tmp/pi-nodrop-runtime.tar.gz -C ' + GUEST + ' && chmod +x ' + GUEST + '/node')
elif args.action == 'exec': ssh('cd ' + GUEST + ' && ' + args.command)
elif args.action == 'fetch':
    (ROOT / 'results').mkdir(exist_ok=True)
    subprocess.run(['scp', *OPTIONS, '-r', TARGET + ':' + GUEST + '/results/.', str(ROOT / 'results')], check=True)
elif args.action == 'shutdown':
    subprocess.run(['virsh', '-c', 'qemu:///system', 'shutdown', 'kmod-noble-68'], check=True)
