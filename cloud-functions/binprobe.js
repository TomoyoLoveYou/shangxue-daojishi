// 诊断探针（临时）：Node.js 云函数返回二进制，看字节是否被破坏。

export default function onRequest() {
  const payload = new Uint8Array(256);
  for (let i = 0; i < 256; i += 1) payload[i] = i;
  return new Response(payload, {
    headers: {
      "Content-Type": "application/octet-stream",
      "Content-Length": String(payload.byteLength),
    },
  });
}
