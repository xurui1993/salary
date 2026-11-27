import test from 'node:test';
import assert from 'node:assert/strict';

import {
  BUSINESS_MODULE_CATALOG,
  DATASET_CONFIG_CATALOG,
  DEFAULT_GLOBAL_WORKBENCH_CONFIG,
  MODULE_GROUP_CATALOG,
  PLATFORM_CHANNEL_CATALOG,
  SUBMODULE_CATALOG,
  applyBusinessModuleEnabled,
  applyPlatformChannelMode,
  countGlobalConfigCustomizations,
  getDynamicPermissionGroups,
  getGlobalWorkbenchConfig,
  isBusinessModuleEnabled,
  isPlatformShared,
  normalizeGlobalWorkbenchConfig,
  partitionBusinessModules,
  partitionPlatformChannels,
  resolveChannelMode,
  resolveDatasetCardCopy,
  resolveModuleGroupLabel,
  resolveSubmoduleLabel,
  setGlobalWorkbenchConfig,
} from '../src/lib/workbenchConfig';
import {
  buildShellCommands,
  canMemberAccessDownloadPlatform,
  getBreadcrumbModel,
} from '../src/lib/shellNav';
import { getDatasetCardMeta, getStageHeaderMeta } from '../src/lib/workbench';

test('normalizeGlobalWorkbenchConfig sanitizes inputs and preserves catalog defaults', () => {
  assert.equal(PLATFORM_CHANNEL_CATALOG.length, 6);
  assert.equal(BUSINESS_MODULE_CATALOG.length, 4);
  assert.equal(MODULE_GROUP_CATALOG.length, 4);
  assert.equal(SUBMODULE_CATALOG.length, 18);
  assert.equal(DATASET_CONFIG_CATALOG.length, 40);

  const defaults = normalizeGlobalWorkbenchConfig(null);
  assert.deepEqual(defaults.channel_modes, {
    fengshen: 'personal',
    lanorange: 'personal',
    lanorange_mdr: 'personal',
    baize: 'personal',
    xiaoxiang: 'shared',
    benlai: 'shared',
  });
  assert.deepEqual(defaults.module_permissions, {
    collection: true,
    reports: true,
    payroll: true,
    approval: true,
  });

  // Setting a group/item name equal to default is stripped cleanly
  const normalized = normalizeGlobalWorkbenchConfig({
    channel_modes: {
      fengshen: 'shared',
      xiaoxiang: 'personal',
    } as any,
    module_permissions: {
      payroll: false,
    } as any,
    module_names: {
      groups: {
        collection: '数据中心',
        reports: '业务报表', // equals default -> stripped
      },
      items: {
        'platform:fengshen': '闪购采数',
      },
    },
    dataset_overrides: {
      delivery_fee: { title: '闪购配送费', desc: '按城按周期拉取基础配送费' },
      empty_entry: { title: '   ', desc: '' },
    },
  });

  assert.equal(resolveChannelMode('fengshen', normalized), 'shared');
  assert.equal(isPlatformShared('fengshen', normalized), true);
  assert.equal(resolveChannelMode('xiaoxiang', normalized), 'personal');
  assert.equal(isPlatformShared('xiaoxiang', normalized), false);
  assert.equal(isBusinessModuleEnabled('payroll', normalized), false);
  assert.equal(isBusinessModuleEnabled('collection', normalized), true);
  assert.equal(normalized.module_names.groups.reports, undefined);
  assert.equal(normalized.module_names.groups.collection, '数据中心');
  assert.equal(normalized.dataset_overrides.empty_entry, undefined);

  const counts = countGlobalConfigCustomizations(normalized);
  assert.deepEqual(counts, { channels: 2, modules: 1, names: 2, datasets: 1 });
});

test('setGlobalWorkbenchConfig updates store cleanly and naming resolvers apply overrides', () => {
  const original = getGlobalWorkbenchConfig();
  try {
    const custom = setGlobalWorkbenchConfig({
      module_names: {
        groups: { collection: '采数中心', reports: '专项分析' },
        items: { 'platform:fengshen': '闪购风神', 'workspace:history': '下载队列' },
      },
      dataset_overrides: {
        delivery_fee: { title: '自定义配送费', desc: '自定义副标题说明' },
      },
    });

    assert.equal(resolveModuleGroupLabel('collection', custom), '采数中心');
    assert.equal(resolveModuleGroupLabel('payroll', custom), '薪资核算');
    assert.equal(resolveSubmoduleLabel('platform:fengshen', '风神数据', custom), '闪购风神');
    assert.equal(resolveSubmoduleLabel('workspace:history', '任务下载', custom), '下载队列');

    const copy = resolveDatasetCardCopy('delivery_fee', '配送费', '默认说明', custom);
    assert.deepEqual(copy, { title: '自定义配送费', desc: '自定义副标题说明' });

    const stageMeta = getStageHeaderMeta('download', 'fengshen', 'create', custom);
    assert.equal(stageMeta.title, '闪购风神');

    const cardMeta = getDatasetCardMeta('delivery_fee', '配送费', custom);
    assert.equal(cardMeta.title, '自定义配送费');
    assert.equal(cardMeta.desc, '自定义副标题说明');

    const breadcrumb = getBreadcrumbModel(
      {
        workspaceView: 'history',
        taskKind: 'download',
        downloadPlatform: 'fengshen',
        payrollSubView: 'batches',
      },
      custom,
    );
    assert.equal(breadcrumb.moduleLabel, '采数中心');
    assert.equal(breadcrumb.viewLabel, '下载队列');
    assert.equal(breadcrumb.siblings[0].label, '闪购风神');
  } finally {
    setGlobalWorkbenchConfig(DEFAULT_GLOBAL_WORKBENCH_CONFIG);
    assert.equal(getGlobalWorkbenchConfig().updated_at, original.updated_at);
  }
});

