// Native HTTP streaming only. Authentication arrives on stdin, never argv/logs.
import {createWriteStream} from 'node:fs';
import {Readable, Transform} from 'node:stream';
import {pipeline} from 'node:stream/promises';

const allowed = new Set(['info/riderQuit/export','info/riderReportDetail/export',
  'info/riderBatchQuit/export','info/riderLeave/export','info/riderIdentityChange/export',
  'info/riderSalaryReplace/export','salary/partRiderPrice/export','info/riderInfo/export']);
let bytes = 0, status = 0;
try {
  let input = '';
  for await (const chunk of process.stdin) {
    input += chunk;
    if (input.length > 65536) throw new Error('input_size');
  }
  const p = JSON.parse(input);
  if (!allowed.has(p.endpoint)) throw new Error('invalid_endpoint');
  const response = await fetch('https://madouren.cdevelopment.cn/prod-api/' + p.endpoint,
    {method:'POST', headers:p.headers, body:p.body, redirect:'error', signal:AbortSignal.timeout(180000)});
  status = response.status;
  if (status !== 200) throw new Error('http_status');
  const limit = new Transform({transform(chunk, _encoding, done) {
    bytes += chunk.length;
    done(bytes > 200 * 1024 * 1024 ? new Error('size_limit') : null, chunk);
  }});
  await pipeline(Readable.fromWeb(response.body), limit, createWriteStream(p.output, {flags:'wx'}));
  process.stdout.write(JSON.stringify({ok:true, bytes, status}));
} catch (error) {
  process.stdout.write(JSON.stringify({ok:false, bytes, status,
    error_category:String(error.cause?.code || error.code || error.name || 'transport_error')}));
  process.exitCode = 1;
}
