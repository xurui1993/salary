import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import {
  UnifiedPlatformAuthModal,
  getPlatformAuthModalMeta,
  normalizePlatformAuthStatusText,
} from '../src/components/UnifiedPlatformAuthModal';
import { SourceLoginPanel } from '../src/components/SourceLoginPanel';

const noopFetch: typeof fetch = async () => {
  throw new Error('SSR test must not trigger network calls');
};

test('platform modal metadata provides cohesive titles, tags, and channel pills across all sources', () => {
  const lanorange = getPlatformAuthModalMeta('lanorange', '蓝橙');
  const lanorangeMdr = getPlatformAuthModalMeta('lanorange_mdr', '新蓝橙');
  const baize = getPlatformAuthModalMeta('baize', '商翼');
  const benlai = getPlatformAuthModalMeta('benlai', '本来人力');
  const xiaoxiang = getPlatformAuthModalMeta('xiaoxiang', '小象灯塔');

  assert.equal(lanorange.title, '蓝橙登录验证');
  assert.equal(lanorange.tag, '钉钉扫码授权');
  assert.equal(lanorangeMdr.title, '新蓝橙登录验证');
  assert.equal(lanorangeMdr.tag, '钉钉扫码授权');
  assert.equal(baize.title, '商翼登录验证');
  assert.equal(baize.tag, '企业账号认证');
  assert.equal(benlai.title, '本来人力登录验证');
  assert.equal(benlai.tag, '商户账号认证');
  assert.equal(xiaoxiang.title, '小象灯塔登录验证');
  assert.equal(xiaoxiang.tag, '双重扫码 / 短信认证');
});

test('normalizePlatformAuthStatusText fixes legacy misrouted Baize copy on Lanorange and refines Benlai/Baize copy', () => {
  const lanMeta = getPlatformAuthModalMeta('lanorange', '蓝橙');
  const fixedLan = normalizePlatformAuthStatusText(
    'lanorange',
    '请在内部表单完成白泽登录',
    'waiting_login',
    lanMeta,
  );
  assert.doesNotMatch(fixedLan, /白泽/);
  assert.match(fixedLan, /钉钉/);

  const benlaiMeta = getPlatformAuthModalMeta('benlai', '本来人力');
  const fixedBenlai = normalizePlatformAuthStatusText(
    'benlai',
    '请在内部表单完成本来人力登录',
    'waiting_login',
    benlaiMeta,
  );
  assert.match(fixedBenlai, /商户号\/手机号/);

  const baizeMeta = getPlatformAuthModalMeta('baize', '商翼');
  const fixedBaize = normalizePlatformAuthStatusText(
    'baize',
    '请在内部表单完成白泽登录',
    'waiting_login',
    baizeMeta,
  );
  assert.match(fixedBaize, /企业账号/);
});

test('lanorange and lanorange_mdr render unified centered modal with DingTalk QR stage and steps', () => {
  for (const [source, label] of [
    ['lanorange', '蓝橙'],
    ['lanorange_mdr', '新蓝橙'],
  ] as const) {
    const html = renderToStaticMarkup(
      React.createElement(
        UnifiedPlatformAuthModal,
        {
          sourceKey: source,
          displayName: label,
          status: {
            state: 'waiting_login',
            session_id: 'sid-qr',
            message: '请在内部表单完成白泽登录',
          },
          onClose: () => {},
          onStartLogin: () => {},
          onCredentialAction: () => {},
        },
        React.createElement(SourceLoginPanel, {
          source,
          sessionId: 'sid-qr',
          apiFetch: noopFetch,
          desktop: {
            fields: [],
            controls: [],
            has_qr: false,
            qr_state: 'preparing',
          },
        }),
      ),
    );
    assert.match(html, /wbx-unified-auth-modal/);
    assert.match(html, /钉钉扫码授权/);
    assert.match(html, /正在准备钉钉二维码/);
    assert.match(html, /打开手机端扫一扫/);
    assert.match(html, /重新读取二维码/);
    assert.doesNotMatch(html, /请在内部表单完成白泽登录/);
  }
});

test('baize renders unified modal with inline math captcha, password toggle, and refined submit button', () => {
  const html = renderToStaticMarkup(
    React.createElement(
      UnifiedPlatformAuthModal,
      {
        sourceKey: 'baize',
        displayName: '商翼',
        status: {
          state: 'waiting_login',
          session_id: 'sid-baize',
          message: '请在内部表单完成白泽登录',
        },
        onClose: () => {},
        onStartLogin: () => {},
        onCredentialAction: () => {},
      },
      React.createElement(SourceLoginPanel, {
        source: 'baize',
        sessionId: 'sid-baize',
        apiFetch: noopFetch,
        desktop: {
          fields: [
            { id: 'acc', type: 'text', label: '企业账号' },
            { id: 'pwd', type: 'password', role: 'password', label: '密码' },
            { id: 'math', type: 'text', role: 'math', label: '算式答案' },
          ],
          controls: [
            { id: 'ref', kind: 'captcha_refresh', label: '刷新算式' },
            { id: 'sub', kind: 'submit', label: '登录', enabled: true },
          ],
          math_captcha: {
            id: 'cap-1',
            state: 'manual',
            image: 'data:image/png;base64,AAAA',
          },
        },
      }),
    ),
  );
  assert.match(html, /商翼登录验证/);
  assert.match(html, /企业账号认证/);
  assert.match(html, /wbx-auth-captcha-inline/);
  assert.match(html, /alt="商翼算式验证码"/);
  assert.match(html, /刷新算式/);
  assert.match(html, /aria-label="显示密码"/);
  assert.match(html, /立即验证并登录/);
});

test('benlai renders unified modal with merchant account, password visibility toggle, and credential prompt', () => {
  const html = renderToStaticMarkup(
    React.createElement(
      UnifiedPlatformAuthModal,
      {
        sourceKey: 'benlai',
        displayName: '本来人力',
        status: {
          state: 'waiting_login',
          session_id: 'sid-benlai',
          credential_prompt: true,
          credential_account: '13800138000',
        },
        onClose: () => {},
        onStartLogin: () => {},
        onCredentialAction: () => {},
      },
      React.createElement(SourceLoginPanel, {
        source: 'benlai',
        sessionId: 'sid-benlai',
        apiFetch: noopFetch,
        desktop: {
          fields: [
            { id: 'acc', type: 'text', label: '商户号/手机号' },
            { id: 'pwd', type: 'password', role: 'password', label: '密码' },
          ],
          controls: [{ id: 'sub', kind: 'submit', label: '登录', enabled: true }],
        },
      }),
    ),
  );
  assert.match(html, /本来人力登录验证/);
  assert.match(html, /商户账号认证/);
  assert.match(html, /保存加密凭据/);
  assert.match(html, /仅本次登录/);
  assert.match(html, /请输入本来人力商户号或手机号/);
  assert.match(html, /aria-label="显示密码"/);
  assert.match(html, /立即验证并登录/);
});
