"""诊断探针（临时）：Python WSGI(Flask) 模式返回二进制，看字节是否被破坏。"""

from flask import Flask, Response

app = Flask(__name__)

PAYLOAD = bytes(range(256))


@app.route("/")
@app.route("/binprobe2")
def probe():
    return Response(PAYLOAD, mimetype="application/octet-stream")
