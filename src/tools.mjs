import {
  createBashToolDefinition, createReadToolDefinition, createWriteToolDefinition,
  createEditToolDefinition, createGrepToolDefinition, createFindToolDefinition, createLsToolDefinition,
} from '@earendil-works/pi-coding-agent';

export function toolDefinitions(cwd) {
  return [createBashToolDefinition(cwd), createReadToolDefinition(cwd),
    createWriteToolDefinition(cwd), createEditToolDefinition(cwd),
    createGrepToolDefinition(cwd), createFindToolDefinition(cwd), createLsToolDefinition(cwd)];
}
