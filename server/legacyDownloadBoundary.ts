import fs from "node:fs";
import path from "node:path";
import type { Request, Response, NextFunction } from "express";
import { isDownloadProxyPath } from "./downloadProxy.ts";
import { isFengshenAuthProxyPath } from "./fengshenAuthProxy.ts";

const PATH_KEYS = /^(path|.*path|.*dir|.*directory|paths)$/i;
const LIST_PATHS = new Set(["/api/files"]);
const READ_PATHS = new Set(["/api/files", "/api/files_tree", "/api/config_excel_data", "/api/dialog/smart_source",
  "/api/open/config", "/api/open/explorer", "/api/parttime/fengshen/plan", "/api/rider_sources/plan"]);

/** Resolve existing ancestors too, so aliases cannot bypass the directory boundary. */
function canonical(value: string): string {
  let cursor = path.resolve(value);
  const remainder: string[] = [];
  while (!fs.existsSync(cursor)) {
    const parent = path.dirname(cursor);
    if (parent === cursor) break;
    remainder.unshift(path.basename(cursor));
    cursor = parent;
  }
  let resolved = path.join(fs.realpathSync(cursor), ...remainder);
  if (process.platform === "win32") resolved = resolved.toLowerCase();
  return resolved;
}

function contains(root: string, target: string): boolean {
  const relative = path.relative(root, target);
  return relative === "" || (!relative.startsWith(".." + path.sep) && relative !== ".." && !path.isAbsolute(relative));
}

export function createLegacyBoundary(root = process.cwd(), extraRoots: string[] = []) {
  const project = canonical(root);
  const business = ["data", "uploads", "outputs", "system_templates"].map(name => canonical(path.join(root, name)));
  const protectedRoots = () => {
    let historic: string[] = [];
    try {
      const values = JSON.parse(fs.readFileSync(path.join(root, "backend", ".local_downloads", "protected_roots.json"), "utf8"));
      if (!Array.isArray(values.roots) || values.roots.some((value: unknown) => typeof value !== "string" || !path.isAbsolute(value))) {
        throw new Error("Invalid download directory registry");
      }
      historic = values.roots;
    } catch {
      // Python writes this trusted registry before serving requests. Missing or
      // corrupt state must never make an old external archive public.
      throw new Error("Download directory registry is not ready");
    }
    return [path.join(root, "backend", ".local_downloads"), path.join(root, "backend", ".local_auth"),
      path.join(root, ".local_auth"), path.join(root, "outputs", "fengshen_downloads"),
      ...(process.env.FENGSHEN_DOWNLOAD_ROOT ? [process.env.FENGSHEN_DOWNLOAD_ROOT] : []), ...extraRoots, ...historic].map(canonical);
  };
  const allowedPath = (value: string, { write = false, recursive = false } = {}) => {
    try {
      const target = canonical(path.resolve(root, value));
      if (protectedRoots().some(folder => contains(folder, target) || (recursive && contains(target, folder)))) return false;
      // Legacy file upload must not overwrite executable code, dependencies or runtime configuration.
      if (write && contains(project, target) && !business.some(folder => contains(folder, target))) return false;
      return true;
    } catch { return false; }
  };
  const bodyAllowed = (body: unknown, route: string) => {
    const visit = (value: unknown, key = ""): boolean => {
      if (typeof value === "string" && PATH_KEYS.test(key) && value) {
        return allowedPath(value, { write: !READ_PATHS.has(route), recursive: !LIST_PATHS.has(route) && key.toLowerCase() !== "basepath" });
      }
      if (Array.isArray(value)) return value.every(item => visit(item, key));
      if (value && typeof value === "object") return Object.entries(value).every(([name, child]) => visit(child, name));
      return true;
    };
    return visit(body);
  };
  const allowedTree = (value: string) => {
    const seen = new Set<string>();
    let count = 0;
    const walk = (filename: string): boolean => {
      if (++count > 50_000 || !allowedPath(filename, { recursive: true })) return false;
      const actual = canonical(filename);
      if (seen.has(actual)) return false;
      seen.add(actual);
      if (!fs.statSync(filename).isDirectory()) return true;
      return fs.readdirSync(filename).every(name => walk(path.join(filename, name)));
    };
    try { return walk(path.resolve(root, value)); } catch { return false; }
  };
  const reject = (res: Response) => res.status(403).json({ success: false, error: "下载中心资料及账号状态须通过下载中心授权入口访问" });
  const guardBody = (req: Request, res: Response, next: NextFunction) => {
    if (!bodyAllowed(req.body, req.path)) { reject(res); return; }
    next();
  };
  const guardRequest = (req: Request, res: Response, next: NextFunction) => {
    if (isDownloadProxyPath(req.path) || isFengshenAuthProxyPath(req.path)) { next(); return; }
    // Existing local handlers and the ASGI router must agree on the route.
    // Encoded legacy route separators may otherwise bypass a web-mode stub.
    if (req.path.startsWith("/api/") && req.path.includes("%")) { reject(res); return; }
    if (!req.path.startsWith("/api/")) {
      let filename: string;
      try {
        const decoded = decodeURIComponent(req.path);
        filename = decoded.startsWith("/@fs/") ? decoded.slice(5) : path.resolve(root, "." + decoded);
      } catch { reject(res); return; }
      if (!allowedPath(filename)) { reject(res); return; }
    }
    let owner = req.header("x-workspace-id") || String(req.query.workspace_id || "");
    try { owner = decodeURIComponent(owner); } catch { reject(res); return; }
    if (owner.toLowerCase().replace(/[^a-z0-9_-]/g, "").startsWith("account_")) { reject(res); return; }
    if (!bodyAllowed(req.query, req.path === "/api/download" ? "recursive-download" : req.path)) { reject(res); return; }
    next();
  };
  return { allowedPath, allowedTree, bodyAllowed, guardBody, guardRequest, reject };
}
