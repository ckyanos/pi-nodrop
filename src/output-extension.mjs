import { resolve } from 'node:path';
import { OutputStore } from './output-store.mjs';
import { outputToolDefinitions } from './tools.mjs';

export default function outputReferences(pi) {
  const store = new OutputStore(resolve(process.env.PI_NODROP_OUTPUT, 'outputs'),
    Number(process.env.PI_NODROP_INLINE_BYTES ?? 4096));
  for (const tool of outputToolDefinitions(process.cwd(), store)) pi.registerTool(tool);
}
