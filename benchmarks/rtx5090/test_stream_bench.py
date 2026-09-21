"""Exercise the published streaming harness without model weights or a GPU."""
import json
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class StreamHarnessTests(unittest.TestCase):
    def run_client(self, complete):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                assert request['model'] == 'test-model'
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.end_headers()

                def send(payload):
                    self.wfile.write(('data: ' + json.dumps(payload) + '\n\n').encode())
                    self.wfile.flush()

                send({'choices': [{'delta': {'role': 'assistant'}}]})
                time.sleep(0.04)
                for key, value in [('reasoning_content', 'think'), ('content', 'answer'), ('content', '.')]:
                    send({'choices': [{'delta': {key: value}}]})
                    time.sleep(0.015)
                if complete:
                    send({'choices': [{'delta': {}, 'finish_reason': 'length'}],
                          'usage': {'prompt_tokens': 7, 'completion_tokens': 3, 'total_tokens': 10}})
                    self.wfile.write(b'data: [DONE]\n\n')
                    self.wfile.flush()

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as temp:
                result = subprocess.run([
                    sys.executable, str(Path(__file__).with_name('stream_bench.py')),
                    '--base', f'http://127.0.0.1:{server.server_port}',
                    '--label', 'mock', '--model', 'test-model', '--lengths', '0',
                    '--tokens', '3', '--output', temp,
                ], capture_output=True, text=True)
                path = Path(temp) / 'mock-0-0.json'
                return result, json.loads(path.read_text()) if path.exists() else None
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_role_event_is_not_ttft_and_reasoning_counts(self):
        result, report = self.run_client(True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(report['nonempty_chunks'], 3)
        self.assertGreater(report['ttft_s'] - report['first_event_s'], 0.02)
        self.assertEqual(report['usage']['completion_tokens'], 3)
        self.assertAlmostEqual(report['decode_tps'], 2 / (report['last_token_s'] - report['ttft_s']))

    def test_disconnected_stream_is_not_reported_as_a_benchmark(self):
        result, report = self.run_client(False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Incomplete stream', result.stderr)
        self.assertIsNone(report)


if __name__ == '__main__':
    unittest.main()
