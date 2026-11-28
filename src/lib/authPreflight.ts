export const AUTH_PREFLIGHT_EVENT = 'workbench:auth-preflight';
export const AUTH_PREFLIGHT_READY_EVENT = 'workbench:auth-preflight-ready';
export const AUTH_PREFLIGHT_CANCEL_EVENT = 'workbench:auth-preflight-cancel';

export interface AuthPreflightPlatform {
  source: string;
  label?: string;
  state?: string;
  ready?: boolean;
  message?: string;
}

export type PreflightRequestInit = RequestInit & {
  timeoutMs?: number;
};

const fallbackEventTarget = new EventTarget();

function getEventTarget(): EventTarget {
  if (typeof window !== 'undefined' && typeof window.addEventListener === 'function') {
    return window;
  }
  return fallbackEventTarget;
}

function waitForPreflight(message?: string): Promise<void> {
  const target = getEventTarget();
  return new Promise<void>((resolve, reject) => {
    const cleanup = () => {
      target.removeEventListener(AUTH_PREFLIGHT_READY_EVENT, onReady);
      target.removeEventListener(AUTH_PREFLIGHT_CANCEL_EVENT, onCancel);
      clearTimeout(timer);
    };
    const onReady = () => {
      cleanup();
      resolve();
    };
    const onCancel = () => {
      cleanup();
      reject(
        new Error(
          message || '认证未完成，本次任务未创建；请完成平台认证后重新发起',
        ),
      );
    };
    const timer = setTimeout(onCancel, 10 * 60 * 1000);
    target.addEventListener(AUTH_PREFLIGHT_READY_EVENT, onReady);
    target.addEventListener(AUTH_PREFLIGHT_CANCEL_EVENT, onCancel);
  });
}

function unwrapPreflightDetail(body: unknown): Record<string, unknown> | null {
  if (!body || typeof body !== 'object') return null;
  const record = body as Record<string, unknown>;
  if (
    record.detail &&
    typeof record.detail === 'object' &&
    !Array.isArray(record.detail)
  ) {
    return record.detail as Record<string, unknown>;
  }
  return record;
}

function buildRetryInit(init?: PreflightRequestInit): RequestInit | undefined {
  if (!init) return undefined;
  const { timeoutMs, ...rest } = init;
  if (typeof timeoutMs === 'number' && timeoutMs > 0) {
    return { ...rest, signal: AbortSignal.timeout(timeoutMs) };
  }
  return init;
}

export async function fetchWithPreflight(
  url: RequestInfo | URL,
  init?: PreflightRequestInit,
  doFetch: (
    requestUrl: RequestInfo | URL,
    requestOptions?: RequestInit,
  ) => Promise<Response> = fetch,
): Promise<Response> {
  const initialInit =
    init && 'timeoutMs' in init
      ? (() => {
          const { timeoutMs, ...rest } = init;
          return {
            ...rest,
            signal:
              rest.signal ||
              (typeof timeoutMs === 'number' && timeoutMs > 0
                ? AbortSignal.timeout(timeoutMs)
                : undefined),
          };
        })()
      : init;

  const response = await doFetch(url, initialInit);
  if (response.status !== 409) return response;

  let rawBody: unknown;
  try {
    rawBody = await response.clone().json();
  } catch {
    return response;
  }

  const detail = unwrapPreflightDetail(rawBody);
  if (detail?.code !== 'AUTH_PREFLIGHT_REQUIRED') return response;

  const platforms = Array.isArray(detail.platforms)
    ? (detail.platforms as AuthPreflightPlatform[])
    : [];
  const unready = platforms.filter(item => item && item.ready === false);
  const eventItems = unready.length > 0 ? unready : platforms;

  getEventTarget().dispatchEvent(
    new CustomEvent(AUTH_PREFLIGHT_EVENT, { detail: eventItems }),
  );
  await waitForPreflight(
    typeof detail.message === 'string' ? detail.message : undefined,
  );
  return doFetch(url, buildRetryInit(init));
}
