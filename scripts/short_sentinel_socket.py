#!/usr/bin/python3
"""Launch the unchanged AgentSentinel ELF through a short Unix-socket alias."""
import os
from pathlib import Path
import sys
import tempfile


def main():
    binary = Path(__file__).with_name('agent-sentinel.native')
    args = sys.argv[1:]
    for flag in ('-mount-path', '--mount-path'):
        if flag not in args:
            continue
        index = args.index(flag) + 1
        target = Path(args[index]).resolve(strict=True)
        if len(str(target / 'computer-monitor.sock').encode()) >= 104:
            alias = Path(tempfile.mkdtemp(prefix='pi-sentinel-')) / 'shared'
            alias.symlink_to(target, target_is_directory=True)
            args[index] = str(alias)
        break
    os.execv(str(binary), [str(binary), *args])


if __name__ == '__main__':
    main()
