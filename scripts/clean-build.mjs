import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';

export function cleanBuild(inputRoot){
  const root=fs.realpathSync(inputRoot);
  const target=path.resolve(root,'dist');
  if(!target.startsWith(root+path.sep))throw Error('Generated target outside project');
  if(!fs.existsSync(target))return;
  const info=fs.lstatSync(target);
  if(info.isSymbolicLink())throw Error('Generated target cannot be a directory link');
  if(!info.isDirectory())throw Error('Unexpected build target');
  fs.rmSync(target,{recursive:true});
}
if(process.argv[1]&&import.meta.url===pathToFileURL(path.resolve(process.argv[1])).href){cleanBuild(path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..'));console.log('Removed generated build.');}
