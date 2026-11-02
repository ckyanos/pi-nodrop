import {
  createBashToolDefinition, createReadToolDefinition, createWriteToolDefinition,
  createEditToolDefinition, createGrepToolDefinition, createFindToolDefinition, createLsToolDefinition,
} from '@earendil-works/pi-coding-agent';
import { randomBytes } from 'node:crypto';
import { readOutputPage } from './output-store.mjs';

export const auditPolicyGuideline = 'Set audit_policy in every tool call: raw keeps syscall arguments and order; counts keeps event-type totals and time bounds. Example: {"command":"pwd","audit_policy":"counts"}.';

export function toolDefinitions(cwd) {
  return [createBashToolDefinition(cwd), createReadToolDefinition(cwd),
    createWriteToolDefinition(cwd), createEditToolDefinition(cwd),
    createGrepToolDefinition(cwd), createFindToolDefinition(cwd), createLsToolDefinition(cwd)];
}

function outputParameters(definition) {
  if (definition.name !== 'read') return definition.parameters;
  return { ...definition.parameters, properties: { ...definition.parameters.properties,
    output_page: { type: 'integer', minimum: 1,
      description: 'Read a 1-based page from a stored tool-output index; omit offset/limit.' } } };
}

export function outputToolDefinitions(cwd, store) {
  return toolDefinitions(cwd).map(definition => ({ ...definition,
    parameters: outputParameters(definition),
    async execute(id, input, signal, onUpdate, ctx) {
      const identity = { toolCallId: id, outputRef: randomBytes(8).toString('hex'), toolName: definition.name };
      let result;
      try {
        result = definition.name === 'read' && input.output_page !== undefined
          ? await readOutputPage(input, { root: store.root, cwd, signal })
          : await definition.execute(id, input, signal, onUpdate, ctx);
      } catch (error) {
        const shown = await store.present({ content: [{ type: 'text', text: error.message }], isError: true }, identity);
        throw new Error(shown.content[0].text);
      }
      return store.present(result, identity);
    },
  }));
}

export function auditedToolDefinitions(cwd, executor) {
  if (executor.policyMode === 'agent-names') {
    return toolDefinitions(cwd).flatMap(definition => ['raw', 'counts'].map(policy => {
      const name = `${definition.name}_${policy}`;
      const references = value => value.replace(new RegExp(`\\b${definition.name}\\b`, 'g'),
        `${definition.name}_raw or ${definition.name}_counts`);
      return { ...definition, name,
        description: `${policy === 'raw' ? 'Audit: retain syscall arguments and order.' : 'Audit: retain event-type totals and time bounds.'}\n${definition.description}`,
        parameters: executor.outputMode === 'reference' ? outputParameters(definition) : definition.parameters,
        promptGuidelines: definition.promptGuidelines?.map(references),
        prepareArguments(input) {
          if (input && Object.hasOwn(input, 'audit_policy'))
            throw new Error('Select the audit policy in the tool name and omit audit_policy.');
          return definition.prepareArguments ? definition.prepareArguments(input) : input;
        },
        execute: (id, input, signal, onUpdate, ctx) => executor.execute(name, id, input, { signal, onUpdate, ctx }),
      };
    }));
  }
  return toolDefinitions(cwd).map(definition => {
    const tool = { ...definition,
      execute: (id, input, signal, onUpdate, ctx) => executor.execute(
        definition.name, id, input, { signal, onUpdate, ctx }),
    };
    if (definition.name === 'read' && executor.outputMode === 'reference') {
      tool.parameters = outputParameters(definition);
    }
    if (executor.policyMode !== 'agent') return tool;
    tool.parameters = { ...tool.parameters,
      properties: { audit_policy: {
        type: 'string', enum: ['raw', 'counts'],
      }, ...tool.parameters.properties },
      required: ['audit_policy', ...(definition.parameters.required ?? [])],
    };
    tool.prepareArguments = input => {
      if (!input || typeof input !== 'object' || Array.isArray(input)
        || !['raw', 'counts'].includes(input.audit_policy))
        throw new Error('Set audit_policy to "raw" or "counts" and resubmit this tool call.');
      if (!definition.prepareArguments) return input;
      const { audit_policy, ...business } = input;
      return { ...definition.prepareArguments(business), audit_policy };
    };
    return tool;
  });
}
