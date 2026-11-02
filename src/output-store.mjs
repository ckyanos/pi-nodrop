import { chmod, copyFile, mkdir, open, readFile, realpath, stat, writeFile } from 'node:fs/promises';
import { basename, dirname, isAbsolute, relative, resolve, sep } from 'node:path';

export const DEFAULT_INLINE_BYTES = 4096;

function within(root, path) {
  const child = relative(root, path);
  return child !== '..' && !child.startsWith(`..${sep}`) && !isAbsolute(child);
}

function textBytes(text, limit, tail = false) {
  const chars = [...text];
  let result = '', used = 0;
  for (const char of tail ? chars.reverse() : chars) {
    const size = Buffer.byteLength(char);
    if (used + size > limit) break;
    result = tail ? char + result : result + char;
    used += size;
  }
  return result;
}

export class OutputStore {
  constructor(root, inlineBytes = DEFAULT_INLINE_BYTES, readTools = ['read']) {
    if (!Number.isSafeInteger(inlineBytes) || inlineBytes < 1024)
      throw new Error('Output inline bytes must be an integer >= 1024');
    this.root = resolve(root);
    this.inlineBytes = inlineBytes;
    this.readTools = readTools;
  }

  async present(result, { toolCallId, callRef, outputRef = callRef, toolName }) {
    const text = (result.content ?? []).filter(c => c.type === 'text').map(c => c.text).join('\n');
    if (Buffer.byteLength(text) <= this.inlineBytes) return result;
    if (!/^[0-9a-f]{16}$/.test(outputRef)) throw new Error('Invalid output reference');
    const directory = resolve(this.root, outputRef);
    await mkdir(this.root, { recursive: true, mode: 0o700 });
    await mkdir(directory, { mode: 0o700 });
    await writeFile(resolve(directory, 'result.json'), JSON.stringify(result) + '\n', { mode: 0o600 });
    const payload = resolve(directory, 'output.txt');
    const upstream = toolName === 'bash' ? result.details?.fullOutputPath : undefined;
    let source = 'tool-result-text';
    if (upstream) {
      await copyFile(upstream, payload);
      await chmod(payload, 0o600);
      source = 'pi-full-output';
    } else await writeFile(payload, text, { mode: 0o600 });
    const bytes = (await stat(payload)).size;
    const pageBytes = Math.min(2048, Math.floor(this.inlineBytes / 2));
    const index = { version: 1, kind: 'pi-tool-output', output_ref: outputRef, call_ref: callRef ?? null,
      tool_call_id: toolCallId, tool_name: toolName, is_error: Boolean(result.isError),
      exit_code: result.structuredContent?.exit_code ?? null,
      bytes, page_bytes: pageBytes, pages: Math.max(1, Math.ceil(bytes / pageBytes)), source,
      upstream_truncated: Boolean(result.details?.truncation?.truncated),
      payload_file: 'output.txt', result_file: 'result.json' };
    const indexPath = resolve(directory, 'index.json');
    await writeFile(indexPath, JSON.stringify(index) + '\n', { mode: 0o600 });
    const previewBytes = Math.min(512, Math.floor(this.inlineBytes / 8));
    const content = [
      `Stored output: ${bytes} bytes; ${index.pages} pages. Status: ${result.isError ? 'error' : 'success'}${index.exit_code === null ? '' : `; exit ${index.exit_code}`}.`,
      `Output index: ${indexPath}`,
      `Use ${this.readTools.join(' or ')} with this index path and output_page=1 (or another page number).`,
      `Preview:\n${textBytes(text, previewBytes)}\n[... stored externally ...]\n${textBytes(text, previewBytes, true)}`,
    ].join('\n');
    return { ...result,
      content: [{ type: 'text', text: content }, ...(result.content ?? []).filter(c => c.type !== 'text')],
      details: { ...result.details, outputIndex: { path: indexPath, ...index } } };
  }
}

export async function readOutputPage(input, { root, cwd, signal }) {
  if (signal?.aborted) throw new Error('Operation aborted');
  if (!root) throw new Error('Stored output retrieval requires reference output mode');
  if (!Number.isSafeInteger(input.output_page) || input.output_page < 1)
    throw new Error('output_page must be an integer >= 1');
  if (input.offset !== undefined || input.limit !== undefined)
    throw new Error('Use output_page without offset or limit');
  const ownedRoot = await realpath(root);
  const path = await realpath(resolve(cwd, input.path));
  if (!within(ownedRoot, path) || basename(path) !== 'index.json')
    throw new Error('Path is not a stored tool-output index');
  const index = JSON.parse(await readFile(path, { encoding: 'utf8', signal }));
  if (index.kind !== 'pi-tool-output' || index.version !== 1
    || (index.output_ref ?? index.call_ref) !== basename(dirname(path))
    || !Number.isSafeInteger(index.page_bytes) || index.page_bytes < 1
    || index.page_bytes > 1048576 || !Number.isSafeInteger(index.bytes) || index.bytes < 0
    || index.pages !== Math.max(1, Math.ceil(index.bytes / index.page_bytes)))
    throw new Error('Invalid stored tool-output index');
  if (input.output_page > index.pages) throw new Error(`Output has ${index.pages} pages`);
  const payload = await realpath(resolve(dirname(path), 'output.txt'));
  if (!within(ownedRoot, payload)) throw new Error('Stored output is outside the output directory');
  const file = await open(payload, 'r');
  let start, end, content;
  try {
    if ((await file.stat()).size !== index.bytes) throw new Error('Stored output size has changed');
    const boundaryStart = (input.output_page - 1) * index.page_bytes;
    const boundaryEnd = Math.min(boundaryStart + index.page_bytes, index.bytes);
    const buffer = Buffer.alloc(Math.min(index.page_bytes + 3, index.bytes - boundaryStart));
    let bytesRead = 0;
    while (bytesRead < buffer.length) {
      const part = await file.read(buffer, bytesRead, buffer.length - bytesRead, boundaryStart + bytesRead);
      if (!part.bytesRead) throw new Error('Stored output ended unexpectedly');
      bytesRead += part.bytesRead;
    }
    let left = 0, right = boundaryEnd - boundaryStart;
    // Adjacent pages move both boundaries forward to the same UTF-8 character boundary.
    if (boundaryStart) while (left < bytesRead && (buffer[left] & 0xc0) === 0x80) left++;
    while (right < bytesRead && (buffer[right] & 0xc0) === 0x80) right++;
    start = boundaryStart + left; end = boundaryStart + right;
    content = buffer.subarray(left, right).toString('utf8');
  } finally { await file.close(); }
  if (signal?.aborted) throw new Error('Operation aborted');
  const text = `Output ${index.output_ref ?? index.call_ref}, page ${input.output_page}/${index.pages}, bytes ${start}:${end}/${index.bytes}.\n${content}`;
  return { content: [{ type: 'text', text }], structuredContent: text,
    details: { outputPage: { index: path, page: input.output_page, pages: index.pages, start, end, text: content } } };
}
