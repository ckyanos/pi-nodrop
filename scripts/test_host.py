import shutil
import subprocess
import os
from lab_config import HOST_STAGE, ROOT

repo = ROOT
stage = HOST_STAGE
for name in ('src', 'tests'):
    shutil.copytree(repo / name, stage / name, dirs_exist_ok=True)
subprocess.run(['node', '--test', 'tests/protocol.test.mjs'], cwd=stage, check=True)
subprocess.run(['node', 'tests/integration.mjs'], cwd=stage, check=True,
               env=dict(os.environ, PI_NODROP_TEST_BACKEND='none'))
