import test from 'node:test';
import assert from 'node:assert/strict';
import { readEvents, errorMessage, request } from '../src/api.js';
import { language } from '../src/i18n.js';

test('quota errors preserve the server explanation and machine-readable details', async () => {
  const original = globalThis.fetch;
  const body = { error: 'فضای اختصاصی کافی نیست.', code: 'storage_quota_exceeded', used_bytes: 50000 };
  globalThis.fetch = async () => new Response(JSON.stringify(body), { status: 413 });
  try {
    await assert.rejects(request('/api/projects/test/upload'), error => {
      assert.equal(error.message, body.error);
      assert.equal(error.code, body.code);
      assert.equal(error.status, 413);
      assert.equal(error.details.used_bytes, 50000);
      return true;
    });
  } finally { globalThis.fetch = original; }
});

test('structured errors use UI language instead of technical traceback', () => {
  const body = { error: 'Traceback technical details', error_detail: { fa: 'لایهٔ معابر باید خطی باشد.', en: 'Roads must be lines.' } };
  language.value = 'fa';
  assert.equal(errorMessage(body), body.error_detail.fa);
  language.value = 'en';
  assert.equal(errorMessage(body), body.error_detail.en);
  assert.equal(errorMessage({ error: 'legacy error' }), 'legacy error');
  language.value = 'fa';
});

test('stream decoder handles split UTF-8, CRLF, and multi-line data', async () => {
  const source = 'event: step\r\ndata: {"text":"تهران"}\r\n\r\nevent: done\ndata: {"ok":\ndata: true}\n\n';
  const bytes = new TextEncoder().encode(source);
  const split = bytes.indexOf(0xd8) + 1;
  const chunks = [bytes.slice(0, split), bytes.slice(split, split + 5), bytes.slice(split + 5)];
  const response = new Response(new ReadableStream({
    pull(controller) { if (chunks.length) controller.enqueue(chunks.shift()); else controller.close(); },
  }));
  const seen = [];
  await readEvents(response, (event, data) => seen.push([event, data]));
  assert.deepEqual(seen, [['step', { text: 'تهران' }], ['done', { ok: true }]]);
});
