import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'vite';
import { createSSRApp, h, provide } from 'vue';
import { renderToString } from 'vue/server-renderer';

// Exercise the real workspace request handler and ChatPanel template together.
// This is a component/HTTP-contract test, not a visual browser test.
test('GIS responses and provider errors appear in the chat panel, not a modal', async t => {
  const vite = await createServer({ server: { middlewareMode: true, watch: null, ws: false } });
  const originalFetch = globalThis.fetch;
  const { useWorkspace, workspaceKey } = await vite.ssrLoadModule('/src/workspace.js');
  const { currentUser } = await vite.ssrLoadModule('/src/auth.js');
  const { useFeedback, dismissToast } = await vite.ssrLoadModule('/src/feedback.js');
  const { default: ChatPanel } = await vite.ssrLoadModule('/src/components/ChatPanel.vue');
  try {
    for (const scenario of [
      { name: 'success', status: 200, body: { success: true, answer: 'پاسخ تحلیل آزمایشی', outputs: ['analysis-test/buffer.geojson'], usage: {}, code: 'print(2)', steps: [{ action: 'execute', code: 'print(2)', observation: '2', success: true }] } },
      { name: 'greeting without files', status: 200, body: { success: true, answer: 'سلام! چه تحلیل مکانی نیاز دارید؟', outputs: [], usage: {} } },
      { name: 'provider failure', status: 502, body: { error: 'اتصال مدل ناموفق بود. شناسهٔ پیگیری: test502', code: 'model_call_failed', steps: [{ action: 'execute', code: 'print(2)', observation: '2', success: true }] } },
      { name: 'timeout', status: 504, body: { error: 'مدل در زمان مجاز پاسخ نداد. شناسهٔ پیگیری: test504', code: 'model_timeout' } },
    ]) await t.test(scenario.name, async () => {
      let workspace;
      currentUser.value = { role: 'user', chat_enabled: false, analysis_enabled: true, isolated_analysis_enabled: true };
      const app = createSSRApp({ setup() {
        workspace = useWorkspace();
        provide(workspaceKey, workspace);
        return () => h(ChatPanel);
      } });
      await renderToString(app);
      Object.assign(workspace.state, { project: { id: 'test', name: 'Test' }, model: 'kimi-3', prompt: 'نام لایه‌ها را بگو' });
      workspace.state.tree.data = ['points.geojson'];
      let sent;
      globalThis.fetch = async (url, options) => {
        let body;
        let status = 200;
        if (url.endsWith('/analysis')) {
          sent = JSON.parse(options.body);
          body = scenario.body;
          status = scenario.status;
        } else if (url.endsWith('/tree')) body = { data: ['points.geojson'], outputs: [], documents: [], records: [], runs: [] };
        else if (url === '/api/projects') body = [{ id: 'test', name: 'Test' }];
        else if (url === '/api/run/active') body = { active: null };
        else throw new Error('Unexpected request: ' + url);
        return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
      };
      await workspace.runAnalysis();
      assert.equal(sent.model, 'kimi-3');
      assert.equal(workspace.state.running, false);
      assert.equal(workspace.state.tab, 'code');
      assert.equal(workspace.state.status, scenario.status === 200 ? 'Done' : 'Failed');
      if (scenario.body.steps?.length) {
        assert.equal(workspace.state.code, 'print(2)');
        assert.ok(workspace.state.stdout.some(item => item.text.includes('2')));
      }
      if (scenario.status !== 200) assert.ok(workspace.state.stdout.some(item => !item.ok && item.text === scenario.body.error));
      const text = scenario.body.answer || scenario.body.error;
      assert.ok(workspace.state.messages.some(m => m.text === text));
      const rendered = await renderToString(createSSRApp({ setup() {
        provide(workspaceKey, workspace);
        return () => h(ChatPanel);
      } }));
      assert.ok(rendered.includes(text));
      assert.equal(useFeedback().dialog, null);
      if (scenario.body.outputs?.length) assert.ok(rendered.includes('analysis-test/buffer.geojson'));
      if (scenario.status !== 200) assert.ok(useFeedback().toasts.some(item => item.text === text));
      for (const toast of [...useFeedback().toasts]) dismissToast(toast.id);
    });
  } finally {
    globalThis.fetch = originalFetch;
    currentUser.value = null;
    await vite.close();
  }
});
