import { createRequire } from 'node:module';
import { toolDefinitions } from './tools.mjs';
import { readOutputPage } from './output-store.mjs';

if (process.env.UV_THREADPOOL_SIZE !== '1') throw new Error('Audit worker requires UV_THREADPOOL_SIZE=1');
const require = createRequire(import.meta.url);
const backend = process.env.PI_NODROP_BACKEND === 'none'
  ? { setContext() {}, async flush() {} }
  : require('../build/context.node');
let active;
process.on('message', async (message) => {
  if (message.kind === 'abort') { active?.abort(); return; }
  if (message.kind === 'shutdown') { process.disconnect(); return; }
  if (message.kind !== 'execute') return;
  if (active) throw new Error('Concurrent calls in one audit worker are forbidden');
  active = new AbortController();
  let result, error;
  try {
    if (Object.hasOwn(message.params, 'audit_policy')) throw new Error('Audit policy must be separated from tool arguments');
    const tool = toolDefinitions(message.cwd).find(t => t.name === message.toolName);
    if (!tool) throw new Error(`Unknown tool: ${message.toolName}`);
    backend.setContext(BigInt(`0x${message.callRef}`), message.policyId);
    const session = message.session ?? {};
    const ctx = { cwd: message.cwd, model: session.model, thinkingLevel: session.thinkingLevel,
      sessionManager: { getSessionId: () => session.id ?? '', getSessionFile: () => session.file } };
    result = message.toolName === 'read' && Object.hasOwn(message.params, 'output_page')
      ? await readOutputPage(message.params, { root: message.outputRoot, cwd: message.cwd, signal: active.signal })
      : await tool.execute(message.toolCallId, message.params, active.signal,
        partial => process.send?.({ kind: 'update', partial }), ctx);
  } catch (cause) { error = cause instanceof Error ? cause.message : String(cause); }
  finally {
    try { await backend.flush(); }
    catch (cause) { error = `Audit flush failed: ${cause.message}; tool error: ${error ?? ''}`; }
    try { backend.setContext(0n, 0); }
    catch (cause) { error = `Audit context clear failed: ${cause.message}`; }
    active = undefined;
  }
  process.send?.({ kind: 'result', result, error, pid: process.pid });
});
process.send?.({ kind: 'ready', pid: process.pid });
