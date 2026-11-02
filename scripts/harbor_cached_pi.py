"""Reuse a byte-identified official Pi installation in independent task containers."""
import hashlib
import json
from pathlib import Path
import shlex

from harbor.agents.installed.pi import Pi
from scripts.harbor_agent import NoDropPi
from scripts.harbor_external_audit import ExternalAuditPi


class CachedPi(Pi):
    async def install(self, environment):
        await self.ensure_system_dependencies(environment, ('curl',))
        result = await self.exec_as_agent(environment,
            command='tar -xf /tmp/pi-install-cache.tar -C /root && . ~/.nvm/nvm.sh && node --version && pi --version')
        if '1.4.0' not in result.stdout:
            raise RuntimeError('Cached Pi version mismatch')
        metadata = json.loads(Path(self._get_env('PI_INSTALL_CACHE_METADATA')).read_text())
        for file_key, hash_key in [('node_relative', 'node_sha256'), ('pi_cli_relative', 'pi_cli_sha256')]:
            path = '/root/' + metadata[file_key]
            result = await self.exec_as_agent(environment, command='sha256sum ' + shlex.quote(path))
            if result.stdout.split()[0] != metadata[hash_key]:
                raise RuntimeError('Cached installation binary hash mismatch')


class CachedNoDropPi(NoDropPi, CachedPi):
    pass


class CachedExternalAuditPi(ExternalAuditPi, CachedPi):
    pass
