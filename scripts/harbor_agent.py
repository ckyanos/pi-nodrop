"""NoDrop extension setup for Harbor's unmodified native Pi execution path."""
from pathlib import Path
import json
import shlex
from typing import Literal

from harbor.agents.installed.pi import Pi, PiOptions


class NoDropPiOptions(PiOptions):
    audit_mode: Literal['fixed-raw', 'agent', 'agent-names'] = 'agent'


class NoDropPi(Pi):
    options_model = NoDropPiOptions

    @staticmethod
    def name() -> str:
        return 'pi-nodrop'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._extra_env.update({
            'PI_NODROP_OUTPUT': str(self.environment_logs_dir / 'nodrop'),
            'PI_NODROP_OUTPUT_MODE': 'inline',
            'PI_NODROP_CONTROL_MODE': self.options.audit_mode,
            'PI_NODROP_TOOLS': 'read,bash,edit,write',
            'PI_NODROP_IOCTL_PATH': '/dev/pi-nodrop',
        })

    async def install(self, environment):
        await super().install(environment)
        root = Path(__file__).resolve().parents[1]
        await environment.upload_file(root / 'build/harbor-audit-payload.tar.gz', '/tmp/pi-nodrop-payload.tar.gz')
        quoted = shlex.quote(str(root))
        await self.exec_as_agent(environment, command=(
            f'. ~/.nvm/nvm.sh; mkdir -p {quoted} && '
            f'tar -xzf /tmp/pi-nodrop-payload.tar.gz -C {quoted} && '
            f'ln -s "$(npm root -g)" {quoted}/node_modules && '
            f'node -e {shlex.quote("require(" + json.dumps(str(root / "build/context.node")) + ")")}'
        ))

    def build_cli_flags(self):
        flags = super().build_cli_flags()
        extension = Path(__file__).resolve().parents[1] / 'src/extension.mjs'
        return f'{flags} --extension {shlex.quote(str(extension))}'.strip()
