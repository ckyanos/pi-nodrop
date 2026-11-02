"""Resolve explicitly named iBrain test credentials without falling back to Pi auth."""
import os


def get_ibrain_credential(selection=None):
    selection = selection or os.environ.get('PI_NODROP_API_CREDENTIAL', 'project')
    if selection not in ('project', 'personal'):
        raise ValueError('PI_NODROP_API_CREDENTIAL must be project or personal')
    name = selection + '-ak-api'
    value = os.environ.get(name)
    if not value and os.name == 'nt':
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, 'Environment') as env:
                value = winreg.QueryValueEx(env, name)[0]
        except FileNotFoundError:
            pass
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError('Set ' + name + ' in the test environment; no fallback credential is used')
    return value, name
