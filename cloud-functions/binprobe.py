"""诊断探针（临时）：Python Handler 模式返回二进制，看字节是否被破坏。

请求 /binprobe 应返回 256 字节的 0x00..0xFF 序列。
"""

from http.server import BaseHTTPRequestHandler

PAYLOAD = bytes(range(256))


class handler(BaseHTTPRequestHandler):

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(PAYLOAD)))
        self.end_headers()
        self.wfile.write(PAYLOAD)
