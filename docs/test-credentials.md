# Test credentials

iBrain test entry points select credentials from these environment variables:

| Variable | Use |
|---|---|
| `project-ak-api` | Default for experiments |
| `personal-ak-api` | Explicit personal selection |

Python commands accept `--credential project` or `--credential personal`. `PI_NODROP_API_CREDENTIAL=personal` selects the personal credential for Node and Python test entry points. The default is `project`.

The resolvers read the process environment, followed by the Windows user environment when running on Windows. A missing selected variable stops the test; Pi's saved authentication is not used as a fallback. Reports record the credential variable name, never its value.

WSL and VM test processes must receive the selected variable in their own environment. Linux environments support these names through process environment APIs or `env`; shell `export` syntax generally requires names without hyphens. Test launchers forward credentials through process memory or isolated temporary Pi configuration, without putting secrets in command arguments. The standard Pi authentication file remains unchanged.

Route checks default to a compact set. Expanded model sweeps and repeated trials are separate experiments. They retain request counts and reported token usage.
