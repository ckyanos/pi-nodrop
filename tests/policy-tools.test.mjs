import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { Agent, runToolCall } from '@earendil-works/pi-agent-core';
import { AssistantMessageEventStream, validateToolArguments } from '@earendil-works/pi-ai';
import { createAgentSession, DefaultResourceLoader, ModelRuntime, SessionManager, SettingsManager } from '@earendil-works/pi-coding-agent';
import { AuditExecutor } from '../src/client.mjs';
import { auditedToolDefinitions, toolDefinitions } from '../src/tools.mjs';
import { decodePolicyToolName, policyToolNames } from '../src/policy-tools.mjs';

function directory() {
  const parent = process.env.PI_NODROP_TEST_WORKDIR ?? tmpdir();
  mkdirSync(parent, { recursive: true });
  return mkdtempSync(join(parent, 'policy-tools-'));
}

test('policy names expose fourteen entries with the original business schemas and edit preparation', async () => {
  const cwd = directory(), tools = auditedToolDefinitions(cwd, { policyMode: 'agent-names', outputMode: 'reference' });
  assert.deepEqual(tools.map(t => t.name), policyToolNames);
  for (const tool of tools) {
    const { toolName, policy } = decodePolicyToolName(tool.name);
    assert(['raw', 'counts'].includes(policy));
    assert.equal(tool.parameters.properties.audit_policy, undefined);
    if (toolName === 'read') assert(tool.parameters.properties.output_page);
    else assert.deepEqual(tool.parameters, toolDefinitions(cwd).find(t => t.name === toolName).parameters);
    assert.throws(() => tool.prepareArguments({ audit_policy: 'raw' }), /tool name/);
  }
  const edit = tools.find(t => t.name === 'edit_counts');
  const prepared = edit.prepareArguments({ path: 'file', oldText: 'old', newText: 'new' });
  assert.deepEqual(validateToolArguments(edit, { name: edit.name, arguments: prepared }).edits,
    [{ oldText: 'old', newText: 'new' }]);
  const unknown = await runToolCall({ id: 'unknown', name: 'read', arguments: { path: 'file' } }, {
    tools, assistantMessage: {}, context: { tools, messages: [], systemPrompt: '' },
  });
  assert.equal(unknown.isError, true);
  assert.match(unknown.result.content[0].text, /not found/);
});

test('the Pi SDK activates only the fourteen policy entries', async () => {
  const cwd = directory(), agentDir = join(cwd, 'agent'); mkdirSync(agentDir);
  const model = { id: 'policy-names-test', name: 'Policy names test', api: 'openai-completions',
    reasoning: false, input: ['text'], contextWindow: 8192, maxTokens: 1024,
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 } };
  writeFileSync(join(agentDir, 'models.json'), JSON.stringify({ providers: {
    'local-test': { api: model.api, baseUrl: 'http://127.0.0.1:1/v1', models: [model] },
  } }));
  const runtime = await ModelRuntime.create({ modelsPath: join(agentDir, 'models.json'),
    authPath: join(agentDir, 'auth.json'), refreshOnCreate: false });
  const settings = SettingsManager.inMemory({});
  const loader = new DefaultResourceLoader({ cwd, agentDir, settingsManager: settings,
    noExtensions: true, noSkills: true, noPromptTemplates: true, noThemes: true, noContextFiles: true });
  await loader.reload();
  const { session } = await createAgentSession({ cwd, agentDir, resourceLoader: loader,
    modelRuntime: runtime, model: runtime.getModel('local-test', model.id), settingsManager: settings,
    sessionManager: SessionManager.inMemory(), tools: policyToolNames,
    customTools: auditedToolDefinitions(cwd, { policyMode: 'agent-names', outputMode: 'reference' }),
  });
  try { assert.deepEqual(session.getActiveToolNames().sort(), [...policyToolNames].sort()); }
  finally { session.dispose(); }
});

test('the Pi loop maps explicit name choices to policies, preserves identity and retrieves a stored page', async () => {
  const cwd = directory(), text = 'named-policy-output-'.repeat(1500);
  const executor = new AuditExecutor({ cwd, output: join(cwd, 'audit'), workers: 2,
    backend: process.env.PI_NODROP_TEST_BACKEND ?? 'none', policyMode: 'agent-names', outputMode: 'reference' });
  const tools = auditedToolDefinitions(cwd, executor);
  const model = { id: 'scripted-name-test', name: 'Scripted name test', api: 'openai-completions',
    provider: 'local-test', baseUrl: '', reasoning: false, input: ['text'],
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 8192, maxTokens: 1024 };
  let turn = 0, index;
  const agent = new Agent({ initialState: { model, tools }, streamFn: (_model, context) => {
    const previous = context.messages.filter(m => m.role === 'toolResult').at(-1);
    if (previous?.details?.outputIndex) {
      index = previous.details.outputIndex.path;
      assert.match(previous.content[0].text, /Use read_raw or read_counts/);
    }
    const call = turn === 0 ? { id: 'named-write', name: 'write_raw', arguments: { path: 'source', content: text } }
      : turn === 1 ? { id: 'named-read', name: 'read_raw', arguments: { path: 'source' } }
        : turn === 2 ? { id: 'named-page', name: 'read_counts', arguments: { path: index, output_page: 1 } } : null;
    turn++;
    const message = { role: 'assistant', api: model.api, provider: model.provider, model: model.id,
      content: call ? [{ type: 'toolCall', ...call }] : [{ type: 'text', text: 'done' }],
      stopReason: call ? 'toolUse' : 'stop', timestamp: Date.now(),
      usage: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0,
        cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } } };
    const stream = new AssistantMessageEventStream();
    queueMicrotask(() => { stream.push({ type: 'start', partial: message });
      stream.push({ type: 'done', reason: message.stopReason, message }); });
    return stream;
  } });
  try {
    await executor.ready;
    for (const name of ['read', 'read_default', 'exec_raw'])
      await assert.rejects(executor.execute(name, 'named-write', {}), /tool name/);
    await assert.rejects(executor.execute('write_raw', 'named-write', { audit_policy: 'counts' }), /tool name/);
    await agent.prompt('Write, read and page the stored output.');
    const results = agent.state.messages.filter(m => m.role === 'toolResult');
    assert.equal(results.length, 3); assert(results.every(m => !m.isError));
    assert.equal(readFileSync(join(cwd, 'source'), 'utf8'), text);
    assert(results[2].details.outputPage.text.startsWith('named-policy-output-'));
    const calls = readFileSync(join(cwd, 'audit/calls.jsonl'), 'utf8').trim().split('\n').map(JSON.parse);
    const starts = calls.filter(c => c.kind === 'begin');
    assert.deepEqual(starts.map(c => [c.tool_call_id, c.model_tool_name, c.tool_name, c.policy_id, c.policy_source]),
      [['named-write', 'write_raw', 'write', 1, 'agent-names'],
       ['named-read', 'read_raw', 'read', 1, 'agent-names'],
       ['named-page', 'read_counts', 'read', 2, 'agent-names']]);
    assert(starts.every(c => !Object.hasOwn(c.input, 'audit_policy')));
    assert.equal(new Set(starts.map(c => c.call_ref)).size, 3);
  } finally { await executor.close(); }
});
