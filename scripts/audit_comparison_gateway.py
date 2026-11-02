"""TLS transport and usage accounting for native Pi and independent auditors."""
import ctypes
import http.server
import json
import pathlib
import ssl
import sys
import threading
import time
import urllib.error
import urllib.request


def serve(config, root):
    ctypes.CDLL(None).prctl(15, b'pi-audit-gw', 0, 0, 0)
    lock = threading.Lock()
    activity = {'inflight': 0}

    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path != '/status':
                self.send_error(404)
                return
            with lock:
                raw = json.dumps(activity).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_POST(self):
            parts = self.path.strip('/').split('/')
            role, case = parts[:2]
            suffix = '/'.join(parts[2:])
            payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            requested = payload.get('model')
            payload['model'] = config['model']
            system = '\n'.join(str(m.get('content', '')) for m in payload.get('messages', []) if m.get('role') == 'system')
            if role == 'sentinel':
                role = 'sentinel-context' if 'summarizing the context' in system else 'sentinel-security'
            started = time.time()
            usage, finish, error, status = None, None, None, 200
            request_bytes = json.dumps(payload).encode()
            self.close_connection = True
            sent = False
            with lock:
                activity['inflight'] += 1
            try:
                req = urllib.request.Request(config['base_url'].rstrip('/') + '/' + suffix,
                    data=request_bytes, headers={'Authorization': 'Bearer ' + config['key'], 'Content-Type': 'application/json'})
                with urllib.request.urlopen(req, timeout=180) as response:
                    content_type = response.headers.get('Content-Type', '')
                    if 'event-stream' in content_type:
                        self.send_response(response.status)
                        self.send_header('Content-Type', content_type)
                        self.send_header('Connection', 'close')
                        self.end_headers()
                        sent = True
                        for line in response:
                            if line.startswith(b'data:'):
                                try:
                                    event = json.loads(line[5:].strip())
                                    usage = event.get('usage') or usage
                                    choices = event.get('choices') or []
                                    if choices and choices[0].get('finish_reason'):
                                        finish = choices[0]['finish_reason']
                                except (ValueError, AttributeError):
                                    pass
                            self.wfile.write(line)
                            self.wfile.flush()
                    else:
                        raw = response.read()
                        event = json.loads(raw)
                        usage = event.get('usage')
                        if not event.get('choices'):
                            raise RuntimeError('Upstream returned no choices: ' + str(event.get('code', '')))
                        finish = event['choices'][0].get('finish_reason')
                        self.send_response(response.status)
                        self.send_header('Content-Type', 'application/json')
                        self.send_header('Content-Length', str(len(raw)))
                        self.end_headers()
                        sent = True
                        self.wfile.write(raw)
            except Exception as exc:
                status = 502
                error = str(exc).replace(config['key'], '[REDACTED]')
                if not sent:
                    try:
                        raw = json.dumps({'error': {'message': error}}).encode()
                        self.send_response(502)
                        self.send_header('Content-Type', 'application/json')
                        self.send_header('Content-Length', str(len(raw)))
                        self.end_headers()
                        self.wfile.write(raw)
                    except (BrokenPipeError, ConnectionResetError):
                        pass
            finally:
                row = {'case': case, 'role': role, 'requested_model': requested,
                       'status': status, 'usage': usage, 'finish_reason': finish,
                       'error': error, 'request_bytes': len(request_bytes),
                       'started': started, 'seconds': time.time() - started}
                with lock:
                    with (root / 'gateway-requests.jsonl').open('a') as f:
                        f.write(json.dumps(row) + '\n')
                    activity['inflight'] -= 1

    server = http.server.ThreadingHTTPServer(('0.0.0.0', config.get('port', 24443)), Handler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(root / 'gateway.crt', root / 'gateway.key')
    server.socket = ctx.wrap_socket(server.socket, server_side=True)
    print('TLS gateway ready; project credential kept in process memory', flush=True)
    server.serve_forever()


if __name__ == '__main__':
    serve(json.load(sys.stdin), pathlib.Path(sys.argv[1]))
