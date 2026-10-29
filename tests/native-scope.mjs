import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { appendFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { spawn } from 'node:child_process';
import { once } from 'node:events';

const backend = createRequire(import.meta.url)('../build/context.node');
assert.equal(process.env.UV_THREADPOOL_SIZE, '1');
const calls = resolve('results/pi/calls.jsonl');
const cwd = resolve('results/workload');
const write = (name, text) => writeFileSync(resolve(cwd, name), text);
for (const [id, ref] of [['scope-A', 0x1001n], ['scope-B', 0x1002n]]) {
  appendFileSync(calls, JSON.stringify({ kind: 'begin', tool_call_id: id,
    call_ref: ref.toString(16).padStart(16, '0'), tool_name: 'native-scope-check',
    policy_id: 1, worker_pid: process.pid, input: { path: `${id}.txt` } }) + '\n');
  backend.setContext(ref, 1);
  assert.equal(backend.getContext().callRef, ref);
  assert.throws(() => backend.setContext(ref, 99), /Invalid argument/);
  assert.equal(backend.getContext().callRef, ref);
  write(`${id}.txt`, id);
  await backend.flush();
  backend.setContext(0n, 0);
  assert.equal(backend.getContext().callRef, 0n);
  write(`unbound-${id}.txt`, 'This event must not enter the tool audit.');
}
// A descendant keeps A's snapshot after its parent clears A and starts B.
const register = (id, ref) => appendFileSync(calls, JSON.stringify({ kind: 'begin',
  tool_call_id: id, call_ref: ref.toString(16).padStart(16, '0'), tool_name: 'native-scope-check',
  policy_id: 1, worker_pid: process.pid, input: {} }) + '\n');
register('scope-parent', 0x2001n);
backend.setContext(0x2001n, 1);
const child = spawn('python3', ['-u', '-c',
  'import sys; print("ready", flush=True); sys.stdin.read(1); open(sys.argv[1], "w").write("child")',
  resolve(cwd, 'scope-background.txt')], { stdio: ['pipe', 'pipe', 'inherit'] });
const ended = once(child, 'exit');
await once(child.stdout, 'data');
await backend.flush();
backend.setContext(0n, 0);
register('scope-overlap', 0x2002n);
backend.setContext(0x2002n, 1);
write('scope-overlap.txt', 'parent B');
child.stdin.end('x');
assert.equal((await ended)[0], 0);
await backend.flush();
backend.setContext(0n, 0);
console.log('native scope set/clear and rejected policy checks passed');
