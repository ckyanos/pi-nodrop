import assert from 'node:assert/strict';
import { existsSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { OutputStore } from '../src/output-store.mjs';

const [results, artifacts, output] = process.argv.slice(2);
if (!results || !artifacts || !output)
  throw new Error('Usage: node scripts/measure_output_view.mjs RESULTS NEW_ARTIFACT_DIR REPORT');
assert(!existsSync(artifacts), 'Use a new artifact directory');
mkdirSync(artifacts, { recursive: true });
const read = path => JSON.parse(readFileSync(path, 'utf8'));
const text = content => content.filter(c => c.type === 'text').map(c => c.text).join('\n');
const bytes = value => Buffer.byteLength(value);
const runs = [];
for (const entry of readdirSync(results, { withFileTypes: true }).filter(e => e.isDirectory())) {
  const directory = join(results, entry.name);
  const messages = read(join(directory, 'transcript.json'));
  const calls = new Map(readFileSync(join(directory, 'pi/calls.jsonl'), 'utf8').trim().split('\n')
    .map(JSON.parse).filter(c => c.kind === 'begin').map(c => [c.tool_call_id, c]));
  const store = new OutputStore(join(artifacts, entry.name));
  const views = new Map(), external = [];
  let originalBytes = 0, viewBytes = 0;
  for (const result of messages.filter(m => m.role === 'toolResult')) {
    const call = calls.get(result.toolCallId);
    // Replay the persisted model-facing text, independently of old temporary stdout files.
    const { fullOutputPath: _upstream, ...details } = result.details ?? {};
    const original = { content: result.content, isError: result.isError, details };
    const shown = call ? await store.present(original, { toolCallId: result.toolCallId,
      callRef: call.call_ref, toolName: result.toolName }) : original;
    const oldText = text(original.content), newText = text(shown.content);
    originalBytes += bytes(oldText); viewBytes += bytes(newText);
    views.set(result.toolCallId, newText);
    if (shown.details?.outputIndex) {
      assert(bytes(newText) < 4096);
      assert.equal(readFileSync(join(store.root, call.call_ref, 'output.txt'), 'utf8'), oldText);
      external.push({ tool: result.toolName, original_text_bytes: bytes(oldText),
        view_text_bytes: bytes(newText), pages: shown.details.outputIndex.pages });
    }
  }
  let originalPayloadBytes = 0, projectedPayloadBytes = 0;
  const requests = readdirSync(directory).filter(name => /^request-\d+\.json$/.test(name));
  for (const name of requests) {
    const body = read(join(directory, name));
    originalPayloadBytes += bytes(JSON.stringify(body));
    for (const message of body.messages) {
      if (message.role === 'tool' && views.has(message.tool_call_id)) {
        assert.equal(typeof message.content, 'string');
        message.content = views.get(message.tool_call_id);
      }
    }
    projectedPayloadBytes += bytes(JSON.stringify(body));
  }
  runs.push({ task: entry.name, original_result_text_bytes: originalBytes,
    projected_result_text_bytes: viewBytes, requests: requests.length,
    original_request_payload_bytes: originalPayloadBytes,
    projected_request_payload_bytes: projectedPayloadBytes, external_outputs: external });
}
const total = key => runs.reduce((sum, run) => sum + run[key], 0);
const report = { scope: 'Saved model-facing tool texts; same calls and requests; byte projection only',
  model_requests: 0, retrieval_rounds_simulated: false, schema_changes_included: false, inline_bytes: 4096,
  runs, totals: Object.fromEntries(['original_result_text_bytes', 'projected_result_text_bytes',
    'original_request_payload_bytes', 'projected_request_payload_bytes'].map(key => [key, total(key)])) };
writeFileSync(output, JSON.stringify(report, null, 2) + '\n');
console.log(JSON.stringify(report.totals));
