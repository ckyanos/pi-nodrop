import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, readFileSync, writeFileSync, unlinkSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { Agent } from '@earendil-works/pi-agent-core';
import { AssistantMessageEventStream } from '@earendil-works/pi-ai';
import { OutputStore, readOutputPage } from '../src/output-store.mjs';
import { AuditExecutor } from '../src/client.mjs';
import { auditedToolDefinitions, outputToolDefinitions } from '../src/tools.mjs';

function directory() {
  const root = process.env.PI_NODROP_TEST_WORKDIR ?? tmpdir();
  mkdirSync(root, { recursive: true });
  return mkdtempSync(join(root, 'output-store-'));
}

test('baseline output references use direct tools and share the fixed-raw read schema', async () => {
  const cwd = directory(), text = 'direct-output-'.repeat(1500);
  writeFileSync(join(cwd, 'source.txt'), text);
  const store = new OutputStore(join(cwd, 'outputs'));
  const tools = outputToolDefinitions(cwd, store);
  const fixed = auditedToolDefinitions(cwd, { policyMode: 'fixed-raw', outputMode: 'reference' });
  assert.deepEqual(tools.map(t => t.parameters), fixed.map(t => t.parameters));
  const read = tools.find(t => t.name === 'read');
  const shown = await read.execute('direct-read', { path: 'source.txt' });
  const index = shown.details.outputIndex;
  assert.equal(index.call_ref, null);
  assert.match(index.output_ref, /^[0-9a-f]{16}$/);
  assert.equal(index.tool_call_id, 'direct-read');
  const page = await read.execute('direct-page', { path: index.path, output_page: 2 });
  assert.equal(page.details.outputPage.page, 2);
  assert.equal(readFileSync(join(index.path, '../output.txt'), 'utf8'), text);
});

test('large Unicode output is archived and every page reconstructs the original text', async () => {
  const cwd = directory(), store = new OutputStore(join(cwd, 'outputs'));
  const text = '0123456789中文😀'.repeat(5000);
  const original = { content: [{ type: 'text', text }, { type: 'image', mimeType: 'image/png', data: 'image-data' }],
    isError: true, structuredContent: { output: text, exit_code: 7 } };
  const result = await store.present(original, { toolCallId: 'call/unicode', callRef: '1111111111111111', toolName: 'bash' });
  assert(Buffer.byteLength(result.content[0].text) < 4096);
  assert.equal(result.isError, true);
  assert.equal(result.content[1].data, 'image-data');
  assert.equal(result.structuredContent, original.structuredContent);
  const index = result.details.outputIndex;
  assert.deepEqual(JSON.parse(readFileSync(join(cwd, 'outputs/1111111111111111/result.json'))), original);
  let reconstructed = '', previousEnd = 0;
  for (let page = 1; page <= index.pages; page++) {
    const viewed = await readOutputPage({ path: index.path, output_page: page }, { root: store.root, cwd });
    assert(Buffer.byteLength(viewed.content[0].text) < 4096);
    assert.equal(viewed.details.outputPage.start, previousEnd);
    previousEnd = viewed.details.outputPage.end;
    reconstructed += viewed.details.outputPage.text;
  }
  assert.equal(reconstructed, text);
  assert.equal(previousEnd, Buffer.byteLength(text));
  await assert.rejects(readOutputPage({ path: index.path, output_page: index.pages + 1 }, { root: store.root, cwd }), /pages/);
  const small = { content: [{ type: 'text', text: 'ok' }] };
  assert.equal(await store.present(small, { callRef: '2222222222222222' }), small);
});

test('Pi full output is retained beyond its display truncation and lookup stays in the store', async () => {
  const cwd = directory(), store = new OutputStore(join(cwd, 'outputs'));
  const source = join(cwd, 'pi-full-output.txt'), full = 'full-output-'.repeat(10000);
  writeFileSync(source, full);
  const original = { content: [{ type: 'text', text: 'display-only-'.repeat(500) }],
    details: { fullOutputPath: source, truncation: { truncated: true } } };
  const shown = await store.present(original, { toolName: 'bash', toolCallId: 'full', callRef: '3333333333333333' });
  const index = shown.details.outputIndex;
  assert.equal(index.source, 'pi-full-output');
  assert.equal(index.bytes, Buffer.byteLength(full));
  assert.equal(readFileSync(join(cwd, 'outputs/3333333333333333/output.txt'), 'utf8'), full);
  unlinkSync(source);
  const last = await readOutputPage({ path: index.path, output_page: index.pages }, { root: store.root, cwd });
  assert(last.details.outputPage.text.endsWith('full-output-'));
  const outside = join(cwd, 'index.json'); writeFileSync(outside, '{}');
  await assert.rejects(readOutputPage({ path: outside, output_page: 1 }, { root: store.root, cwd }), /not a stored/);
  await assert.rejects(readOutputPage({ path: index.path, output_page: 1, limit: 1 }, { root: store.root, cwd }), /without offset/);
});

test('the Pi loop receives a reference then fetches an audited page with the original read tool', async () => {
  const cwd = directory(), text = 'business-output-'.repeat(1500);
  writeFileSync(join(cwd, 'source.txt'), text);
  const executor = new AuditExecutor({ cwd, output: join(cwd, 'audit'), workers: 1,
    backend: process.env.PI_NODROP_TEST_BACKEND ?? 'none', policyMode: 'agent', outputMode: 'reference' });
  const model = { id: 'scripted-output-test', name: 'Scripted output test', api: 'openai-completions',
    provider: 'local-test', baseUrl: '', reasoning: false, input: ['text'],
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 8192, maxTokens: 1024 };
  let turn = 0, indexPath;
  const agent = new Agent({ initialState: { model, tools: auditedToolDefinitions(cwd, executor) },
    streamFn: (_model, context) => {
      for (const message of context.messages.filter(m => m.role === 'toolResult')) {
        assert(Buffer.byteLength(message.content[0].text) < 4096);
        assert(!message.content[0].text.includes(text));
      }
      const previous = context.messages.filter(m => m.role === 'toolResult').at(-1);
      if (previous?.details?.outputIndex) indexPath = previous.details.outputIndex.path;
      const call = turn === 0 ? { id: 'output-read', name: 'read',
        arguments: { path: 'source.txt', audit_policy: 'raw' } }
        : turn === 1 ? { id: 'output-page', name: 'read',
          arguments: { path: indexPath, output_page: 1, audit_policy: 'counts' } } : null;
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
    await agent.prompt('Read the stored output page.');
    const results = agent.state.messages.filter(m => m.role === 'toolResult');
    assert.equal(results.length, 2); assert(results.every(r => !r.isError));
    assert.match(results[0].content[0].text, /Output index:/);
    assert(results[1].details.outputPage.text.startsWith('business-output-'));
    assert.equal(readFileSync(join(indexPath, '../output.txt'), 'utf8'), text);
    const calls = readFileSync(join(cwd, 'audit/calls.jsonl'), 'utf8').trim().split('\n').map(JSON.parse);
    assert.deepEqual(calls.filter(c => c.kind === 'begin').map(c => [c.tool_call_id, c.policy_id]),
      [['output-read', 1], ['output-page', 2]]);
  } finally { await executor.close(); }
});
