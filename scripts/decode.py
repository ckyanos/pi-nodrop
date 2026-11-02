"""Decode the versioned NoDrop records. Association uses only call_ref."""
import argparse
import base64
import json
import pathlib
import re
import struct

ROOT = pathlib.Path(__file__).resolve().parents[1]
HEADER = struct.Struct('<QIHHIIIQII')
MAGIC = 0x50494E44

def schema():
    header = (ROOT / 'vendor/nodrop/include/events.h').read_text(encoding='utf-8')
    ids = {name: int(value) for name, value in re.findall(r'\b(NODE_\w+)\s*=\s*(\d+)', header)}
    table = (ROOT / 'vendor/nodrop/kmodule/tables/events_table.c').read_text(encoding='utf-8')
    result = {}
    for line in table.splitlines():
        match = re.search(r'\[(NODE_\w+)\]\s*=\s*\{"([^"]+)"', line)
        if not match: continue
        symbol, name = match.groups()
        params = re.findall(r'\{"([^"]+)"\s*,\s*(PT_\w+)', line)
        result[ids[symbol]] = (name, params)
    return result

def decode_file(path, schemas):
    data = path.read_bytes()
    offset = 0
    while offset < len(data):
        if len(data) - offset < HEADER.size: raise ValueError(f'Truncated header {path}:{offset}')
        ts, tid, cpu, kind, length, nargs, magic, ref, policy, tgid = HEADER.unpack_from(data, offset)
        if magic != MAGIC or length < HEADER.size + nargs * 2 or offset + length > len(data):
            raise ValueError(f'Invalid prototype record {path}:{offset}, magic={magic:x} len={length}')
        name, params = schemas.get(kind, (f'type_{kind}', []))
        lengths = struct.unpack_from('<' + 'H' * nargs, data, offset + HEADER.size)
        arg_offset = offset + HEADER.size + nargs * 2
        args = {}
        for index, size in enumerate(lengths):
            if arg_offset + size > offset + length: raise ValueError(f'Argument exceeds record {path}:{offset}')
            raw = data[arg_offset:arg_offset + size]
            key, ptype = params[index] if index < len(params) else (str(index), 'PT_BYTEBUF')
            if ptype in ('PT_CHARBUF', 'PT_FSPATH', 'PT_FSRELPATH'):
                value = raw.rstrip(b'\0').decode('utf-8', errors='replace')
            elif ptype == 'PT_BYTEBUF' or len(raw) not in (1, 2, 4, 8):
                value = {'base64': base64.b64encode(raw).decode()}
            else:
                value = int.from_bytes(raw, 'little', signed=ptype in
                    ('PT_INT8', 'PT_INT16', 'PT_INT32', 'PT_INT64', 'PT_FD', 'PT_PID', 'PT_ERRNO'))
            args[key] = value
            arg_offset += size
        yield {'call_ref': f'{ref:016x}', 'policy_id': policy, 'name': name, 'type': kind,
               'tid': tid, 'tgid': tgid, 'cpu': cpu, 'timestamp_ns': ts, 'args': args}
        offset += length

def decode(root):
    schemas = schema()
    calls = [json.loads(line) for line in (root / 'pi/calls.jsonl').read_text(encoding='utf-8').splitlines()]
    identities = {c['call_ref']: c for c in calls if c['kind'] == 'begin'}
    events = []
    for path in sorted((root / 'audit').glob('*.buf')):
        for event in decode_file(path, schemas):
            context = identities.get(event['call_ref'])
            event['tool_call_id'] = context['tool_call_id'] if context else None
            events.append(event)
    counts = []
    for path in sorted((root / 'audit').glob('*.counts.jsonl')):
        for line in path.read_text(encoding='utf-8').splitlines():
            item = json.loads(line)
            context = identities.get(item['call_ref'])
            item['tool_call_id'] = context['tool_call_id'] if context else None
            counts.append(item)
    with (root / 'events.jsonl').open('w', encoding='utf-8') as out:
        for event in events: out.write(json.dumps(event) + '\n')
    (root / 'counts.json').write_text(json.dumps(counts, indent=2) + '\n', encoding='utf-8')
    return calls, events, counts

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('results', nargs='?', default='results', type=pathlib.Path)
    calls, events, counts = decode(parser.parse_args().results)
    print(json.dumps({'calls': len(calls), 'events': len(events), 'count_rows': len(counts)}))
