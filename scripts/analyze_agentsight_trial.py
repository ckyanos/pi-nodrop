"""Reassemble native TLS records and invoke the pinned AgentSight analyzers."""
from collections import Counter, deque
import json
from pathlib import Path
import re
import ssl
import subprocess
import sys
import urllib.request


def json_lines(path):
    rows = []
    if path.exists():
        for line in path.read_text().splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                pass
    return rows


def reassemble(shared):
    native = json_lines(shared / 'ssl-native.jsonl')
    process = json_lines(shared / 'process-trace.jsonl')
    pending = deque()
    events = list(process)
    buffers = {'WRITE/SEND': '', 'READ/RECV': ''}
    starts = {}
    errors = []

    def add(event, data):
        events.append({'source': 'http_parser', 'timestamp': event['timestamp_ns'],
                       'pid': event['pid'], 'comm': event['comm'], 'data': data})

    for event in native:
        direction = event.get('function')
        if direction not in buffers or not isinstance(event.get('data'), str):
            continue
        chunk = event['data']
        if re.match(r'^POST \S+ HTTP/1\.\d\r\n', chunk):
            if buffers['WRITE/SEND']:
                errors.append('incomplete_request_at_next_request')
                buffers['WRITE/SEND'] = ''
            if pending:
                errors.append('incomplete_response_at_next_request')
                pending.clear()
                buffers['READ/RECV'] = ''
        if not buffers[direction]:
            starts[direction] = event
        buffers[direction] += chunk
        raw = buffers[direction]
        if '\r\n\r\n' not in raw:
            continue
        header, body = raw.split('\r\n\r\n', 1)
        if direction == 'WRITE/SEND':
            length = re.search(r'(?im)^content-length:\s*(\d+)', header)
            if not length:
                errors.append('request_without_content_length')
                buffers[direction] = ''
                continue
            size = int(length.group(1))
            if len(body.encode()) < size:
                continue
            try:
                request = json.loads(body)
            except ValueError:
                errors.append('invalid_request_json')
                buffers[direction] = ''
                continue
            start = starts[direction]
            tid = start['tid']
            data = {'message_type': 'request', 'body': json.dumps(request), 'tid': tid,
                    'pid': start['pid'], 'comm': start['comm'],
                    'method': 'POST', 'path': header.splitlines()[0].split()[1]}
            add(start, data)
            pending.append((start, data))
            buffers[direction] = ''
        elif re.search(r'(?m)^data:\s*\[DONE\]\s*$', body):
            chunks = []
            for line in body.splitlines():
                if line.startswith('data:'):
                    try:
                        chunks.append(json.loads(line[5:].strip()))
                    except ValueError:
                        pass
            content, reasoning, calls, usage = [], [], {}, None
            for part in chunks:
                usage = part.get('usage') or usage
                for choice in part.get('choices') or []:
                    delta = choice.get('delta') or {}
                    if delta.get('content'):
                        content.append(delta['content'])
                    if delta.get('reasoning_content'):
                        reasoning.append(delta['reasoning_content'])
                    for call in delta.get('tool_calls') or []:
                        target = calls.setdefault(call.get('index', 0), {'id': '', 'type': 'function',
                            'function': {'name': '', 'arguments': ''}})
                        if call.get('id'):
                            target['id'] = call['id']
                        function = call.get('function') or {}
                        target['function']['name'] += function.get('name') or ''
                        target['function']['arguments'] += function.get('arguments') or ''
            if pending:
                request_event, request_data = pending.popleft()
                response = {'choices': [{'message': {'role': 'assistant', 'content': ''.join(content),
                    'reasoning_content': ''.join(reasoning), 'tool_calls': list(calls.values())}}], 'usage': usage}
                add(event, {'message_type': 'response', 'body': json.dumps(response),
                    'tid': request_data['tid'], 'pid': event['pid'], 'comm': event['comm'], 'status_code': 200})
            else:
                errors.append('response_without_captured_request')
            buffers[direction] = ''
    events.sort(key=lambda x: x['timestamp'])
    trace = shared / 'normalized-trace.jsonl'
    trace.write_text(''.join(json.dumps(e) + '\n' for e in events))
    facts = {'system_events': len(process), 'native_ssl_records': len(native),
             'truncated_ssl_records': sum(bool(e.get('truncated')) for e in native),
             'http_records': sum(e['source'] == 'http_parser' for e in events),
             'http_pairs': sum(e['source'] == 'http_parser' and e['data']['message_type'] == 'response' for e in events),
             'pending_requests': len(pending), 'unparsed_tail_bytes': {k: len(v.encode()) for k, v in buffers.items()},
             'parse_errors': dict(Counter(errors)), 'raw_ssl_bytes': (shared / 'ssl-native.jsonl').stat().st_size,
             'system_event_bytes': (shared / 'process-trace.jsonl').stat().st_size}
    (shared / 'capture-summary.json').write_text(json.dumps(facts, indent=2) + '\n')
    return trace, facts


def main():
    shared, external, gateway, case = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], sys.argv[4]
    trace, facts = reassemble(shared)
    print(json.dumps(facts), flush=True)
    if not facts['system_events'] or not facts['http_pairs']:
        raise RuntimeError('AgentSight did not capture both system events and LLM traffic')
    script = external / 'agentsight-paper/script'
    proc = subprocess.run(['python3', str(script / 'multi_signal_correlator.py'), str(trace),
                           '-o', str(shared / 'correlations.json')], capture_output=True, text=True)
    (shared / 'correlation-stdout.log').write_text(proc.stdout + proc.stderr)
    print('Original correlation script exit', proc.returncode, flush=True)
    sys.path.insert(0, str(script))
    from llm_semantic_analyzer import LLMSemanticAnalyzer

    class RealAnalyzer(LLMSemanticAnalyzer):
        def _generate_mock_response(self):
            raise RuntimeError('Mock responses disabled')

        def _query_openai(self, prompt):
            (shared / 'observer-prompt.txt').write_text(prompt)
            body = {'model': 'deepseek-v4.1-flash-1017-al', 'max_tokens': 4000,
                    'messages': [{'role': 'user', 'content': prompt}]}
            req = urllib.request.Request(gateway + '/observer/' + case + '/v1/chat/completions',
                data=json.dumps(body).encode(), headers={'Authorization': 'Bearer local-transport-token',
                                                        'Content-Type': 'application/json'})
            ctx = ssl.create_default_context(cafile=str(shared.parent.parent / 'gateway.crt'))
            with urllib.request.urlopen(req, context=ctx, timeout=180) as response:
                data = json.load(response)
            (shared / 'observer-response.json').write_text(json.dumps(data, indent=2) + '\n')
            return data['choices'][0]['message']['content']

    result = RealAnalyzer('openai', 'deepseek-v4.1-flash-1017-al').analyze_trace(
        str(trace), str(shared / 'observer-analysis.json'))
    print(result.summary, flush=True)


if __name__ == '__main__':
    main()
