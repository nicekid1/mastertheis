import { language } from './i18n.js';

export function errorMessage(body, fallback = 'Request failed') {
  return body?.error_detail?.[language.value] || body?.error || body?.detail || fallback;
}

export async function request(url, options = {}) {
  const headers = new Headers(options.headers);
  if (url.startsWith('/api/')) headers.set('X-GISclaw', '1');
  const response = await fetch(url, { ...options, headers });
  if (!response.ok) {
    if (response.status === 401 && url !== '/api/auth/login' && typeof window !== 'undefined') window.dispatchEvent(new Event('auth-expired'));
    let message = `Request failed (${response.status})`;
    let body;
    try { body = await response.json(); message = errorMessage(body, message); } catch {}
    const error = new Error(message);
    error.status = response.status;
    error.code = body?.code;
    error.details = body;
    throw error;
  }
  return response;
}

export async function api(url, body, method = body === undefined ? 'GET' : 'POST') {
  const response = await request(url, {
    method,
    ...(body === undefined ? {} : { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
  });
  const result = await response.json();
  if (result.error || result.ok === false) throw new Error(errorMessage(result));
  return result;
}

// Streaming decoder accepts CRLF, multi-line data and UTF-8 split across chunks.
// Cancellation only detaches the view; the server owns the analysis lifetime.
export async function readEvents(response, receive, signal) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  const cancel = () => { reader.cancel().catch(() => {}); };
  signal?.addEventListener('abort', cancel, { once: true });
  const dispatch = block => {
    let event = 'message';
    const data = [];
    for (const line of block.split(/\r?\n/)) {
      if (line.startsWith('event:')) event = line.slice(6).trim();
      if (line.startsWith('data:')) data.push(line.slice(5).replace(/^ /, ''));
    }
    if (!data.length) return;
    let value;
    try { value = JSON.parse(data.join('\n')); } catch { return; }
    receive(event, value);
  };
  try {
    while (!signal?.aborted) {
      const { done, value } = await reader.read();
      buffer += done ? decoder.decode() : decoder.decode(value, { stream: true });
      const frames = buffer.split(/\r?\n\r?\n/);
      buffer = frames.pop();
      for (const frame of frames) { if (!signal?.aborted) dispatch(frame); }
      if (done) { if (buffer.trim() && !signal?.aborted) dispatch(buffer); break; }
    }
  } finally {
    signal?.removeEventListener('abort', cancel);
    reader.releaseLock();
  }
}
