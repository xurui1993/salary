import test from 'node:test';
import assert from 'node:assert/strict';
import type { ClientRequest, IncomingMessage } from 'node:http';
import { protectProxyHeaders } from '../server/downloadProxy';

function createMockProxyReq(initial: Record<string, string> = {}) {
  const headers = new Map<string, string>(
    Object.entries(initial).map(([k, v]) => [k.toLowerCase(), v]),
  );
  return {
    getHeaderNames: () => Array.from(headers.keys()),
    removeHeader: (name: string) => {
      headers.delete(name.toLowerCase());
    },
    setHeader: (name: string, value: string) => {
      headers.set(name.toLowerCase(), String(value));
    },
    getHeader: (name: string) => headers.get(name.toLowerCase()),
  };
}

function createMockReq(headers: Record<string, string>, remoteAddress: string): IncomingMessage {
  return {
    headers,
    socket: { remoteAddress },
  } as unknown as IncomingMessage;
}

test('protectProxyHeaders trusts loopback X-Forwarded-Host for matching AI Studio preview Origin', () => {
  const host = 'ais-dev-upgtlexm4iul47roppfdbz-435988664994.us-east1.run.app';
  const proxyReq = createMockProxyReq({
    host: 'localhost:3000',
    origin: `https://${host}`,
    'x-forwarded-host': host,
    'x-forwarded-proto': 'https',
  });
  const req = createMockReq(
    {
      host: 'localhost:3000',
      origin: `https://${host}`,
      'x-forwarded-host': host,
      'x-forwarded-proto': 'https',
    },
    '127.0.0.1',
  );

  protectProxyHeaders(proxyReq as unknown as ClientRequest, req, 'secret-123');

  assert.equal(proxyReq.getHeader('host'), 'localhost:3000');
  assert.equal(proxyReq.getHeader('origin'), 'http://localhost:3000');
  assert.equal(proxyReq.getHeader('x-download-proxy-https'), '1');
  assert.equal(proxyReq.getHeader('x-download-proxy-secret'), 'secret-123');
  assert.equal(proxyReq.getHeader('x-forwarded-host'), undefined);
});

test('protectProxyHeaders does NOT rewrite cross-site Origin even behind AI Studio preview proxy', () => {
  const host = 'ais-dev-upgtlexm4iul47roppfdbz-435988664994.us-east1.run.app';
  const proxyReq = createMockProxyReq({
    host: 'localhost:3000',
    origin: 'https://evil.example',
    'x-forwarded-host': host,
  });
  const req = createMockReq(
    {
      host: 'localhost:3000',
      origin: 'https://evil.example',
      'x-forwarded-host': host,
    },
    '::ffff:127.0.0.1',
  );

  protectProxyHeaders(proxyReq as unknown as ClientRequest, req, 'secret-123');

  assert.equal(proxyReq.getHeader('origin'), 'https://evil.example');
});

test('protectProxyHeaders ignores spoofed X-Forwarded-Host from non-loopback LAN clients', () => {
  const host = 'ais-dev-upgtlexm4iul47roppfdbz-435988664994.us-east1.run.app';
  const proxyReq = createMockProxyReq({
    host: '192.168.1.10:3000',
    origin: `https://${host}`,
    'x-forwarded-host': host,
  });
  const req = createMockReq(
    {
      host: '192.168.1.10:3000',
      origin: `https://${host}`,
      'x-forwarded-host': host,
    },
    '192.168.1.50',
  );

  protectProxyHeaders(proxyReq as unknown as ClientRequest, req, 'secret-123');

  assert.equal(proxyReq.getHeader('host'), '192.168.1.10:3000');
  assert.equal(proxyReq.getHeader('origin'), `https://${host}`);
  assert.equal(proxyReq.getHeader('x-download-proxy-https'), undefined);
});
