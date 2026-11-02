import { appendFileSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { createHash } from 'node:crypto';
import { createAgentSession, DefaultResourceLoader, ModelRuntime, SessionManager,
  SettingsManager } from '@earendil-works/pi-coding-agent';
import piNodrop from '../src/extension.mjs';
import outputReferences from '../src/output-extension.mjs';
import { auditPolicyGuideline } from '../src/tools.mjs';
import { businessToolNames, policyToolGuideline, policyToolNames } from '../src/policy-tools.mjs';
import { getIbrainCredential } from './test-credentials.mjs';

const taskFile = process.argv[2];
const agentDir = process.env.PI_NODROP_AGENT_DIR;
const output = process.env.PI_NODROP_TRIAL_DIR;
if (!taskFile || !agentDir || !output) {
  throw new Error('Provide an instruction file, PI_NODROP_AGENT_DIR and PI_NODROP_TRIAL_DIR');
}
mkdirSync(output, { recursive: true });
process.env.PI_NODROP_OUTPUT = resolve(output, 'pi');
const config = JSON.parse(readFileSync(resolve(agentDir, 'settings.json'), 'utf8'));
const settingsManager = SettingsManager.inMemory(config);
const modelRuntime = await ModelRuntime.create({
  modelsPath: resolve(agentDir, 'models.json'), authPath: resolve(agentDir, 'auth.json'),
  refreshOnCreate: false,
});
const model = modelRuntime.getModel(config.defaultProvider, config.defaultModel);
if (!model) throw new Error('Configured model is unavailable');
let credentialName = null;
if (config.defaultProvider === 'ibrain') {
  const credential = getIbrainCredential();
  await modelRuntime.setRuntimeApiKey('ibrain', credential.key);
  credentialName = credential.name;
}
const audit = process.env.PI_NODROP_AUDIT ?? 'on';
if (!['on', 'off'].includes(audit)) throw new Error('Audit must be on or off');
const controlMode = process.env.PI_NODROP_CONTROL_MODE ?? 'agent';
if (!['agent', 'agent-names', 'configured', 'fixed-raw'].includes(controlMode)) throw new Error('Unknown control mode');
const outputMode = process.env.PI_NODROP_OUTPUT_MODE ?? 'reference';
if (!['inline', 'reference'].includes(outputMode)) throw new Error('Unknown output mode');
let requests = 0;
function observeRequests(pi) {
  pi.on('before_provider_request', event => {
    const payload = JSON.stringify(event.payload);
    const sha256 = value => createHash('sha256').update(JSON.stringify(value)).digest('hex');
    const body = event.payload;
    const index = ++requests;
    writeFileSync(resolve(output, `request-${index}.json`), payload + '\n');
    appendFileSync(resolve(output, 'requests.jsonl'), JSON.stringify({ index,
      bytes: Buffer.byteLength(payload), sha256: sha256(body),
      toolsSha256: sha256(body.tools ?? null),
      messagesSha256: sha256(body.messages ?? null) }) + '\n');
  });
}
const loader = new DefaultResourceLoader({ cwd: process.cwd(), agentDir, settingsManager,
  extensionFactories: [observeRequests, ...(audit === 'on' ? [piNodrop]
    : outputMode === 'reference' ? [outputReferences] : [])], noExtensions: true, noSkills: true,
  noPromptTemplates: true, noThemes: true, noContextFiles: true,
});
await loader.reload();
if (loader.getExtensions().errors.length) throw new Error('Pi extension loading failed');
const { session } = await createAgentSession({ cwd: process.cwd(), agentDir,
  resourceLoader: loader, modelRuntime, model, settingsManager,
  sessionManager: SessionManager.inMemory(),
  tools: controlMode === 'agent-names' ? policyToolNames : businessToolNames,
});
const started = Date.now();
const limits = { turns: null, tools: null, tokens: null,
  timeoutSec: Number(process.env.PI_NODROP_TIMEOUT_SEC ?? 900) };
let turns = 0, tools = 0, tokens = 0, stop = null, error = null;
const usage = { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 };
let lastStopReason = null;
function abort(reason) {
  if (stop) return;
  stop = reason;
  void session.abort();
}
const timer = setTimeout(() => abort('timeout'), limits.timeoutSec * 1000);
process.on('SIGINT', () => abort('interrupted'));
process.on('SIGTERM', () => abort('interrupted'));
const unsubscribe = session.subscribe(event => {
  if (event.type === 'tool_execution_start') {
    tools++;
    console.log(JSON.stringify({ type: event.type, tool: event.toolName, id: event.toolCallId }));
  }
  if (event.type === 'message_end' && event.message.role === 'assistant') {
    turns++;
    tokens += event.message.usage?.totalTokens ?? 0;
    for (const key of Object.keys(usage)) usage[key] += event.message.usage?.[key] ?? 0;
  }
  if (['tool_execution_start', 'tool_execution_end', 'turn_start', 'turn_end',
    'agent_start', 'agent_end', 'auto_retry_start', 'auto_retry_end'].includes(event.type)) {
    appendFileSync(resolve(output, 'agent-events.jsonl'), JSON.stringify(event) + '\n');
  }
});
try {
  await session.prompt(readFileSync(taskFile, 'utf8'));
  const assistant = session.messages.filter(m => m.role === 'assistant').at(-1);
  lastStopReason = assistant?.stopReason ?? null;
  if (assistant?.stopReason === 'error') error = assistant.errorMessage ?? 'Model request failed';
  if (assistant?.stopReason === 'length' && !stop) stop = 'output_limit';
} catch (cause) {
  error = cause.message;
} finally {
  clearTimeout(timer);
  await session.abort();
  unsubscribe();
  writeFileSync(resolve(output, 'transcript.json'), JSON.stringify(session.messages, null, 2) + '\n');
  await session.extensionRunner.emit({ type: 'session_shutdown', reason: 'exit' });
  session.dispose();
  const result = { provider: model.provider, model: model.id, api: model.api,
    credentialName,
    maxOutputTokens: model.maxTokens, lastStopReason,
    audit, controlMode,
    outputMode,
    outputInlineBytes: outputMode === 'reference' ? Number(process.env.PI_NODROP_INLINE_BYTES ?? 4096) : null,
    auditPolicyGuideline: audit === 'off' ? null : controlMode === 'agent' ? auditPolicyGuideline
      : controlMode === 'agent-names' ? policyToolGuideline : null,
    policies: audit === 'on' && controlMode === 'configured' ? JSON.parse(process.env.PI_NODROP_POLICIES ?? '{}') : null,
    requests, usage, turns, tools, totalTokens: tokens, elapsedSec: (Date.now() - started) / 1000,
    stop, error, limits };
  writeFileSync(resolve(output, 'agent-result.json'), JSON.stringify(result, null, 2) + '\n');
  console.log(JSON.stringify(result));
  if (error || stop) process.exitCode = 1;
}
