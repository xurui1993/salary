import {spawn} from 'node:child_process';
import path from 'node:path';

/** ZIP bodies stay on disk; the helper reads and writes bounded 1 MiB blocks. */
export function extractSourceArchive(python: string, project: string, source: string, target: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const child = spawn(python, [path.join(project, 'backend', 'upload_archive.py'), source, target], {
      cwd: project, windowsHide: true, shell: false, stdio: ['ignore', 'pipe', 'pipe'],
      env: {...process.env, PYTHONIOENCODING: 'utf-8'},
    });
    let output = '';
    const timer = setTimeout(() => {
      if (process.platform === 'win32' && child.pid) spawn('taskkill', ['/PID', String(child.pid), '/T', '/F'], {windowsHide:true, shell:false, stdio:'ignore'}).on('error', () => child.kill());
      else child.kill();
      reject(new Error('解压用时过长，本次上传已停止；已接收资料保留'));
    }, 30 * 60 * 1000);
    child.stdout.on('data', chunk => { if (output.length < 65536) output += chunk.toString('utf-8'); });
    // Drain errors without exposing internal paths or retaining unbounded logs.
    child.stderr.on('data', () => {});
    child.once('error', () => { clearTimeout(timer); reject(new Error('无法启动资料解压服务；已接收资料保留')); });
    child.once('close', code => {
      clearTimeout(timer);
      try {
        const result = JSON.parse(output);
        if (code === 0 && result.success) resolve();
        else reject(new Error(result.error || '资料解压失败；已接收资料保留'));
      } catch { reject(new Error('资料解压服务未正常完成；已接收资料保留')); }
    });
  });
}
