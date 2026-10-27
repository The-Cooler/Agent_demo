// 后端接口封装：统一处理 JSON、错误消息与 204 响应。
const API = "/api/v1";

async function api(path, options = {}) {
  const res = await fetch(API + path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch (e) {
      // 响应体不是 JSON 时沿用 statusText
    }
    throw new Error(detail);
  }
  if (res.status === 204) return null;
  return res.json();
}
