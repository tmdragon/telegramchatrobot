// api.js：Fetch 包装，统一抛 ApiError。
// ApiError 形状必须与服务端 JSON 错误体一致：
//   { status: HTTP_code, message: '...', detail: '...' }

export class ApiError extends Error {
  constructor(status, message, detail) {
    super(message || `HTTP ${status}`);
    this.status = status;
    this.message = message || `HTTP ${status}`;
    this.detail = detail;
  }
}

async function _unwrap(res) {
  if (res.ok) {
    if (res.status === 204) return null;
    const ct = res.headers.get("content-type") || "";
    return ct.includes("json") ? await res.json() : await res.text();
  }
  let body = null;
  try { body = await res.json(); } catch (_) { /* not JSON */ }
  const detail = (body && (body.detail || body.message)) || res.statusText;
  throw new ApiError(res.status, `HTTP ${res.status}`, detail);
}

export async function getJson(url) {
  const res = await fetch(url, { headers: { "Accept": "application/json" } });
  return _unwrap(res);
}

export async function postJson(url, body = {}) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", "Accept": "application/json" },
    body: JSON.stringify(body),
  });
  return _unwrap(res);
}

export async function putJson(url, body = {}) {
  const res = await fetch(url, {
    method: "PUT",
    headers: { "Content-Type": "application/json", "Accept": "application/json" },
    body: JSON.stringify(body),
  });
  return _unwrap(res);
}

export async function delJson(url) {
  const res = await fetch(url, { method: "DELETE", headers: { "Accept": "application/json" } });
  return _unwrap(res);
}