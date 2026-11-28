import assert from 'node:assert/strict';
import test from 'node:test';
import {
  AUTH_PREFLIGHT_CANCEL_EVENT,
  AUTH_PREFLIGHT_EVENT,
  AUTH_PREFLIGHT_READY_EVENT,
  fetchWithPreflight,
} from '../src/lib/authPreflight';

function withMockWindow<T>(fn: (win: EventTarget) => Promise<T>): Promise<T> {
  const prev = (globalThis as any).window;
  const win = new EventTarget();
  (globalThis as any).window = win;
  return fn(win).finally(() => {
    if (prev === undefined) {
      delete (globalThis as any).window;
    } else {
      (globalThis as any).window = prev;
    }
  });
}

test('fetchWithPreflight unwraps FastAPI 409 detail and dispatches only unready platforms', async () => {
  await withMockWindow(async win => {
    const dispatched: any[] = [];
    const onPreflight = (event: Event) => {
      dispatched.push((event as CustomEvent).detail);
      queueMicrotask(() => {
        win.dispatchEvent(new Event(AUTH_PREFLIGHT_READY_EVENT));
      });
    };
    win.addEventListener(AUTH_PREFLIGHT_EVENT, onPreflight);

    let calls = 0;
    try {
      const response = await fetchWithPreflight(
        '/api/fengshen-downloads/runs',
        {
          method: 'POST',
          signal: AbortSignal.abort(new Error('expired-initial-timeout')),
          timeoutMs: 30000,
        },
        async (_url, options) => {
          calls += 1;
          if (calls === 1) {
            return new Response(
              JSON.stringify({
                detail: {
                  code: 'AUTH_PREFLIGHT_REQUIRED',
                  message: '请先完成涉及平台的登录认证，认证齐备后任务将自动继续',
                  platforms: [
                    { source: 'baize', label: '商翼', state: 'ready', ready: true, message: 'ok' },
                    { source: 'benlai', label: '本来人力', state: 'signed_out', ready: false, message: '未登录' },
                    { source: 'fengshen', label: '风神', state: 'ready', ready: true, message: 'ok' },
                  ],
                },
              }),
              { status: 409, headers: { 'Content-Type': 'application/json' } },
            );
          }
          assert.equal(options?.signal?.aborted, false, 'retry must receive a fresh non-aborted signal');
          return new Response(JSON.stringify({ run: { id: 'run_1' } }), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          });
        },
      );

      assert.equal(calls, 2);
      assert.equal(response.status, 200);
      assert.equal(dispatched.length, 1);
      assert.deepEqual(
        dispatched[0].map((item: any) => item.source),
        ['benlai'],
      );
    } finally {
      win.removeEventListener(AUTH_PREFLIGHT_EVENT, onPreflight);
    }
  });
});

test('fetchWithPreflight rejects with backend message when user cancels preflight', async () => {
  await withMockWindow(async win => {
    const onPreflight = () => {
      queueMicrotask(() => {
        win.dispatchEvent(new Event(AUTH_PREFLIGHT_CANCEL_EVENT));
      });
    };
    win.addEventListener(AUTH_PREFLIGHT_EVENT, onPreflight);

    try {
      await assert.rejects(
        () =>
          fetchWithPreflight(
            '/api/fengshen-downloads/runs',
            { method: 'POST' },
            async () =>
              new Response(
                JSON.stringify({
                  detail: {
                    code: 'AUTH_PREFLIGHT_REQUIRED',
                    message: '请先完成本来人力认证',
                    platforms: [{ source: 'benlai', label: '本来人力', ready: false }],
                  },
                }),
                { status: 409, headers: { 'Content-Type': 'application/json' } },
              ),
          ),
        /请先完成本来人力认证/,
      );
    } finally {
      win.removeEventListener(AUTH_PREFLIGHT_EVENT, onPreflight);
    }
  });
});

test('fetchWithPreflight passes through ordinary 409 business conflict responses', async () => {
  const response = await fetchWithPreflight(
    '/api/fengshen-downloads/runs',
    { method: 'POST' },
    async () =>
      new Response(JSON.stringify({ detail: '存在重复任务，请确认' }), {
        status: 409,
        headers: { 'Content-Type': 'application/json' },
      }),
  );
  assert.equal(response.status, 409);
  const data = await response.json();
  assert.equal(data.detail, '存在重复任务，请确认');
});
