import test from 'node:test';
import assert from 'node:assert/strict';
import {
  BUILT_IN_DISPLAY_PRESETS,
  DEFAULT_DISPLAY_CONFIG,
  DESKTOP_27_PARAMS,
  LAPTOP_15_PARAMS,
  clampUiScale,
  computeDisplayCssTokens,
  detectScreenEnvironment,
  formatDisplayAdaptationBadge,
  resolveEffectiveDisplayParams,
  sanitizeDisplayConfig,
  sanitizeDisplayPresetList,
} from '../src/lib/displayAdaptation';
import {
  buildShellCommands,
  filterShellCommands,
  getActiveNavGroup,
  getBreadcrumbModel,
  getCurrentQuickTargetId,
  type ShellNavState,
} from '../src/lib/shellNav';

test('detectScreenEnvironment distinguishes 27-inch desktop monitors from 15.6-inch laptops', () => {
  // 1) 公司 27 寸 1080p / 2K 显示器
  const desktop1080 = detectScreenEnvironment({
    viewportWidth: 1920,
    viewportHeight: 980,
    screenWidth: 1920,
    screenHeight: 1080,
    devicePixelRatio: 1,
  });
  assert.equal(desktop1080.detectedClass, 'desktop_27');
  assert.match(desktop1080.detectedLabel, /27 寸/);

  const desktop2k = detectScreenEnvironment({
    viewportWidth: 2560,
    viewportHeight: 1340,
    screenWidth: 2560,
    screenHeight: 1440,
    devicePixelRatio: 1,
  });
  assert.equal(desktop2k.detectedClass, 'desktop_27');

  // 2) 家里 15.6 寸笔记本（1080p + Windows 125% 缩放 -> 1536×864 逻辑视口）
  const laptop125 = detectScreenEnvironment({
    viewportWidth: 1536,
    viewportHeight: 780,
    screenWidth: 1536,
    screenHeight: 864,
    devicePixelRatio: 1.25,
  });
  assert.equal(laptop125.detectedClass, 'laptop_15');
  assert.match(laptop125.detectedLabel, /15\.6 寸/);

  // 3) 1440×900 / 1366×768 笔记本
  const laptop1440 = detectScreenEnvironment({
    viewportWidth: 1440,
    viewportHeight: 810,
    screenWidth: 1440,
    screenHeight: 900,
    devicePixelRatio: 2,
  });
  assert.equal(laptop1440.detectedClass, 'laptop_15');
});

test('resolveEffectiveDisplayParams and computeDisplayCssTokens compute accurate 27-inch and 15.6-inch tokens', () => {
  // Auto mode on 27-inch monitor
  const auto27 = computeDisplayCssTokens(DEFAULT_DISPLAY_CONFIG, 'desktop_27');
  assert.equal(auto27.effectiveClass, 'desktop_27');
  assert.equal(auto27.effectiveParams.uiScale, 100);
  assert.equal(auto27.effectiveParams.contentWidth, 'wide');
  assert.equal(auto27.mainMaxWidthCss, '1760px');
  assert.equal(auto27.rootFontSizePx, 16);
  assert.equal(auto27.shouldCollapseSidebarOnLaptop, false);

  // Auto mode on 15.6-inch laptop
  const auto15 = computeDisplayCssTokens(DEFAULT_DISPLAY_CONFIG, 'laptop_15');
  assert.equal(auto15.effectiveClass, 'laptop_15');
  assert.equal(auto15.effectiveParams.uiScale, 92.5);
  assert.equal(auto15.effectiveParams.contentWidth, 'full');
  assert.equal(auto15.effectiveParams.density, 'compact');
  assert.equal(auto15.mainMaxWidthCss, '100%');
  assert.equal(auto15.sidebarWidthPx, 212);
  assert.equal(auto15.rootFontSizePx, 14.8);
  assert.equal(auto15.shellGapPx, 10);

  // Custom mode with auto_collapse sidebar on 15.6-inch laptop
  const customCollapse = computeDisplayCssTokens(
    {
      mode: 'custom',
      uiScale: 90,
      fontOffset: -1,
      contentWidth: 'full',
      density: 'compact',
      sidebarBehavior: 'auto_collapse',
    },
    'laptop_15',
  );
  assert.equal(customCollapse.shouldCollapseSidebarOnLaptop, true);
  assert.ok(customCollapse.rootFontSizePx < 14.8);
});

