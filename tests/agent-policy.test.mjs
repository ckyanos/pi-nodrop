import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { Agent, runToolCall } from '@earendil-works/pi-agent-core';
import { AssistantMessageEventStream, validateToolArguments } from '@earendil-works/pi-ai';
import { AuditExecutor } from '../src/client.mjs';
import { auditedToolDefinitions, toolDefinitions } from '../src/tools.mjs';
import { defaultToolNames } from '../src/policy-tools.mjs';

function directory() {
  const parent = process.env.PI_NODROP_TEST_WORKDIR ?? tmpdir();
  mkdirSync(parent, { recursive: true });
  return mkdtempSync(join(parent, 'agent-policy-'));
}
const backend = process.env.PI_NODROP_TEST_BACKEND ?? 'none';
function begins(cwd) {
  return readFileSync(join(cwd, 'audit/calls.jsonl'), 'utf8').trim().split('\n')
    .map(JSON.parse).filter(c => c.kind === 'begin');
}

test('Pi validates the policy in each tool schema and preserves edit argument preparation', () => {
  const cwd = directory();
  const tools = auditedToolDefinitions(cwd, { policyMode: 'agent', execute() {} });
  const examples = {
    bash: { command: 'pwd' }, read: { path: 'file.txt' },
    write: { path: 'file.txt', content: 'text' },
    edit: { path: 'file.txt', edits: [{ oldText: 'old', newText: 'new' }] },
    grep: { pattern: 'text' }, find: { pattern: '*.js' }, ls: { path: '.' },
  };
  for (const tool of tools) {
    assert(tool.parameters.required.includes('audit_policy'));
    assert.deepEqual(tool.parameters.properties.audit_policy.enum, ['raw', 'counts']);
    assert.equal(tool.parameters.properties.audit_policy.description, undefined);
    assert.equal(Object.keys(tool.parameters.properties)[0], 'audit_policy');
    const example = { ...examples[tool.name], audit_policy: 'counts' };
    assert.equal(tool.description, toolDefinitions(cwd).find(t => t.name === tool.name).description);
    assert.doesNotThrow(() => validateToolArguments(tool, { name: tool.name, arguments: example }));
    assert.equal(toolDefinitions(cwd).find(t => t.name === tool.name).parameters.properties.audit_policy, undefined);
  }
  const read = tools.find(t => t.name === 'read');
  assert.throws(() => validateToolArguments(read, { name: 'read', arguments: { path: 'a' } }), /audit_policy/);
  assert.throws(() => validateToolArguments(read, { name: 'read', arguments: { path: 'a', audit_policy: 'drop' } }), /audit_policy/);
  const edit = tools.find(t => t.name === 'edit');
  const prepared = edit.prepareArguments({ path: 'a', oldText: 'old', newText: 'new', audit_policy: 'counts' });
  const args = validateToolArguments(edit, { name: 'edit', arguments: prepared });
  assert.equal(args.audit_policy, 'counts');
  assert.deepEqual(args.edits, [{ oldText: 'old', newText: 'new' }]);
});

test('fixed-raw descriptions keep the original tool contract', () => {
  const cwd = directory();
  const original = toolDefinitions(cwd);
  const fixed = auditedToolDefinitions(cwd, { policyMode: 'fixed-raw', execute() {} });
  for (let i = 0; i < original.length; i++) {
    assert.equal(fixed[i].description, original[i].description);
    assert.equal(fixed[i].parameters.properties.audit_policy, undefined);
  }
});

test('Pi rejects missing or invalid policies without echoing long business arguments', async () => {
  const cwd = directory();
  let executions = 0;
  const tools = auditedToolDefinitions(cwd, { policyMode: 'agent', execute() { executions++; } });
  const content = 'long-business-content-'.repeat(8192);
  for (const policy of [undefined, 'drop', null, 1]) {
    const input = { path: 'unexecuted.txt', content };
    if (policy !== undefined) input.audit_policy = policy;
    const outcome = await runToolCall({ id: 'invalid', name: 'write', arguments: input }, {
      tools, assistantMessage: {}, context: { tools, messages: [], systemPrompt: '' },
    });
    assert.equal(outcome.isError, true);
    const text = outcome.result.content[0].text;
    assert.match(text, /audit_policy.*raw.*counts/);
    assert(text.length < 128);
    assert(!text.includes('long-business-content'));
    assert.equal(input.content, content);
  }
  const businessError = await runToolCall({ id: 'business-invalid', name: 'write',
    arguments: { path: 'unexecuted.txt', audit_policy: 'raw' } }, {
    tools, assistantMessage: {}, context: { tools, messages: [], systemPrompt: '' },
  });
  assert.equal(businessError.isError, true);
  assert.match(businessError.result.content[0].text, /Validation failed.*write/);
  assert.match(businessError.result.content[0].text, /content/);
  assert.equal(executions, 0);
});

