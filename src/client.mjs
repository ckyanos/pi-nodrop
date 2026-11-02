import { fork } from 'node:child_process';
import { randomBytes } from 'node:crypto';
import { appendFileSync, mkdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { DEFAULT_INLINE_BYTES, OutputStore } from './output-store.mjs';
import { decodePolicyToolName } from './policy-tools.mjs';

export class AuditExecutor {
  constructor({ cwd = process.cwd(), output = resolve(cwd, '.pi/nodrop'), workers = 2,
    policies = {}, backend = 'nodrop', policyMode = 'configured', outputMode = 'inline',
    inlineBytes = DEFAULT_INLINE_BYTES } = {}) {
    if (!Number.isInteger(workers) || workers < 1 || workers > 16) throw new Error('workers must be 1..16');
    if (!['nodrop', 'none'].includes(backend)) throw new Error('Unknown backend');
    if (!['agent', 'agent-names', 'configured', 'fixed-raw'].includes(policyMode)) throw new Error('Unknown policy mode');
    if (!['inline', 'reference'].includes(outputMode)) throw new Error('Unknown output mode');
    this.cwd = cwd;
    this.output = output;
    this.policies = policies;
    this.policyMode = policyMode;
    this.backend = backend;
    this.outputMode = outputMode;
    this.outputStore = outputMode === 'reference' ? new OutputStore(resolve(output, 'outputs'), inlineBytes,
      policyMode === 'agent-names' ? ['read_raw', 'read_counts'] : ['read']) : undefined;
    this.queue = [];
    this.calls = new Set();
    this.refs = new Set();
    this.closed = false;
    mkdirSync(output, { recursive: true });
    this.slots = Array.from({ length: workers }, () => this.spawn());
    this.ready = Promise.all(this.slots.map(s => s.ready));
  }
  log(record) { appendFileSync(resolve(this.output, 'calls.jsonl'), JSON.stringify(record) + '\n'); }
  spawn() {
    const child = fork(fileURLToPath(new URL('./worker.mjs', import.meta.url)), [], {
      execPath: process.execPath, serialization: 'advanced',
      env: { ...process.env, UV_THREADPOOL_SIZE: '1', PI_NODROP_BACKEND: this.backend },
      stdio: ['ignore', 'ignore', 'pipe', 'ipc'],
    });
    const slot = { child, busy: false, readyDone: false, pending: undefined, diagnostic: '' };
    child.stderr.on('data', bytes => { slot.diagnostic = (slot.diagnostic + bytes).slice(-8192); });
    slot.ready = new Promise((resolveReady, rejectReady) => {
      slot.resolveReady = resolveReady; slot.rejectReady = rejectReady;
    });
    slot.exit = new Promise(resolveExit => { slot.resolveExit = resolveExit; });
    child.on('message', async message => {
      if (message.kind === 'ready') {
        slot.readyDone = true; slot.resolveReady(); this.dispatch();
      } else if (message.kind === 'update') slot.pending?.onUpdate?.(message.partial);
      else if (message.kind === 'result' && slot.pending) {
        const job = slot.pending;
        job.signal?.removeEventListener('abort', job.onAbort);
        let result = message.result, error = message.error;
        try {
          if (this.outputStore) {
            result = await this.outputStore.present(error
              ? { content: [{ type: 'text', text: error }], isError: true } : result,
            { toolCallId: job.toolCallId, callRef: job.callRef, toolName: job.toolName });
            if (error) error = result.content[0].text;
          }
        } catch (cause) { error = `Could not store tool output: ${cause.message}`; }
        this.log({ kind: 'end', tool_call_id: job.toolCallId, call_ref: job.callRef,
          worker_pid: message.pid, error: message.error ?? error ?? null,
          output_index: result?.details?.outputIndex?.path, time: new Date().toISOString() });
        slot.pending = undefined; slot.busy = false;
        if (error) job.reject(new Error(error)); else job.resolve(result);
        this.dispatch();
      }
    });
    child.on('error', error => this.workerFailed(slot, error));
    child.on('exit', (code, signal) => {
      slot.resolveExit(); slot.dead = true;
      if (!this.closed || slot.pending)
        this.workerFailed(slot, new Error(`Audit worker exited ${code}/${signal}: ${slot.diagnostic}`));
    });
    return slot;
  }
  workerFailed(slot, error) {
    slot.dead = true;
    slot.rejectReady(error);
    if (slot.pending) {
      slot.pending.signal?.removeEventListener('abort', slot.pending.onAbort);
      slot.pending.reject(error); slot.pending = undefined;
    }
    this.failure = error;
    for (const job of this.queue.splice(0)) job.reject(error);
  }
  execute(toolName, toolCallId, params, { signal, onUpdate, ctx } = {}) {
    if (this.closed || this.failure) return Promise.reject(this.failure ?? new Error('Executor closed'));
    if (!params || typeof params !== 'object' || Array.isArray(params))
      return Promise.reject(new Error('Tool arguments must be an object'));
    const { audit_policy: requestedPolicy, ...toolParams } = params;
    let modelToolName, selectedPolicy;
    if (this.policyMode === 'agent-names') {
      if (Object.hasOwn(params, 'audit_policy'))
        return Promise.reject(new Error('Select the audit policy in the tool name and omit audit_policy.'));
      try {
        const selected = decodePolicyToolName(toolName);
        modelToolName = toolName; toolName = selected.toolName; selectedPolicy = selected.policy;
      } catch (error) { return Promise.reject(error); }
    }
    const policy = this.policyMode === 'agent-names' ? selectedPolicy : this.policyMode === 'agent' ? requestedPolicy
      : this.policyMode === 'fixed-raw' ? 'raw' : (this.policies[toolName] ?? 'raw');
    if (!['raw', 'counts'].includes(policy))
      return Promise.reject(new Error(this.policyMode === 'agent'
        ? 'audit_policy must be raw or counts' : `Unknown audit policy: ${policy}`));
    if (this.calls.has(toolCallId)) return Promise.reject(new Error(`Duplicate tool call ID: ${toolCallId}`));
    this.calls.add(toolCallId);
    let callRef;
    do { callRef = randomBytes(8).toString('hex'); } while (this.refs.has(callRef) || callRef === '0000000000000000');
    this.refs.add(callRef);
    const session = ctx ? { id: ctx.sessionManager?.getSessionId(), file: ctx.sessionManager?.getSessionFile(),
      model: ctx.model, thinkingLevel: ctx.thinkingLevel } : undefined;
    return new Promise((resolveJob, reject) => {
      this.queue.push({ toolName, modelToolName, toolCallId, params: toolParams, input: params, callRef, policyId: policy === 'raw' ? 1 : 2,
        cwd: ctx?.cwd ?? this.cwd, session, signal, onUpdate, resolve: resolveJob, reject });
      this.dispatch();
    });
  }
  dispatch() {
    for (const slot of this.slots ?? []) {
      if (slot.busy || slot.dead || !slot.readyDone) continue;
      const job = this.queue.shift();
      if (!job) break;
      if (job.signal?.aborted) { job.reject(new Error('aborted')); queueMicrotask(() => this.dispatch()); continue; }
      slot.busy = true; slot.pending = job;
      this.log({ kind: 'begin', tool_call_id: job.toolCallId, call_ref: job.callRef,
        tool_name: job.toolName, model_tool_name: job.modelToolName,
        input: job.input, policy_id: job.policyId, policy_source: this.policyMode,
        worker_pid: slot.child.pid, session_id: job.session?.id, time: new Date().toISOString() });
      job.onAbort = () => slot.child.send({ kind: 'abort' });
      job.signal?.addEventListener('abort', job.onAbort, { once: true });
      slot.child.send({ kind: 'execute', toolName: job.toolName, toolCallId: job.toolCallId,
        params: job.params, callRef: job.callRef, policyId: job.policyId, cwd: job.cwd, session: job.session,
        outputRoot: this.outputStore?.root });
      if (job.signal?.aborted) job.onAbort();
    }
  }
  async close() {
    if (this.queue.length || this.slots.some(s => s.pending)) throw new Error('Cannot close while tools are running');
    await this.ready.catch(() => {});
    this.closed = true;
    for (const slot of this.slots) if (!slot.dead && slot.child.connected) slot.child.send({ kind: 'shutdown' });
    await Promise.all(this.slots.map(s => s.exit));
  }
}
