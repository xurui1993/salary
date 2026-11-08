import fs from 'node:fs';
import path from 'node:path';
import { randomUUID } from 'node:crypto';

export function workspaceConfigFile(root: string, workspace: string): string {
  if (!/^[\w\u4e00-\u9fff-]+$/u.test(workspace)) throw new Error('工作区编号无效');
  return path.join(root, 'data', 'workspaces', `${workspace}.json`);
}

export function readWorkspaceConfig(root: string, workspace: string): unknown {
  const target = workspaceConfigFile(root, workspace);
  // Old installations remain readable until their local configuration is migrated.
  const legacy = path.join(root, `.aegis_config_${workspace}.json`);
  const source = fs.existsSync(target) ? target : legacy;
  return fs.existsSync(source) ? JSON.parse(fs.readFileSync(source, 'utf8')) : {};
}

export function writeWorkspaceConfig(root: string, workspace: string, value: unknown): void {
  const target = workspaceConfigFile(root, workspace);
  fs.mkdirSync(path.dirname(target), { recursive: true });
  const temporary = `${target}.${randomUUID()}.tmp`;
  try { fs.writeFileSync(temporary, JSON.stringify(value, null, 2), 'utf8'); fs.renameSync(temporary, target); }
  finally { if (fs.existsSync(temporary)) fs.unlinkSync(temporary); }
}
