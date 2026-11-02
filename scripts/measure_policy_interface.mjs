import assert from 'node:assert/strict';
import { writeFileSync } from 'node:fs';
import { toolDefinitions, auditedToolDefinitions, auditPolicyGuideline } from '../src/tools.mjs';
import { defaultToolNames, policyToolGuideline } from '../src/policy-tools.mjs';
const selected = definitions => definitions.filter(d => defaultToolNames.includes(d.name.split('_')[0]));
const base = selected(toolDefinitions(process.cwd()));
const field = selected(auditedToolDefinitions(process.cwd(), { policyMode: 'agent', outputMode: 'inline' }));
const named = selected(auditedToolDefinitions(process.cwd(), { policyMode: 'agent-names', outputMode: 'inline' }));
assert.equal(base.length, 4); assert.equal(field.length, 4); assert.equal(named.length, 8);
assert.deepEqual(base.map(t => t.name), field.map(t => t.name));
for (let i = 0; i < field.length; i++) {
  assert.equal(field[i].description, base[i].description);
  assert(field[i].parameters.required.includes('audit_policy'));
}
const bytes = definitions => Buffer.byteLength(JSON.stringify(definitions.map(({ name, description, parameters }) => ({ name, description, parameters }))));
const report = { measurement: 'UTF-8 JSON bytes of tool name, description and parameter schema; not model token counts',
  model_requests: 0, tools: defaultToolNames,
  baseline: { tool_count: base.length, declaration_bytes: bytes(base) },
  field: { tool_count: field.length, declaration_bytes: bytes(field), guideline_bytes: Buffer.byteLength(auditPolicyGuideline) },
  historical_names: { tool_count: named.length, declaration_bytes: bytes(named), guideline_bytes: Buffer.byteLength(policyToolGuideline) } };
writeFileSync(process.argv[2] ?? 'build/field-interface-measurement.json', JSON.stringify(report, null, 2) + '\n');
console.log(JSON.stringify(report));
