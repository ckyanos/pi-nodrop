import { appendFileSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { resolve } from 'node:path';
import { performance } from 'node:perf_hooks';
import { AuditExecutor } from '../src/client.mjs';

const source = process.argv[2];
const output = process.env.PI_NODROP_TRIAL_DIR;
if (!source || !output) throw new Error('Provide a saved transcript and PI_NODROP_TRIAL_DIR');
mkdirSync(output, { recursive: true });
const bytes = readFileSync(source);
const transcript = JSON.parse(bytes.toString('utf8'));
const groups = transcript.filter(m => m.role === 'assistant')
  .map(m => (m.content ?? []).filter(c => c.type === 'toolCall')).filter(g => g.length);
const expected = new Map(transcript.filter(m => m.role === 'toolResult').map(m => [m.toolCallId, !!m.isError]));
const policyMode = process.env.PI_NODROP_CONTROL_MODE ?? 'configured';
const policies = JSON.parse(process.env.PI_NODROP_POLICIES ?? '{}');
const executor = new AuditExecutor({ cwd: process.cwd(), output: resolve(output, 'pi'),
  workers: 2, policies, policyMode });
const controller = new AbortController();
let stop = null, error = null, tools = 0, toolErrors = 0, expectedErrorMismatches = 0;
const timer = setTimeout(() => { stop = 'timeout'; controller.abort(); },
  Number(process.env.PI_NODROP_TIMEOUT_SEC ?? 900) * 1000);
process.on('SIGTERM', () => { stop = 'interrupted'; controller.abort(); });
const started = performance.now();
try {
  await executor.ready;
  for (const group of groups) {
    if (controller.signal.aborted) break;
    await Promise.all(group.map(async call => {
      tools++;
      let result, toolError = null;
      try { result = await executor.execute(call.name, call.id, call.arguments, { signal: controller.signal }); }
      catch (cause) { toolError = cause.message; }
      const isError = !!toolError || !!result?.isError;
      if (isError) toolErrors++;
      if (isError !== expected.get(call.id)) expectedErrorMismatches++;
      appendFileSync(resolve(output, 'replay-results.jsonl'), JSON.stringify({
        toolCallId: call.id, tool: call.name, arguments: call.arguments,
        result, error: toolError, isError, expectedIsError: expected.get(call.id) }) + '\n');
      console.log(JSON.stringify({ tool: call.name, id: call.id, isError }));
    }));
  }
} catch (cause) { error = cause.message; }
finally {
  clearTimeout(timer);
  await executor.close();
  const result = { mode: 'tool-replay', policyMode, policies, sourceSha256:
    createHash('sha256').update(bytes).digest('hex'), groups: groups.length, tools,
    expectedTools: groups.flat().length, toolErrors, expectedErrorMismatches,
    apiRequests: 0, totalTokens: 0, elapsedSec: (performance.now() - started) / 1000, stop, error };
  writeFileSync(resolve(output, 'agent-result.json'), JSON.stringify(result, null, 2) + '\n');
  console.log(JSON.stringify(result));
  if (error || stop || expectedErrorMismatches || tools !== result.expectedTools) process.exitCode = 1;
}
