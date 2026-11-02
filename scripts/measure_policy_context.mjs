import assert from 'node:assert/strict';
import { readdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { runToolCall } from '@earendil-works/pi-agent-core';
import { auditedToolDefinitions, auditPolicyGuideline, toolDefinitions } from '../src/tools.mjs';

const [results, output] = process.argv.slice(2);
if (!results || !output) throw new Error('Usage: node scripts/measure_policy_context.mjs RESULTS OUTPUT');
const read = path => JSON.parse(readFileSync(path, 'utf8'));
const bytes = value => Buffer.byteLength(value);
const schemaBytes = tools => bytes(JSON.stringify(tools.map(({ name, parameters }) => ({ name, parameters }))));
const original = toolDefinitions(process.cwd());
let executions = 0;
const tools = auditedToolDefinitions(process.cwd(), {
  policyMode: 'agent', execute() { executions++; throw new Error('Unexpected tool execution'); },
});
const cases = [];
const previousSizes = new Set();
for (const task of readdirSync(results, { withFileTypes: true }).filter(e => e.isDirectory())) {
  const directory = join(results, task.name);
  const messages = read(join(directory, 'transcript.json'));
  const proposed = new Map(messages.filter(m => m.role === 'assistant')
    .flatMap(m => m.content.filter(c => c.type === 'toolCall')).map(c => [c.id, c]));
  const declarations = read(join(directory, 'request-1.json')).tools.map(t => t.function);
  previousSizes.add(schemaBytes(declarations));
  for (const result of messages.filter(m => m.role === 'toolResult' && m.isError)) {
    const call = proposed.get(result.toolCallId);
    const oldText = result.content.filter(c => c.type === 'text').map(c => c.text).join('\n');
    if (!call || call.arguments.audit_policy !== undefined || !oldText.includes('audit_policy')) continue;
    const updated = await runToolCall(call, { tools, assistantMessage: {},
      context: { tools, messages: [], systemPrompt: '' } });
    assert(updated.isError);
    const text = updated.result.content[0].text;
    assert(text.length < 128 && !text.includes('Received arguments:'));
    cases.push({ task: task.name, tool: call.name, previous_error_bytes: bytes(oldText),
      optimized_error_bytes: bytes(text) });
  }
}
assert.equal(previousSizes.size, 1);
assert.equal(executions, 0);
const total = key => cases.reduce((sum, c) => sum + c[key], 0);
const base = schemaBytes(original);
const report = { scope: 'UTF-8 byte measurements; saved invalid calls replayed through Pi validation',
  model_requests: 0, executed_business_calls: executions,
  schemas: { original_tool_bytes: base, previous_tool_bytes: [...previousSizes][0],
    optimized_tool_bytes: schemaBytes(tools), previous_added_tool_bytes: [...previousSizes][0] - base,
    optimized_added_tool_bytes: schemaBytes(tools) - base, shared_guideline_bytes: bytes(auditPolicyGuideline),
    shared_guideline: auditPolicyGuideline },
  cases, totals: { rejected_calls: cases.length, previous_error_bytes: total('previous_error_bytes'),
    optimized_error_bytes: total('optimized_error_bytes') } };
writeFileSync(output, JSON.stringify(report, null, 2) + '\n');
console.log(JSON.stringify({ schemas: report.schemas, totals: report.totals }));
