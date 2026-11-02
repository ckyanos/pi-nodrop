import net from 'node:net';
import { appendFileSync, existsSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

// AgentSentinel's original A2M wire protocol, including its handshake and opcodes.
class SentinelClient {
  constructor(path) {
    this.path = path;
    this.buffer = Buffer.alloc(0);
    this.readers = [];
  }
  read(size) {
    return new Promise((resolve, reject) => {
      this.readers.push({ size, resolve, reject });
      this.drain();
    });
  }
  drain() {
    while (this.readers.length && this.buffer.length >= this.readers[0].size) {
      const { size, resolve } = this.readers.shift();
      const data = this.buffer.subarray(0, size);
      this.buffer = this.buffer.subarray(size);
      resolve(data);
    }
  }
  async connect() {
    this.socket = net.createConnection(this.path);
    this.socket.on('data', data => { this.buffer = Buffer.concat([this.buffer, data]); this.drain(); });
    this.socket.on('error', error => { for (const r of this.readers.splice(0)) r.reject(error); });
    this.socket.on('end', () => { for (const r of this.readers.splice(0)) r.reject(new Error('Sentinel socket closed')); });
    await new Promise((resolve, reject) => { this.socket.once('connect', resolve); this.socket.once('error', reject); });
    this.socket.write('x$!@');
    if ((await this.read(4)).toString() !== '$@!$') throw new Error('Sentinel handshake failed');
    await this.request(0, { pid: process.pid, core_file_paths: [fileURLToPath(import.meta.url)] });
    await this.request(4);
  }
  async request(op, value) {
    const data = value === undefined ? Buffer.alloc(0) : Buffer.from(JSON.stringify(value));
    const header = Buffer.alloc(6);
    header.writeInt16LE(op, 0); header.writeInt32LE(data.length, 2);
    this.socket.write(Buffer.concat([header, data]));
    const response = await this.read(6);
    return await this.read(response.readInt32LE(2));
  }
}

const text = content => typeof content === 'string' ? content
  : (content ?? []).filter(c => c.type === 'text').map(c => c.text).join('\n');

export default function sentinelExtension(pi) {
  const shared = process.env.PI_AUDIT_SHARED;
  const mode = process.env.PI_AUDIT_MODE;
  let client;
  let queue = Promise.resolve();
  let messages = [];
  const record = value => appendFileSync(`${shared}/extension-events.jsonl`, JSON.stringify({ at: Date.now(), ...value }) + '\n');
  const serial = fn => { const task = queue.then(fn); queue = task; return task; };

  pi.on('session_start', async () => {
    process.title = 'pi';
    writeFileSync(`${shared}/ready.json`, JSON.stringify({ pid: process.pid, executable: process.execPath }));
    while (!existsSync(`${shared}/monitor-ready`)) await new Promise(resolve => setTimeout(resolve, 100));
    if (mode === 'sentinel') {
      client = new SentinelClient(`${shared}/computer-monitor.sock`);
      try {
        await client.connect();
      } catch (error) {
        writeFileSync(`${shared}/connection-failure.json`, JSON.stringify({ error: String(error) }));
        client.socket?.destroy();
        process.stderr.write(`Native Sentinel connection failed: ${String(error)}\n`);
        process.exit(1);
      }
    }
    record({ kind: 'connected', mode });
    writeFileSync(`${shared}/client-ready`, '');
  });
  if (mode !== 'sentinel') return;
  pi.on('before_agent_start', event => {
    if (event.messageType === 'user') messages.push({ role: 'user', message: event.prompt });
  });
  pi.on('message_end', event => {
    if (event.message.role === 'assistant') {
      const message = text(event.message.content);
      if (message) messages.push({ role: 'ai_agent', message });
    }
  });
  pi.on('tool_call', event => serial(async () => {
    messages.push({ role: 'ai_agent', message: `Tool Use: ${event.toolName}\nTool Input: ${JSON.stringify(event.input)}` });
    await client.request(5, messages);
    messages = [];
    record({ kind: 'tool_call', tool_call_id: event.toolCallId, tool: event.toolName });
  }));
  pi.on('tool_result', event => serial(async () => {
    const output = text(event.content);
    let alert = '';
    if (event.isError) {
      const raw = await client.request(6);
      if (raw.length) alert = JSON.parse(raw.toString()).msg ?? '';
    }
    if (output) messages.push({ role: 'user', message: `Tool Use Results:\n${output}` });
    record({ kind: 'tool_result', tool_call_id: event.toolCallId, is_error: event.isError, alert: Boolean(alert) });
    if (alert) return { content: [...event.content, { type: 'text', text: alert }] };
  }));
  pi.on('session_shutdown', async () => { await queue; client?.socket.end(); });
}
