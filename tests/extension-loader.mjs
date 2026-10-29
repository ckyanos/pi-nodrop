import assert from 'node:assert/strict';
import { resolve } from 'node:path';
import { discoverAndLoadExtensions } from '@earendil-works/pi-coding-agent';

process.env.PI_NODROP_OUTPUT = resolve('build/extension-loader-metadata');
const result = await discoverAndLoadExtensions([resolve('src/extension.mjs')], process.cwd(),
  resolve('build/empty-agent-dir'));
assert.deepEqual(result.errors, []);
const extension = result.extensions.find(item => item.resolvedPath === resolve('src/extension.mjs')) ?? result.extensions[0];
assert(extension);
assert.equal(extension.tools.size, 7);
const names = [...extension.tools.keys()].sort();
assert.deepEqual(names, ['bash', 'edit', 'find', 'grep', 'ls', 'read', 'write']);
for (const handler of extension.handlers.get('session_shutdown') ?? []) await handler({}, {});
console.log(JSON.stringify({ loader: 'Pi discoverAndLoadExtensions', registeredTools: names, shutdown: 'passed' }));
