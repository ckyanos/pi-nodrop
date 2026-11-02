export const businessToolNames = ['bash', 'read', 'write', 'edit', 'grep', 'find', 'ls'];
export const defaultToolNames = ['read', 'bash', 'edit', 'write'];
export const policyToolNames = businessToolNames.flatMap(name => ['raw', 'counts'].map(policy => `${name}_${policy}`));

export function decodePolicyToolName(name) {
  if (!policyToolNames.includes(name)) throw new Error('Use a tool name ending in _raw or _counts');
  const boundary = name.lastIndexOf('_');
  return { toolName: name.slice(0, boundary), policy: name.slice(boundary + 1) };
}

export const policyToolGuideline = 'Choose the _raw or _counts variant of a tool on every call: raw keeps syscall arguments and order; counts keeps event-type totals and time bounds. The tool-name suffix selects the audit policy.';
