import fs from "node:fs";
import path from "node:path";
import net from "node:net";
import { randomUUID } from "node:crypto";

/** Refuse a live sibling; remove a stale record only after its PID is gone. */
export function acquireStartupLock(filename: string): () => void {
  fs.mkdirSync(path.dirname(filename), { recursive: true });
  const token = randomUUID();
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      const descriptor = fs.openSync(filename, "wx", 0o600);
      try { fs.writeFileSync(descriptor, JSON.stringify({ pid: process.pid, token })); }
      finally { fs.closeSync(descriptor); }
      return () => {
        try {
          const record = JSON.parse(fs.readFileSync(filename, "utf8"));
          if (record.token === token) fs.unlinkSync(filename);
        } catch { /* Another process must never be removed by this cleanup. */ }
      };
    } catch (error: any) {
      if (error.code !== "EEXIST") throw error;
      let existing: { pid: number; token: string };
      try {
        existing = JSON.parse(fs.readFileSync(filename, "utf8"));
        if (!Number.isSafeInteger(existing.pid) || existing.pid <= 0 || typeof existing.token !== "string") throw new Error();
      } catch {
        throw new Error("启动锁无效，请确认旧服务已退出后由主机管理员检查 backend/.local_downloads/server.lock。");
      }
      try {
        process.kill(existing.pid, 0); // Existence check; never terminates a process.
        throw new Error("系统已经运行，请使用现有页面；重复启动不会终止旧服务。");
      } catch (check: any) {
        if (check.code !== "ESRCH") throw check;
      }
      // Compare the ownership record again before deleting a stale lock.
      try {
        const current = JSON.parse(fs.readFileSync(filename, "utf8"));
        if (current.token === existing.token && current.pid === existing.pid) fs.unlinkSync(filename);
      } catch (check: any) {
        if (check.code !== "ENOENT") throw check;
      }
    }
  }
  throw new Error("另一个启动进程正在初始化，请稍后使用现有服务。");
}

export async function assertPortAvailable(port: number, host: string) {
  const probe = net.createServer();
  await new Promise<void>((resolve, reject) => {
    probe.once("error", () => reject(new Error(`端口 ${port} 已被占用，未启动后台，也不会终止已有服务。`)));
    probe.listen({ port, host, exclusive: true }, () => probe.close(error => error ? reject(error) : resolve()));
  });
}
