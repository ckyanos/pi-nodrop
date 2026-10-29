"""Inspect the configured libvirt VM and host network."""
import pathlib
import subprocess
from lab_config import required


def run(args):
    result = subprocess.run(args, capture_output=True, text=True)
    print('$', ' '.join(args))
    print(result.stdout[-8000:])
    print(result.stderr[-1500:])


vm = required('PI_NODROP_VM_NAME')
for command in (
    ['virsh', '-c', 'qemu:///system', 'domiflist', vm],
    ['virsh', '-c', 'qemu:///system', 'domifaddr', vm, '--source', 'agent'],
    ['ip', '-brief', 'address'], ['ip', 'neigh'],
    ['tail', '-n', '35', str(pathlib.PurePosixPath('/var/log/libvirt/qemu') / (vm + '.log'))],
):
    run(command)