test('sanitizeDisplayConfig and sanitizeDisplayPresetList guard invalid input', () => {
  assert.equal(clampUiScale(50), 85);
  assert.equal(clampUiScale(150), 115);
  assert.equal(clampUiScale(92.5), 92.5);

  const fallback = sanitizeDisplayConfig(null);
  assert.deepEqual(fallback, DEFAULT_DISPLAY_CONFIG);

  const laptopCfg = sanitizeDisplayConfig({ mode: 'laptop_15', uiScale: 92.5 });
  assert.equal(laptopCfg.mode, 'laptop_15');
  assert.equal(laptopCfg.contentWidth, LAPTOP_15_PARAMS.contentWidth);

  const presets = sanitizeDisplayPresetList([
    {
      id: 'p1',
      name: '家里15.6寸护眼',
      targetScreen: 'laptop_15',
      uiScale: 95,
      fontOffset: 0,
      contentWidth: 'full',
      density: 'compact',
      sidebarBehavior: 'compact',
    },
    { id: '', name: '无效项' },
  ]);
  assert.equal(presets.length, 1);
  assert.equal(presets[0].name, '家里15.6寸护眼');
  assert.equal(BUILT_IN_DISPLAY_PRESETS.length, 4);
  assert.equal(DESKTOP_27_PARAMS.uiScale, 100);
});

test('formatDisplayAdaptationBadge formats sidebar badge accurately', () => {
  assert.equal(formatDisplayAdaptationBadge(DEFAULT_DISPLAY_CONFIG, 'desktop_27'), '27寸');
  assert.equal(formatDisplayAdaptationBadge(DEFAULT_DISPLAY_CONFIG, 'laptop_15'), '15.6寸');
  assert.equal(
    formatDisplayAdaptationBadge({ ...DEFAULT_DISPLAY_CONFIG, mode: 'custom', uiScale: 95 }, 'desktop_27'),
    '95%',
  );
});

test('shellNav places workspace:display-adaptation (界面适配) under 平台管理 for all users', () => {
  const state: ShellNavState = {
    workspaceView: 'display-adaptation',
    taskKind: 'download',
    downloadPlatform: 'fengshen',
    payrollSubView: 'batches',
  };

  assert.equal(getActiveNavGroup(state), 'admin');
  assert.equal(getCurrentQuickTargetId(state), 'workspace:display-adaptation');

  const breadcrumb = getBreadcrumbModel(state);
  assert.equal(breadcrumb.moduleLabel, '平台管理');
  assert.equal(breadcrumb.viewLabel, '界面适配');
  assert.equal(breadcrumb.siblings.length, 5);
  assert.equal(breadcrumb.siblings.find(s => s.active)?.id, 'display-adaptation');

  const commands = buildShellCommands(state, { isAdmin: false });
  const cmd = commands.find(c => c.id === 'nav-display-adaptation');
  assert.ok(cmd);
  assert.equal(cmd.group, '平台管理');
  assert.equal(cmd.label, '界面适配');
  assert.equal(cmd.active, true);

  assert.equal(filterShellCommands(commands, '15.6寸')[0]?.id, 'nav-display-adaptation');
  assert.equal(filterShellCommands(commands, '27寸')[0]?.id, 'nav-display-adaptation');
  assert.equal(filterShellCommands(commands, '界面适配')[0]?.id, 'nav-display-adaptation');
});