test('canMemberAccessDownloadPlatform and getDynamicPermissionGroups reflect host channel allocation', () => {
  const allPersonal = normalizeGlobalWorkbenchConfig({
    channel_modes: {
      fengshen: 'personal',
      lanorange: 'personal',
      lanorange_mdr: 'personal',
      baize: 'personal',
      xiaoxiang: 'personal',
      benlai: 'personal',
    },
  });

  // When xiaoxiang is moved to personal, member can access even with xiaoxiang_use: false
  assert.equal(
    canMemberAccessDownloadPlatform('xiaoxiang', {
      isAdmin: false,
      permissions: { collection: true, xiaoxiang_use: false },
      globalConfig: allPersonal,
    }),
    true,
  );

  const permGroupsAllPersonal = getDynamicPermissionGroups(allPersonal);
  assert.equal(permGroupsAllPersonal[1].items.length, 1);
  assert.equal(permGroupsAllPersonal[1].items[0].key, 'shared_auth_manage');

  // When both baize and benlai are shared, member needs at least one enabled to open payout
  const payoutShared = normalizeGlobalWorkbenchConfig({
    channel_modes: {
      ...DEFAULT_GLOBAL_WORKBENCH_CONFIG.channel_modes,
      baize: 'shared',
      benlai: 'shared',
    },
  });
  assert.equal(
    canMemberAccessDownloadPlatform('payout', {
      isAdmin: false,
      permissions: { collection: true, baize_use: false, benlai_use: false },
      globalConfig: payoutShared,
    }),
    false,
  );
  assert.equal(
    canMemberAccessDownloadPlatform('payout', {
      isAdmin: false,
      permissions: { collection: true, baize_use: true, benlai_use: false },
      globalConfig: payoutShared,
    }),
    true,
  );

  // Admin retains full access to modules and commands even when modules are paused for members
  const pausedCollection = normalizeGlobalWorkbenchConfig({
    module_permissions: {
      ...DEFAULT_GLOBAL_WORKBENCH_CONFIG.module_permissions,
      collection: false,
    },
  });
  const adminCmds = buildShellCommands(
    {
      workspaceView: 'create',
      taskKind: 'download',
      downloadPlatform: 'fengshen',
      payrollSubView: 'batches',
    },
    { isAdmin: true, globalConfig: pausedCollection },
  );
  assert.ok(adminCmds.some(c => c.id === 'nav-fengshen'));
  const memberCmds = buildShellCommands(
    {
      workspaceView: 'create',
      taskKind: 'download',
      downloadPlatform: 'fengshen',
      payrollSubView: 'batches',
    },
    { isAdmin: false, permissions: { collection: true }, globalConfig: pausedCollection },
  );
  assert.equal(memberCmds.some(c => c.id === 'nav-fengshen'), false);
});

test('dual-lane partition and immutable transition helpers support search and custom names', () => {
  const defaults = normalizeGlobalWorkbenchConfig(null);

  const defaultPlatforms = partitionPlatformChannels(defaults);
  assert.deepEqual(
    defaultPlatforms.shared.map(p => p.key),
    ['xiaoxiang', 'benlai'],
  );
  assert.deepEqual(
    defaultPlatforms.personal.map(p => p.key),
    ['fengshen', 'lanorange', 'lanorange_mdr', 'baize'],
  );

  // Move fengshen into shared without mutating original config
  const nextModes = applyPlatformChannelMode(defaults, 'fengshen', 'shared');
  assert.equal(defaults.channel_modes.fengshen, 'personal');
  assert.equal(nextModes.fengshen, 'shared');
  const updatedConfig = normalizeGlobalWorkbenchConfig({
    ...defaults,
    channel_modes: nextModes,
    module_names: {
      groups: {},
      items: { 'workspace:approval': '日常价格复核' },
    },
  });
  const afterMove = partitionPlatformChannels(updatedConfig);
  assert.deepEqual(
    afterMove.shared.map(p => p.key),
    ['fengshen', 'xiaoxiang', 'benlai'],
  );

  // Search filtering matches platform label/subtitle
  const filteredPlatforms = partitionPlatformChannels(updatedConfig, '灯塔');
  assert.deepEqual(
    filteredPlatforms.shared.map(p => p.key),
    ['xiaoxiang'],
  );
  assert.equal(filteredPlatforms.personal.length, 0);

  // Business module dual-lane partition + pause transition + custom name search
  const defaultModules = partitionBusinessModules(updatedConfig);
  assert.equal(defaultModules.enabled.length, 4);
  assert.equal(defaultModules.paused.length, 0);

  const nextModulePerms = applyBusinessModuleEnabled(updatedConfig, 'approval', false);
  assert.equal(updatedConfig.module_permissions.approval, true);
  assert.equal(nextModulePerms.approval, false);

  const pausedConfig = normalizeGlobalWorkbenchConfig({
    ...updatedConfig,
    module_permissions: nextModulePerms,
  });
  const afterPause = partitionBusinessModules(pausedConfig);
  assert.deepEqual(
    afterPause.enabled.map(m => m.key),
    ['collection', 'reports', 'payroll'],
  );
  assert.deepEqual(
    afterPause.paused.map(m => m.key),
    ['approval'],
  );

  const filteredModules = partitionBusinessModules(pausedConfig, '价格复核');
  assert.equal(filteredModules.enabled.length, 0);
  assert.deepEqual(
    filteredModules.paused.map(m => m.key),
    ['approval'],
  );
});
