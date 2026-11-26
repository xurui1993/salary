import fs from "node:fs";
import path from "node:path";
import type { Request, Response, NextFunction } from "express";
import { isDownloadProxyPath } from "./downloadProxy.ts";
import { isFengshenAuthProxyPath } from "./fengshenAuthProxy.ts";

export interface ResolvedGatewaySession {
  authenticated: boolean;
  initialized: boolean;
  enforce: boolean;
  effective_workspace: string;
  user: {
    id: string;
    username: string;
    display_name: string;
    role: "admin" | "member";
    workspace_id: string;
    effective_workspace: string;
    inspecting: boolean;
    permissions: Record<string, boolean>;
  } | null;
}

const CACHE_TTL_MS = 1200;
const sessionCache = new Map<string, { at: number; value: ResolvedGatewaySession }>();

export function clearGatewaySessionCache(): void {
  sessionCache.clear();
}

export async function resolveCookieSession(
  cookieHeader: string | undefined,
  inspectHeader: string | undefined,
  backendUrl: string,
  proxySecret: string,
  clientAddress?: string,
): Promise<ResolvedGatewaySession | null> {
  const normalizedAddr = (clientAddress || "").trim();
  const key = `${normalizedAddr || "unknown"}::${cookieHeader || ""}::${inspectHeader || ""}`;
  const now = Date.now();
  const hit = sessionCache.get(key);
  if (hit && now - hit.at < CACHE_TTL_MS) {
    return hit.value;
  }
  try {
    const headers: Record<string, string> = {
      "x-download-proxy-secret": proxySecret,
    };
    if (normalizedAddr) headers["x-download-client-address"] = normalizedAddr;
    if (cookieHeader) headers.cookie = cookieHeader;
    if (inspectHeader) headers["x-inspect-workspace"] = inspectHeader;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 3500);
    try {
      const res = await fetch(`${backendUrl}/api/auth/internal/resolve`, {
        headers,
        signal: controller.signal,
      });
      if (!res.ok) return null;
      const data = (await res.json()) as ResolvedGatewaySession;
      if (sessionCache.size > 200) sessionCache.clear();
      sessionCache.set(key, { at: now, value: data });
      return data;
    } finally {
      clearTimeout(timer);
    }
  } catch {
    return null;
  }
}

export function workspaceConfigPath(root: string, wid: string): string {
  if (wid && wid !== "download_shared" && wid.startsWith("ws_")) {
    const wsDataDir = path.resolve(root, "workspaces", wid, "data");
    fs.mkdirSync(wsDataDir, { recursive: true });
    const targetCfg = path.join(wsDataDir, "config.json");
    if (!fs.existsSync(targetCfg)) {
      const templateCfg = path.resolve(root, "data", "config.json");
      if (fs.existsSync(templateCfg)) {
        try {
          fs.copyFileSync(templateCfg, targetCfg);
        } catch {
          fs.writeFileSync(targetCfg, "[]", "utf-8");
        }
      } else {
        fs.writeFileSync(targetCfg, "[]", "utf-8");
      }
    }
    return targetCfg;
  }
  return path.resolve(root, "data", "config.json");
}

function isWithin(parentDir: string, targetPath: string): boolean {
  const rel = path.relative(path.resolve(parentDir), path.resolve(targetPath));
  return rel === "" || (!rel.startsWith(".." + path.sep) && rel !== ".." && !path.isAbsolute(rel));
}

export function isWorkspacePathPermitted(
  root: string,
  wid: string,
  targetPath: string,
  opts: { write?: boolean } = {},
): boolean {
  const resolved = path.resolve(root, targetPath);
  if (!wid || wid === "download_shared" || !wid.startsWith("ws_")) {
    // Primary admin workspace cannot accidentally overwrite another colleague's isolated ws_ folder via legacy routes
    return true;
  }
  const allowedWrite = [
    path.resolve(root, "workspaces", wid),
    path.resolve(root, "uploads", wid),
    path.resolve(root, "outputs", wid),
    path.resolve(root, "outputs", "workspaces", wid),
  ];
  if (allowedWrite.some(dir => isWithin(dir, resolved))) {
    return true;
  }
  if (!opts.write && isWithin(path.resolve(root, "system_templates"), resolved)) {
    return true;
  }
  return false;
}

export function createGatewaySessionMiddleware(backendUrl: string, proxySecret: string) {
  return async (req: Request, res: Response, next: NextFunction) => {
    if (!req.path.startsWith("/api/")) {
      next();
      return;
    }
    if (req.path.startsWith("/api/auth/") || req.path.startsWith("/api/admin/")) {
      clearGatewaySessionCache();
    }
    // Routes proxied directly to FastAPI enforce session & permissions natively in Python
    if (isDownloadProxyPath(req.path) || isFengshenAuthProxyPath(req.path)) {
      next();
      return;
    }
    const resolved = await resolveCookieSession(
      req.headers.cookie,
      req.header("x-inspect-workspace"),
      backendUrl,
      proxySecret,
      req.socket?.remoteAddress,
    );
    if (!resolved) {
      res.status(503).json({ success: false, error: "核心认证服务正在启动中，请稍后重试" });
      return;
    }
    if (resolved.enforce && !resolved.authenticated) {
      res.status(401).json({ success: false, error: "请先登录工作空间账号" });
      return;
    }
    (req as any).resolvedWorkspace = resolved.effective_workspace;
    (req as any).authUser = resolved.user;
    req.headers["x-workspace-id"] = encodeURIComponent(resolved.effective_workspace);
    next();
  };
}
