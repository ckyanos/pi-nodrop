import { resolve } from 'node:path';
import { AuditExecutor } from './client.mjs';
import { toolDefinitions } from './tools.mjs';

export default function piNodrop(pi) {
  if (process.platform !== 'linux') throw new Error('pi-nodrop requires Linux; run Pi in the test VM');
  const cwd = process.cwd();
  const executor = new AuditExecutor({ cwd,
    output: process.env.PI_NODROP_OUTPUT ?? resolve(cwd, '.pi/nodrop'),
    workers: Number(process.env.PI_NODROP_WORKERS ?? 2),
    policies: JSON.parse(process.env.PI_NODROP_POLICIES ?? '{}'),
  });
  for (const definition of toolDefinitions(cwd)) {
    pi.registerTool({ ...definition,
      execute: (id, input, signal, onUpdate, ctx) => executor.execute(
        definition.name, id, input, { signal, onUpdate, ctx }),
    });
  }
  pi.on('session_shutdown', async () => { await executor.close(); });
}
