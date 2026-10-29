/* Real Pi Agent loop + real built-in tools; only the model stream is scripted.
 * No credentials or remote LLM calls are needed for deterministic attribution. */
import assert from 'node:assert/strict';
import { Agent } from '@earendil-works/pi-agent-core';
import { AssistantMessageEventStream } from '@earendil-works/pi-ai';
import { mkdirSync, writeFileSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { AuditExecutor } from '../src/client.mjs';
import { toolDefinitions } from '../src/tools.mjs';

const root = resolve('results');
const cwd = resolve(root, 'workload');
mkdirSync(cwd, { recursive: true });
writeFileSync(resolve(cwd, 'input.txt'), 'original\n');
const executor = new AuditExecutor({ cwd, output: resolve(root, 'pi'), workers: 2, policies: { ls: 'counts' },
  backend: process.env.PI_NODROP_TEST_BACKEND ?? 'nodrop' });
await executor.ready;
const turns = [
  [{ id: 'pi-write-A', name: 'write', arguments: { path: resolve(cwd, 'A.txt'), content: 'alpha\n' } },
   { id: 'pi-write-B', name: 'write', arguments: { path: resolve(cwd, 'B.txt'), content: 'beta\n' } }],
  [{ id: 'pi-read-A', name: 'read', arguments: { path: resolve(cwd, 'A.txt') } },
   { id: 'pi-edit-B', name: 'edit', arguments: { path: resolve(cwd, 'B.txt'), oldText: 'beta', newText: 'gamma' } }],
  [{ id: 'pi-shell-child', name: 'bash', arguments: { command: `cat '${cwd}/input.txt' > '${cwd}/shell-child.txt'` } },
   { id: 'pi-count-ls', name: 'ls', arguments: { path: cwd } }],
  [{ id: 'pi-error', name: 'read', arguments: { path: resolve(cwd, 'does-not-exist.txt') } }],
  [{ id: 'pi-after-error', name: 'write', arguments: { path: resolve(cwd, 'after-error.txt'), content: 'recovered' } }],
];
let turn = 0;
const model = { id: 'scripted-test', name: 'Scripted test', api: 'openai-completions', provider: 'local-test',
  baseUrl: '', reasoning: false, input: ['text'], cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
  contextWindow: 8192, maxTokens: 1024 };
const agent = new Agent({ initialState: { model, tools: toolDefinitions(cwd).map(t => ({ ...t,
  execute: (id, params, signal, onUpdate) => executor.execute(t.name, id, params, { signal, onUpdate }),
})) }, streamFn: () => {
  const calls = turns[turn++];
  const message = { role: 'assistant', api: model.api, provider: model.provider, model: model.id,
    content: calls ? calls.map(c => ({ type: 'toolCall', ...c })) : [{ type: 'text', text: 'done' }],
    stopReason: calls ? 'toolUse' : 'stop', timestamp: Date.now(),
    usage: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0,
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } } };
  const stream = new AssistantMessageEventStream();
  queueMicrotask(() => {
    stream.push({ type: 'start', partial: message });
    stream.push({ type: 'done', reason: message.stopReason, message });
  });
  return stream;
} });
const events = [];
agent.subscribe(event => { events.push(event); });
try {
  await agent.prompt('Run the deterministic pi-nodrop prototype checks.');
  assert.equal(readFileSync(resolve(cwd, 'A.txt'), 'utf8'), 'alpha\n');
  assert.equal(readFileSync(resolve(cwd, 'B.txt'), 'utf8'), 'gamma\n');
  assert.equal(readFileSync(resolve(cwd, 'shell-child.txt'), 'utf8'), 'original\n');
  assert.equal(readFileSync(resolve(cwd, 'after-error.txt'), 'utf8'), 'recovered');
  const results = agent.state.messages.filter(m => m.role === 'toolResult');
  assert.equal(results.length, 8);
  assert.equal(results.filter(m => m.isError).length, 1);
  writeFileSync(resolve(root, 'pi-agent-events.json'), JSON.stringify(events, null, 2));
  writeFileSync(resolve(root, 'pi-transcript.json'), JSON.stringify(agent.state.messages, null, 2));
  console.log(JSON.stringify({ toolCalls: results.length, expectedErrors: 1, model: 'scripted', pi: '1.4.0' }));
} finally { await executor.close(); }
// The parent Agent process has no audit context; this path must not appear.
writeFileSync(resolve(cwd, 'outside-tool.txt'), 'outside');
