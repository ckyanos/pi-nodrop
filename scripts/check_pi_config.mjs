import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { ModelRuntime, SettingsManager } from '@earendil-works/pi-coding-agent';

const directory = resolve(process.argv[2]);
const config = JSON.parse(readFileSync(resolve(directory, 'settings.json'), 'utf8'));
const settings = SettingsManager.create(process.cwd(), directory);
assert.equal(settings.getDefaultProvider(), config.defaultProvider);
assert.equal(settings.getDefaultModel(), config.defaultModel);
const runtime = await ModelRuntime.create({
  modelsPath: resolve(directory, 'models.json'), authPath: resolve(directory, 'auth.json'),
  refreshOnCreate: false,
});
const credentials = await runtime.listCredentials();
assert(credentials.some(c => c.providerId === config.defaultProvider));
const model = runtime.getModel(config.defaultProvider, config.defaultModel);
assert(model);
console.log(JSON.stringify({ nativeSettingsRead: true, nativeCredentialRead: true,
  provider: model.provider, model: model.id, maxOutputTokens: model.maxTokens, modelRequests: 0 }));
