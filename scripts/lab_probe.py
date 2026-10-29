import subprocess

def run(args):
    result = subprocess.run(args, capture_output=True, text=True)
    print('$', ' '.join(args))
    print(result.stdout[-8000:])
    print(result.stderr[-1500:])

for command in (
    ['virsh', '-c', 'qemu:///system', 'domiflist', 'kmod-noble-68'],
    ['virsh', '-c', 'qemu:///system', 'domifaddr', 'kmod-noble-68', '--source', 'agent'],
    ['ip', '-brief', 'address'], ['ip', 'neigh'],
    ['tail', '-n', '35', '/var/log/libvirt/qemu/kmod-noble-68.log'],
): run(command)