test('the real Pi loop passes different policies for the same tool in the original call JSON', async () => {
  const cwd = directory();
  const executor = new AuditExecutor({ cwd, output: join(cwd, 'audit'), workers: 2,
    backend, policyMode: 'agent', policies: { read: 'counts', write: 'counts' } });
  const groups = [
    [{ id: 'agent-write', name: 'write', arguments: { path: 'source.txt', content: 'payload', audit_policy: 'raw' } }],
    [{ id: 'agent-read-raw', name: 'read', arguments: { path: 'source.txt', audit_policy: 'raw' } },
     { id: 'agent-read-counts', name: 'read', arguments: { path: 'source.txt', audit_policy: 'counts' } }],
  ];
  let index = 0;
  const model = { id: 'scripted-policy-test', name: 'Scripted policy test', api: 'openai-completions',
    provider: 'local-test', baseUrl: '', reasoning: false, input: ['text'],
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 8192, maxTokens: 1024 };
  const tools = auditedToolDefinitions(cwd, executor).filter(t => defaultToolNames.includes(t.name));
  assert.equal(tools.length, 4);
  assert.deepEqual(tools.map(t => t.name).sort(), [...defaultToolNames].sort());
  const agent = new Agent({ initialState: { model, tools },
    streamFn: () => {
      const calls = groups[index++];
      const message = { role: 'assistant', api: model.api, provider: model.provider, model: model.id,
        content: calls ? calls.map(c => ({ type: 'toolCall', ...c })) : [{ type: 'text', text: 'done' }],
        stopReason: calls ? 'toolUse' : 'stop', timestamp: Date.now(),
        usage: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0,
          cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } } };
      const stream = new AssistantMessageEventStream();
      queueMicrotask(() => { stream.push({ type: 'start', partial: message });
        stream.push({ type: 'done', reason: message.stopReason, message }); });
      return stream;
    } });
  try {
    await executor.ready;
    await agent.prompt('Run the call-level policy protocol checks.');
    const results = agent.state.messages.filter(m => m.role === 'toolResult');
    assert.equal(results.length, 3);
    assert(results.every(m => !m.isError));
    assert.equal(readFileSync(join(cwd, 'source.txt'), 'utf8'), 'payload');
    const records = begins(cwd);
    assert.deepEqual(records.map(c => [c.tool_call_id, c.input.audit_policy, c.policy_id, c.policy_source]),
      [['agent-write', 'raw', 1, 'agent'], ['agent-read-raw', 'raw', 1, 'agent'], ['agent-read-counts', 'counts', 2, 'agent']]);
    for (const result of results.filter(r => r.toolName === 'read')) assert.match(result.content[0].text, /payload/);
  } finally { await executor.close(); }
});

test('invalid agent choices do not execute, and fixed-raw remains an explicit override', async () => {
  const cwd = directory();
  writeFileSync(join(cwd, 'source.txt'), 'payload');
  const executor = new AuditExecutor({ cwd, output: join(cwd, 'audit'), backend, workers: 1, policyMode: 'agent' });
  try {
    await executor.ready;
    await assert.rejects(executor.execute('read', 'retry-id', { path: 'source.txt' }), /audit_policy/);
    await assert.rejects(executor.execute('read', 'retry-id', { path: 'source.txt', audit_policy: 'drop' }), /audit_policy/);
    await executor.execute('read', 'retry-id', { path: 'source.txt', audit_policy: 'counts' });
    assert.equal(begins(cwd).length, 1);
  } finally { await executor.close(); }
  const fixed = new AuditExecutor({ cwd, output: join(cwd, 'fixed-audit'), backend, workers: 1, policyMode: 'fixed-raw' });
  try {
    await fixed.ready;
    await fixed.execute('read', 'fixed-id', { path: 'source.txt', audit_policy: 'counts' });
    const record = JSON.parse(readFileSync(join(cwd, 'fixed-audit/calls.jsonl'), 'utf8').split('\n')[0]);
    assert.equal(record.policy_id, 1);
    assert.equal(record.policy_source, 'fixed-raw');
    assert.equal(record.input.audit_policy, 'counts');
  } finally { await fixed.close(); }
});
