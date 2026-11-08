import { createProxyMiddleware, type Options } from "http-proxy-middleware";
import { protectProxyHeaders } from "./downloadProxy.ts";

const AUTH_PREFIX = "/api/parttime/fengshen/auth";

/** Match the one decoding step performed by the ASGI server for route lookup. */
export function isFengshenAuthProxyPath(pathname: string): boolean {
  try {
    const decoded = decodeURIComponent(pathname.split("?", 1)[0]);
    return decoded === AUTH_PREFIX || decoded.startsWith(AUTH_PREFIX + "/");
  } catch {
    // Malformed paths must never reach the generic proxy with a loopback Host.
    // Preserve the client's Host and let the backend reject the invalid route.
    return true;
  }
}

export function createFengshenAuthProxy(options: Options, secret?: string) {
  return createProxyMiddleware({
    pathFilter: isFengshenAuthProxyPath,
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
