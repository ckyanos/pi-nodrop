import { resolve } from 'node:path';
import { AuditExecutor } from './client.mjs';
import { auditedToolDefinitions, auditPolicyGuideline } from './tools.mjs';
import { businessToolNames, defaultToolNames, policyToolGuideline } from './policy-tools.mjs';

export default function piNodrop(pi) {
  if (process.platform !== 'linux') throw new Error('pi-nodrop requires Linux; run Pi in the test VM');
  const cwd = process.cwd();
  const selected = process.env.PI_NODROP_TOOLS?.split(',') ?? defaultToolNames;
  if (!selected.length || new Set(selected).size !== selected.length ||
      selected.some(name => !businessToolNames.includes(name))) throw new Error('Unknown or duplicate PI_NODROP_TOOLS entry');
  const executor = new AuditExecutor({ cwd,
    output: process.env.PI_NODROP_OUTPUT ?? resolve(cwd, '.pi/nodrop'),
    workers: Number(process.env.PI_NODROP_WORKERS ?? 2),
    policies: JSON.parse(process.env.PI_NODROP_POLICIES ?? '{}'),
    policyMode: process.env.PI_NODROP_CONTROL_MODE ?? 'agent',
    outputMode: process.env.PI_NODROP_OUTPUT_MODE ?? 'reference',
    inlineBytes: Number(process.env.PI_NODROP_INLINE_BYTES ?? 4096),
  });
  const definitions = auditedToolDefinitions(cwd, executor);
  const names = selected.flatMap(name => executor.policyMode === 'agent-names'
    ? [`${name}_raw`, `${name}_counts`] : [name]);
  for (const name of names) pi.registerTool(definitions.find(definition => definition.name === name));
  pi.on('session_start', () => pi.setActiveTools(names));
  const guideline = executor.policyMode === 'agent' ? auditPolicyGuideline
    : executor.policyMode === 'agent-names' ? policyToolGuideline : null;
  if (guideline) pi.on('before_agent_start', event => {
    const guidelines = event.systemPromptOptions.promptGuidelines;
    if (!guidelines.includes(guideline)) guidelines.push(guideline);
  });
  pi.on('session_shutdown', async () => { await executor.close(); });
}
