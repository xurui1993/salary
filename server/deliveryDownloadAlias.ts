import type { Request, Response, NextFunction } from 'express';
import path from 'node:path';

// Preserve existing payroll download links. The destination authenticates the
// workspace and matches an exact manifest; it never reads a caller-selected tree.
export function deliveryDownloadAlias(root: string) {
  const base=path.resolve(root);
  return (req: Request, _res: Response, next: NextFunction) => {
    if(req.method==='GET' && req.path==='/api/download' && typeof req.query.path==='string') {
      const target=path.resolve(req.query.path),relative=path.relative(base,target);
      if(relative && relative!=='..' && !relative.startsWith('..'+path.sep) && !path.isAbsolute(relative)) {
        if(!req.headers['x-workspace-id'] && typeof req.query.workspace_id==='string')req.headers['x-workspace-id']=req.query.workspace_id;
        req.url='/api/fengshen-downloads/delivery-download?'+new URLSearchParams({path:target}).toString();
      }
    }
    next();
  };
}
