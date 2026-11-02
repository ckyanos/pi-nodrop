import { execFileSync } from 'node:child_process';

export function getIbrainCredential(selection = process.env.PI_NODROP_API_CREDENTIAL ?? 'project') {
  if (!['project', 'personal'].includes(selection))
    throw new Error('PI_NODROP_API_CREDENTIAL must be project or personal');
  const name = `${selection}-ak-api`;
  let key = process.env[name];
  if (!key && process.env.PI_NODROP_TEST_API_CREDENTIAL_NAME === name)
    key = process.env.PI_NODROP_TEST_API_KEY;
  if (!key && process.platform === 'win32') {
    key = execFileSync('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command',
      `[Console]::Write([Environment]::GetEnvironmentVariable('${name}','User'))`],
      { encoding: 'utf8', windowsHide: true, stdio: ['ignore', 'pipe', 'ignore'] });
  }
  if (!key?.trim()) throw new Error(`Set ${name} in the test environment; no fallback credential is used`);
  return { key, name };
}
