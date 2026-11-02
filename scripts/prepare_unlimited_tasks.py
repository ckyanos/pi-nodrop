"""Prepare isolated Harbor tasks with no agent execution deadline."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import tomllib

import toml


def prepare_unlimited_tasks(source: Path, destination: Path, names):
    source = source.resolve()
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    manifest = {}
    for name in dict.fromkeys(names):
        original = source / name
        target = destination / name
        assert original.resolve().parent == source and target.parent == destination
        assert target != original and not target.is_relative_to(original)
        before = tomllib.loads((original / 'task.toml').read_text(encoding='utf-8'))
        after = deepcopy(before)
        previous = after.get('agent', {}).pop('timeout_sec', None)
        assert not after.get('steps'), 'This runner supports single-step tasks'
        text = toml.dumps(after)
        assert tomllib.loads(text) == after
        if target.exists():
            assert tomllib.loads((target / 'task.toml').read_text(encoding='utf-8')) == after
        else:
            shutil.copytree(original, target)
            (target / 'task.toml').write_text(text, encoding='utf-8')
        files = {}
        for path in original.rglob('*'):
            if not path.is_file() or path.name == 'task.toml' and path.parent == original:
                continue
            relative = path.relative_to(original)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            assert hashlib.sha256((target / relative).read_bytes()).hexdigest() == digest
            files[relative.as_posix()] = digest
        manifest[name] = {
            'original_agent_timeout_sec': previous,
            'agent_timeout_sec': None,
            'original_config_sha256': hashlib.sha256((original / 'task.toml').read_bytes()).hexdigest(),
            'prepared_config_sha256': hashlib.sha256((target / 'task.toml').read_bytes()).hexdigest(),
            'unchanged_files_sha256': files,
        }
    return destination, manifest
