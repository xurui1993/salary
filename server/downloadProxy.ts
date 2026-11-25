import { createProxyMiddleware, type Options } from "http-proxy-middleware";
import type { ClientRequest, IncomingMessage } from "node:http";

const PREFIX = "/api/fengshen-downloads";

export function isDownloadProxyPath(pathname: string): boolean {
  try {
    const decoded = decodeURIComponent(pathname.split("?", 1)[0]);
    return decoded === PREFIX || decoded.startsWith(PREFIX + "/")
      || decoded === '/api/run' || decoded.startsWith('/api/parttime/')
      || decoded === '/api/workbench' || decoded.startsWith('/api/workbench/')
      || decoded === '/api/auth' || decoded.startsWith('/api/auth/')
      || decoded === '/api/admin' || decoded.startsWith('/api/admin/');
  } catch {
    // Preserve browser Host for malformed paths instead of trusting loopback.
    return true;
  }
}

const AISTUDIO_HOST_RE = /^ais-(?:dev|pre)-[a-z0-9-]+-\d+\.[a-z0-9-]+\.run\.app(?::\d+)?$/i;

function isLoopbackAddress(rawAddr: string | undefined): boolean {
  const addr = String(rawAddr || "").trim().toLowerCase();
  return addr === "127.0.0.1" || addr === "::1" || addr === "::ffff:127.0.0.1";
}

function isAllowedPreviewHost(host: string): boolean {
  if (!host) return false;
  if (AISTUDIO_HOST_RE.test(host)) return true;
  const configuredAllowed = String(process.env.NG_ALLOWED_HOSTS || "")
    .split(",")
    .map((item) => item.trim().toLowerCase())
    .filter(Boolean);
  if (configuredAllowed.includes(host.toLowerCase())) return true;
  const appUrl = String(process.env.APP_URL || "").trim();
  if (appUrl) {
    try {
      const parsed = new URL(appUrl);
      if (parsed.host.toLowerCase() === host.toLowerCase()) return true;
    } catch {
      // ignore malformed APP_URL
    }
  }
  return false;
}

export function resolveAiStudioPreviewHost(req: IncomingMessage): string | null {
  const rawHost = String(req.headers.host || "").trim();
  if (isAllowedPreviewHost(rawHost)) {
    return rawHost;
  }
  // Behind AI Studio's local Nginx proxy, Nginx rewrites Host to localhost:3000
  // and forwards the external preview host via X-Forwarded-Host from loopback.
  if (isLoopbackAddress(req.socket?.remoteAddress)) {
    const forwardedHost = String(req.headers["x-forwarded-host"] || "")
      .split(",")[0]
      .trim();
    if (isAllowedPreviewHost(forwardedHost)) {
      return forwardedHost;
    }
  }
  return null;
}

export function protectProxyHeaders(proxyReq: ClientRequest, req: IncomingMessage, secret?: string) {
  for (const name of proxyReq.getHeaderNames()) {
    if (name === "forwarded" || name.startsWith("x-forwarded-") || name.startsWith("x-download-proxy-")
        || name === "x-download-client-address") {
      proxyReq.removeHeader(name);
    }
  }
  const previewHost = resolveAiStudioPreviewHost(req);
  const isAiStudioPreview = Boolean(previewHost);
  if (previewHost) {
    proxyReq.setHeader("host", "localhost:3000");
    const rawOrigin = String(req.headers.origin || "").trim();
    if (rawOrigin === `https://${previewHost}` || rawOrigin === `http://${previewHost}`) {
      proxyReq.setHeader("origin", "http://localhost:3000");
    }
  }
  if (secret) {
    proxyReq.setHeader("x-download-proxy-secret", secret);
    proxyReq.setHeader("x-download-client-address", req.socket?.remoteAddress || "unknown");
    if (isAiStudioPreview) {
      proxyReq.setHeader("x-download-proxy-https", "1");
    }
  }
}

export function createDownloadProxy(options: Options, secret: string) {
  return createProxyMiddleware({
    pathFilter: isDownloadProxyPath,
    ...options,
    changeOrigin: false,
    on: {
      ...(options as any).on,
      proxyReq: (proxyReq: any, req: any, res: any, proxyOptions: any) => {
        (options as any).on?.proxyReq?.(proxyReq, req, res, proxyOptions);
        protectProxyHeaders(proxyReq, req, secret);
      },
      proxyReqWs: (proxyReq: any, req: any, socket: any, proxyOptions: any, head: any) => {
        (options as any).on?.proxyReqWs?.(proxyReq, req, socket, proxyOptions, head);
        protectProxyHeaders(proxyReq, req, secret);
      },
    },
  });
}
