import { createProxyMiddleware, type Options } from "http-proxy-middleware";
import type { ClientRequest, IncomingMessage } from "node:http";

const PREFIX = "/api/fengshen-downloads";

export function isDownloadProxyPath(pathname: string): boolean {
  try {
    const decoded = decodeURIComponent(pathname.split("?", 1)[0]);
    return decoded === PREFIX || decoded.startsWith(PREFIX + "/")
      || decoded === '/api/run' || decoded.startsWith('/api/parttime/')
      || decoded === '/api/workbench' || decoded.startsWith('/api/workbench/');
  } catch {
    // Preserve browser Host for malformed paths instead of trusting loopback.
    return true;
  }
}

const AISTUDIO_HOST_RE = /^ais-(?:dev|pre)-[a-z0-9-]+-\d+\.[a-z0-9-]+\.run\.app(?::\d+)?$/i;

export function protectProxyHeaders(proxyReq: ClientRequest, req: IncomingMessage, secret?: string) {
  for (const name of proxyReq.getHeaderNames()) {
    if (name === "forwarded" || name.startsWith("x-forwarded-") || name.startsWith("x-download-proxy-")
        || name === "x-download-client-address") {
      proxyReq.removeHeader(name);
    }
  }
  const rawHost = String(req.headers.host || "").trim();
  if (AISTUDIO_HOST_RE.test(rawHost)) {
    proxyReq.setHeader("host", "localhost:3000");
    const rawOrigin = String(req.headers.origin || "").trim();
    if (rawOrigin === `https://${rawHost}` || rawOrigin === `http://${rawHost}`) {
      proxyReq.setHeader("origin", "http://localhost:3000");
    }
  }
  if (secret) {
    proxyReq.setHeader("x-download-proxy-secret", secret);
    proxyReq.setHeader("x-download-client-address", req.socket.remoteAddress || "unknown");
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
