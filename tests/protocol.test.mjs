import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { AuditExecutor } from '../src/client.mjs';

test('real Pi tools execute concurrently in separate workers and keep exact call IDs', async () => {
  const cwd = mkdtempSync(join(tmpdir(), 'pi-nodrop-test-'));
  const executor = new AuditExecutor({ cwd, output: join(cwd, 'audit'), workers: 2, backend: 'none' });
  try {
    await executor.ready;
    const results = await Promise.all([
      executor.execute('write', 'call-A', { path: 'A.txt', content: 'alpha' }),
      executor.execute('write', 'call-B', { path: 'B.txt', content: 'beta' }),
    ]);
    assert.equal(results.length, 2);
    assert.equal(readFileSync(join(cwd, 'A.txt'), 'utf8'), 'alpha');
    const calls = readFileSync(join(cwd, 'audit/calls.jsonl'), 'utf8').trim().split('\n').map(JSON.parse);
    const begins = calls.filter(c => c.kind === 'begin');
    assert.deepEqual(begins.map(c => c.tool_call_id), ['call-A', 'call-B']);
    assert.notEqual(begins[0].worker_pid, begins[1].worker_pid);
    assert.notEqual(begins[0].call_ref, begins[1].call_ref);
    await assert.rejects(executor.execute('read', 'call-A', { path: 'A.txt' }), /Duplicate/);
  } finally { await executor.close(); }
});

test('tool errors and aborts release the worker for the following call', async () => {
  const cwd = mkdtempSync(join(tmpdir(), 'pi-nodrop-test-'));
  const executor = new AuditExecutor({ cwd, output: join(cwd, 'audit'), workers: 1, backend: 'none' });
  try {
    await executor.ready;
    await assert.rejects(executor.execute('read', 'missing', { path: 'missing.txt' }));
    const abort = new AbortController(); abort.abort();
    await assert.rejects(executor.execute('bash', 'cancelled', { command: 'sleep 10' }, { signal: abort.signal }), /aborted/);
    writeFileSync(join(cwd, 'ok.txt'), 'ok');
    const result = await executor.execute('read', 'next', { path: 'ok.txt' });
    assert.match(result.content[0].text, /ok/);
  } finally { await executor.close(); }
});
