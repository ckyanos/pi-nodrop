import assert from 'node:assert/strict';
import { resolve } from 'node:path';
import { discoverAndLoadExtensions } from '@earendil-works/pi-coding-agent';
import { auditPolicyGuideline } from '../src/tools.mjs';
import { defaultToolNames, policyToolGuideline } from '../src/policy-tools.mjs';

process.env.PI_NODROP_OUTPUT = resolve('build/extension-loader-metadata');
process.env.PI_NODROP_CONTROL_MODE ??= 'agent';
const named = process.env.PI_NODROP_CONTROL_MODE === 'agent-names';
const field = process.env.PI_NODROP_CONTROL_MODE === 'agent';
const selected = process.env.PI_NODROP_TOOLS?.split(',') ?? defaultToolNames;
const expectedNames = selected.flatMap(name => named ? [`${name}_raw`, `${name}_counts`] : [name]);
const result = await discoverAndLoadExtensions([resolve('src/extension.mjs')], process.cwd(),
  resolve('build/empty-agent-dir'));
assert.deepEqual(result.errors, []);
const extension = result.extensions.find(item => item.resolvedPath === resolve('src/extension.mjs')) ?? result.extensions[0];
assert(extension);
assert.equal(extension.tools.size, expectedNames.length);
const names = [...extension.tools.keys()].sort();
assert.deepEqual(names, [...expectedNames].sort());
for (const tool of extension.tools.values()) {
  if (field) assert(tool.definition.parameters.required.includes('audit_policy'));
  else assert.equal(tool.definition.parameters.properties.audit_policy, undefined);
}
const event = { systemPromptOptions: { promptGuidelines: ['existing guideline'] } };
for (let i = 0; i < 2; i++) {
  for (const handler of extension.handlers.get('before_agent_start') ?? []) await handler(event, {});
}
assert.deepEqual(event.systemPromptOptions.promptGuidelines,
  ['existing guideline', ...(named ? [policyToolGuideline] : field ? [auditPolicyGuideline] : [])]);
assert.equal(Boolean(extension.tools.get(named ? 'read_counts' : 'read').definition.parameters.properties.output_page),
  process.env.PI_NODROP_OUTPUT_MODE !== 'inline');
for (const handler of extension.handlers.get('session_shutdown') ?? []) await handler({}, {});
console.log(JSON.stringify({ loader: 'Pi discoverAndLoadExtensions', registeredTools: names, shutdown: 'passed' }));
