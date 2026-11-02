import test from 'node:test';
import assert from 'node:assert/strict';
import net from 'node:net';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import extension from '../src/sentinel-extension.mjs';

test('Pi hooks follow the upstream Sentinel A2M protocol and preserve tool data', { skip: process.platform !== 'linux' }, async () => {
  const dir = mkdtempSync(join(tmpdir(), 'sentinel-protocol-'));
  const frames = [];
  const sockets = new Set();
  const server = net.createServer(socket => {
    sockets.add(socket);
    socket.on('close', () => sockets.delete(socket));
    let buffer = Buffer.alloc(0), hello = false;
    socket.on('data', chunk => {
      buffer = Buffer.concat([buffer, chunk]);
      if (!hello && buffer.length >= 4) {
        assert.equal(buffer.subarray(0, 4).toString(), 'x$!@');
        // api/types.go at the pinned upstream revision defines HELLO_REPLY.
        buffer = buffer.subarray(4); hello = true; socket.write('$@!$');
      }
      while (hello && buffer.length >= 6) {
        const op = buffer.readInt16LE(0), length = buffer.readInt32LE(2);
        if (buffer.length < 6 + length) break;
        const raw = buffer.subarray(6, 6 + length);
        frames.push({ op, data: length ? JSON.parse(raw.toString()) : null });
        buffer = buffer.subarray(6 + length);
        const body = op === 6 ? Buffer.from(JSON.stringify({ msg: 'native monitor alert' })) : Buffer.alloc(0);
        const header = Buffer.alloc(6); header.writeInt16LE(op); header.writeInt32LE(body.length, 2);
        socket.write(Buffer.concat([header, body]));
      }
    });
  });
  const socketPath = join(dir, 'computer-monitor.sock');
  await new Promise(resolve => server.listen(socketPath, resolve));
  const previous = { mode: process.env.PI_AUDIT_MODE, shared: process.env.PI_AUDIT_SHARED, title: process.title };
  try {
    process.env.PI_AUDIT_MODE = 'sentinel'; process.env.PI_AUDIT_SHARED = dir;
    writeFileSync(join(dir, 'monitor-ready'), '');
    const handlers = new Map();
    extension({ on: (event, handler) => handlers.set(event, handler) });
    await handlers.get('session_start')({});
    handlers.get('before_agent_start')({ messageType: 'user', prompt: 'Read the task file' });
    handlers.get('message_end')({ message: { role: 'assistant', content: [{ type: 'text', text: 'Inspect the file.' }] } });
    const call = { toolCallId: 'call-1', toolName: 'read', input: { path: 'task.txt' } };
    const before = structuredClone(call);
    await handlers.get('tool_call')(call);
    assert.deepEqual(call, before);
    assert.deepEqual(frames.map(x => x.op), [0, 4, 5]);
    assert.equal(frames[0].data.pid, process.pid);
    assert.equal(frames[2].data[0].message, 'Read the task file');
    assert.equal(frames[2].data[1].role, 'ai_agent');
    const result = { toolCallId: 'call-1', isError: true, content: [{ type: 'text', text: 'permission denied' }] };
    const decorated = await handlers.get('tool_result')(result);
    assert.equal(decorated.content.at(-1).text, 'native monitor alert');
    assert.equal(result.content.length, 1);
    await handlers.get('tool_call')({ toolCallId: 'call-2', toolName: 'bash', input: { command: 'pwd' } });
    assert.equal(frames.at(-1).data[0].message, 'Tool Use Results:\npermission denied');
    await handlers.get('session_shutdown')({});
  } finally {
    for (const socket of sockets) socket.destroy();
    await new Promise(resolve => server.close(resolve));
    for (const [key, value] of [['PI_AUDIT_MODE', previous.mode], ['PI_AUDIT_SHARED', previous.shared]]) {
      if (value === undefined) delete process.env[key]; else process.env[key] = value;
    }
    process.title = previous.title;
    assert.ok(resolve(dir).startsWith(resolve(tmpdir()) + '/'));
    rmSync(dir, { recursive: true });
  }
});
