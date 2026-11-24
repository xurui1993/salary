// @ts-nocheck
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { useStationDirectory } from '../lib/useStationDirectory';
import { CityStationAccordionCard } from './CityStationAccordionCard';
import { CityDeductionTableView } from './CityDeductionTableView';
import { WorkbenchDrawer } from './WorkbenchDrawer';
import { EmptyState } from './EmptyState';
import {
  applyConfigRuleRows,
  applyProblemRuleRows,
  buildDeductionCategories,
  buildProblemRuleExportRows,
  buildUnifiedConfigWorkbookData,
  classifyImportedWorkbookSheets,
  CONFIG_RULE_COLUMNS,
  CONFIG_RULE_COLUMNS_WITH_THRESHOLDS,
  groupDeductionsByCity,
  summarizeCitiesProgress,
  visibleColumnsForCategory,
  type DeductionCategoryId,
} from '../lib/deductionCategories';
import { formatPayrollDateTime } from '../lib/payrollQueue';
import { applyCityAmounts } from '../lib/payrollReviewActions';
import {
  AlertCircle,
  Check,
  FileSpreadsheet,
  FilterX,
  FolderCog,
  RefreshCw,
  RotateCcw,
  Search,
  Tag,
  Upload,
  X,
} from 'lucide-react';
import {
  shouldUseDemoData,
  useDemoDataVisibility,
  usePlatformAuthSnapshot,
} from '../lib/demoMode';
import { buildDemoDeductionData } from '../lib/showcaseDemoData';
import { DemoDataChip } from './DemoDataChip';

function readErrorMessage(err: unknown, networkFallback: string): string {
  const raw = err instanceof Error ? err.message : typeof err === 'string' ? err : '';
  const text = raw.trim();
  if (!text) return networkFallback;
  if (/Failed to fetch|NetworkError|Load failed|Network request failed|ERR_NETWORK|ERR_CONNECTION|fetch failed|net::/i.test(text)) {
    return networkFallback;
  }
  if (/timeout|timed out|AbortError|aborted|signal is aborted/i.test(text)) {
    return '读取超时，请稍后重试';
  }
  return text;
}

export function StationDeductionManager({
  apiFetch,
  platform = 'fengshen',
  inline = false,
  onClose,
  onSaved,
}: {
  apiFetch: (url: string, init?: RequestInit) => Promise<Response>;
  platform?: 'fengshen' | 'xiaoxiang';
  inline?: boolean;
  onClose?: () => void;
  onSaved: () => void;
}) {
  const [currentPlatform, setCurrentPlatform] = useState<'fengshen' | 'xiaoxiang'>(platform);
  const [pendingPlatform, setPendingPlatform] = useState<'fengshen' | 'xiaoxiang' | null>(null);
  const [profile, setProfile] = useState<any>(null);
  const [entries, setEntries] = useState<any[]>([]);
  const [cities, setCities] = useState<any[]>([]);
  const [cityFilter, setCityFilter] = useState('');
  const [citySearch, setCitySearch] = useState('');
  const [onlyPendingCities, setOnlyPendingCities] = useState(false);
  const [activeCategory, setActiveCategory] = useState<DeductionCategoryId>('all');
  const [search, setSearch] = useState('');
  const [onlyUnconfigured, setOnlyUnconfigured] = useState(false);
  const [activeCityId, setActiveCityId] = useState<string | null>(null);
  const [selectedStations, setSelectedStations] = useState<Set<string>>(new Set());
  const [undoEntries, setUndoEntries] = useState<any[] | null>(null);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [reloadKey, setReloadKey] = useState(0);
  const [confirmClose, setConfirmClose] = useState(false);
  const [problemBusy, setProblemBusy] = useState(false);
  const [problemError, setProblemError] = useState('');
  const [problemNotice, setProblemNotice] = useState('');
  const [problemPreview, setProblemPreview] = useState<any>(null);
  const [pendingProblemRows, setPendingProblemRows] = useState<any[] | null>(null);
  const [problemDirty, setProblemDirty] = useState(false);
  const configUpload = useRef<HTMLInputElement>(null);
  const initializedExpandRef = useRef<string>('');
  const directory = useStationDirectory(currentPlatform, apiFetch);

  const auth = usePlatformAuthSnapshot();
  const { demoHidden, toggleDemoHidden } = useDemoDataVisibility();

  const [demoStore, setDemoStore] = useState<
    Record<'fengshen' | 'xiaoxiang', ReturnType<typeof buildDemoDeductionData>>
  >(() => ({
    fengshen: buildDemoDeductionData('fengshen'),
    xiaoxiang: buildDemoDeductionData('xiaoxiang'),
  }));

  const isPlatformLoggedIn = auth.isLoggedIn(currentPlatform);
  const hasLiveData = entries.length > 0 || cities.length > 0;
  const demoActive = shouldUseDemoData({
    isLoggedIn: isPlatformLoggedIn,
    hasLiveData,
    demoHidden,
  });

  // 真实登录后立即重置演示态并重新拉取该平台后台扣款配置
  const prevPlatformLoggedInRef = useRef(isPlatformLoggedIn);
  useEffect(() => {
    if (isPlatformLoggedIn && !prevPlatformLoggedInRef.current) {
      setDirty(false);
      setProblemDirty(false);
      setPendingProblemRows(null);
      setProblemPreview(null);
      setUndoEntries(null);
      setActiveCityId(null);
      setSelectedStations(new Set());
      setNotice('');
      setError('');
      setReloadKey(val => val + 1);
    }
    prevPlatformLoggedInRef.current = isPlatformLoggedIn;
  }, [isPlatformLoggedIn]);

  useEffect(() => {
    const controller = new AbortController();
    apiFetch(`/api/workbench/deduction-profiles/${currentPlatform}`, { signal: controller.signal })
      .then(async res => {
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || '扣款读取失败');
        if (controller.signal.aborted) return;
        setProfile((prev: any) => (dirty && prev ? prev : data));
        setEntries((prev: any[]) => {
          if (!dirty) return data.entries || [];
          const map = new Map(prev.map(item => [item.key, item]));
          return (data.entries || []).map((item: any) => map.get(item.key) || item);
        });
        setCities((prev: any[]) => (dirty ? prev : data.cities || []));
        setError('');
      })
      .catch(err => {
        if (controller.signal.aborted) return;
        setProfile(null);
        setEntries([]);
        setCities([]);
        setError(readErrorMessage(err, '扣款配置读取失败，请检查后台连接后重试'));
      });
    return () => controller.abort();
  }, [currentPlatform, directory.data?.stations?.length, directory.data?.fetched_at, directory.data?.status, reloadKey, dirty]);

  const currentDemo = demoStore[currentPlatform];
  const displayProfile = demoActive
    ? {
        platform: currentPlatform,
        version: currentDemo.profile.version,
        columns: currentDemo.columns,
        entries: currentDemo.entries,
        cities: currentDemo.cities,
        demo: true,
      }
    : profile;
  const displayEntries = demoActive ? currentDemo.entries : entries;
  const displayCities = demoActive ? currentDemo.cities : cities;

  const setActiveEntries = (updater: any[] | ((prev: any[]) => any[])) => {
    if (demoActive) {
      setDemoStore(prev => {
        const cur = prev[currentPlatform];
        const nextEntries = typeof updater === 'function' ? updater(cur.entries) : updater;
        return { ...prev, [currentPlatform]: { ...cur, entries: nextEntries } };
      });
      return;
    }
    setEntries(updater as any);
  };

  const setActiveCities = (updater: any[] | ((prev: any[]) => any[])) => {
    if (demoActive) {
      setDemoStore(prev => {
        const cur = prev[currentPlatform];
        const nextCities = typeof updater === 'function' ? updater(cur.cities) : updater;
        return { ...prev, [currentPlatform]: { ...cur, cities: nextCities } };
      });
      return;
    }
    setCities(updater as any);
  };

  const effectiveDirectoryCities = useMemo(
    () => (demoActive ? currentDemo.directoryCities : directory.data?.cities || []),
    [demoActive, currentDemo.directoryCities, directory.data?.cities],
  );

  const activeColumns: string[] = useMemo(
    () => (displayProfile?.columns?.length ? displayProfile.columns : [...CONFIG_RULE_COLUMNS_WITH_THRESHOLDS]),
    [displayProfile?.columns],
  );

  const visibleItemCount = useMemo(
    () => activeColumns.filter(col => !col.endsWith('_maxDays')).length,
    [activeColumns],
  );
  const fengshenItemCount = currentPlatform === 'fengshen' ? visibleItemCount : CONFIG_RULE_COLUMNS.length;
  const xiaoxiangItemCount = currentPlatform === 'xiaoxiang' ? visibleItemCount : 3;

  const categorySpecs = useMemo(
    () => buildDeductionCategories(activeColumns),
    [activeColumns],
  );

  const visibleColumns = useMemo(
    () => visibleColumnsForCategory(activeColumns, activeCategory),
    [activeColumns, activeCategory],
  );

  const citySummaries = useMemo(
    () => summarizeCitiesProgress(displayCities, displayEntries, effectiveDirectoryCities),
    [displayCities, displayEntries, effectiveDirectoryCities],
  );

  const allCityGroups = useMemo(
    () => groupDeductionsByCity(displayCities, displayEntries, effectiveDirectoryCities, {}),
    [displayCities, displayEntries, effectiveDirectoryCities],
  );

  const cityGroups = useMemo(
    () =>
      groupDeductionsByCity(displayCities, displayEntries, effectiveDirectoryCities, {
        cityFilter,
        citySearch,
        stationSearch: search,
        onlyPendingCities,
        onlyUnconfigured,
      }),
    [displayCities, displayEntries, effectiveDirectoryCities, cityFilter, citySearch, search, onlyPendingCities, onlyUnconfigured],
  );

  const activeCityGroup = useMemo(
    () => (activeCityId ? allCityGroups.find(g => g.summary.cityId === activeCityId) || null : null),
    [activeCityId, allCityGroups],
  );

  useEffect(() => {
    if (!displayCities.length && !displayEntries.length) return;
    const firstCityId = displayCities[0]?.station?.city_id || displayEntries[0]?.station?.city_id || '';
    if (!firstCityId) return;
    const signature = `${currentPlatform}:${demoActive ? 'demo' : 'live'}:${firstCityId}:${displayEntries.length > 0 ? '1' : '0'}`;
    if (initializedExpandRef.current !== signature) {
      initializedExpandRef.current = signature;
      setActiveCityId(null);
    }
  }, [displayCities, displayEntries, currentPlatform, demoActive]);

  const pendingCount = displayEntries.filter(item => !item.configured).length;
  const configuredCount = displayEntries.length - pendingCount;

  const clearFilters = () => {
    setCityFilter('');
    setCitySearch('');
    setSearch('');
    setOnlyUnconfigured(false);
    setOnlyPendingCities(false);
  };

  const switchPlatform = (next: 'fengshen' | 'xiaoxiang') => {
    setPendingPlatform(null);
    setDirty(false);
    setUndoEntries(null);
    setProblemDirty(false);
    setPendingProblemRows(null);
    setProblemPreview(null);
    setProblemError('');
    setProblemNotice('');
    setProfile(null);
    setEntries([]);
    setCities([]);
    setCityFilter('');
    setCitySearch('');
    setSearch('');
    setOnlyPendingCities(false);
    setOnlyUnconfigured(false);
    setActiveCategory('all');
    setActiveCityId(null);
    setSelectedStations(new Set());
    setError('');
    setNotice('');
    setCurrentPlatform(next);
  };

  const requestPlatform = (next: 'fengshen' | 'xiaoxiang') => {
    if (next === currentPlatform || saving) return;
    if (dirty) {
      setPendingPlatform(next);
      return;
    }
    switchPlatform(next);
  };

  const modifiedCityCount = displayCities.filter(item => item.edited).length;
  const modifiedStationCount = displayEntries.filter(item => item.edited).length;
  const hasUnsavedChanges = dirty || problemDirty || Boolean(pendingProblemRows?.length);

  const handleDiscard = () => {
    if (saving) return;
    setDirty(false);
    setProblemDirty(false);
    setPendingProblemRows(null);
    setProblemPreview(null);
    setUndoEntries(null);
    setError('');
    if (demoActive) {
      setDemoStore(prev => ({ ...prev, [currentPlatform]: buildDemoDeductionData(currentPlatform) }));
      setNotice('示例模式：已还原为初始示例扣款配置。');
      return;
    }
    setNotice('已放弃未保存的修改，恢复为上次保存的扣款配置。');
    setReloadKey(val => val + 1);
  };

  async function handleSave() {
    if (demoActive) {
      setDemoStore(prev => {
        const cur = prev[currentPlatform];
        return {
          ...prev,
          [currentPlatform]: {
            ...cur,
            profile: {
              ...cur.profile,
              version: `${cur.profile.version}-saved`,
            },
            cities: cur.cities.map(c => ({ ...c, edited: false })),
            entries: cur.entries.map(e => ({ ...e, edited: false })),
          },
        };
      });
      setDirty(false);
      setProblemDirty(false);
      setPendingProblemRows(null);
      setProblemPreview(null);
      setUndoEntries(null);
      setNotice('示例模式：修改已保存在本地预览，登录真实平台后可同步至后台。');
      return;
    }
    if (!profile) return;
    setSaving(true);
    setError('');
    try {
      const editedEntries = entries.filter(item => item.edited);
      const editedCities = cities.filter(item => item.edited);
      const hasProblemUpdates =
        currentPlatform !== 'xiaoxiang' && (Boolean(pendingProblemRows?.length) || problemDirty);
      const effectiveProblemRows =
        currentPlatform === 'xiaoxiang'
          ? null
          : pendingProblemRows || (problemDirty ? buildProblemRuleExportRows(cities, entries) : null);
      if (!editedEntries.length && !editedCities.length && !hasProblemUpdates) {
        throw new Error('请先配置金额，或明确确认零扣款');
      }
      let currentVersion = profile.version;
      if (editedEntries.length || editedCities.length) {
        const res = await apiFetch(`/api/workbench/deduction-profiles/${currentPlatform}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            version: currentVersion,
            entries: editedEntries,
            cities: editedCities,
          }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || '保存失败');
        currentVersion = data.version;
      }

      if (hasProblemUpdates && effectiveProblemRows) {
        const previewRes = await apiFetch(`/api/workbench/deduction-profiles/${currentPlatform}/problem-rules/preview`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ version: currentVersion, rows: effectiveProblemRows }),
        });
        const previewData = await previewRes.json();
        if (!previewRes.ok) throw new Error(previewData.detail || '问题单关键词规则校验失败');

        const putRes = await apiFetch(`/api/workbench/deduction-profiles/${currentPlatform}/problem-rules`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            version: currentVersion,
            preview_version: previewData.preview_version,
            rows: previewData.rows,
          }),
        });
        const putData = await putRes.json();
        if (!putRes.ok) throw new Error(putData.detail || '问题单关键词规则保存失败');
        currentVersion = putData.version;
      }

      setProfile({ ...profile, version: currentVersion });
      setDirty(false);
      setProblemDirty(false);
      setPendingProblemRows(null);
      setProblemPreview(null);
      setUndoEntries(null);
      setReloadKey(val => val + 1);
      setNotice(
        currentPlatform === 'xiaoxiang'
          ? '小象超市保险费、循环物资使用费、附加险已保存，后续核算按站点例外优先、城市默认其次沿用。'
          : hasProblemUpdates
            ? '默认扣款与问题单关键词规则已统一保存，后续核算按站点规则优先、城市默认其次执行。'
            : '默认扣款已保存，后续核算按站点例外优先、城市默认其次沿用。',
      );
      onSaved();
    } catch (err) {
      setError(readErrorMessage(err, '保存失败，请检查后台连接后重试'));
    } finally {
      setSaving(false);
    }
  }

  const handleExportConfigExcel = async () => {
    setError('');
    try {
      const XLSX = await import('xlsx');
      const workbook = buildUnifiedConfigWorkbookData(displayCities, displayEntries, activeColumns);
      const book = XLSX.utils.book_new();

      const itemSheet = workbook.itemRows.length
        ? XLSX.utils.json_to_sheet(workbook.itemRows, { header: workbook.itemHeaders })
        : XLSX.utils.aoa_to_sheet([workbook.itemHeaders]);
      XLSX.utils.book_append_sheet(book, itemSheet, workbook.itemSheetName);

      if (currentPlatform !== 'xiaoxiang') {
        const problemSheet = workbook.problemRows.length
          ? XLSX.utils.json_to_sheet(workbook.problemRows, { header: workbook.problemHeaders })
          : XLSX.utils.aoa_to_sheet([workbook.problemHeaders]);
        XLSX.utils.book_append_sheet(book, problemSheet, workbook.problemSheetName);
      }

      XLSX.writeFile(
        book,
        currentPlatform === 'xiaoxiang'
          ? '小象超市扣款配置.xlsx'
          : `站点扣款配置_${currentPlatform}.xlsx`,
      );
      setNotice(
        currentPlatform === 'xiaoxiang'
          ? `已导出小象超市扣款配置：包含「${workbook.itemSheetName}」${workbook.itemRows.length} 行。`
          : displayEntries.length > 0
            ? `已导出 Excel 配置：包含「${workbook.itemSheetName}」${workbook.itemRows.length} 行、「${workbook.problemSheetName}」${workbook.problemRows.length} 条。`
            : '已导出标准 2 表合一 Excel 配置模板（含扣款项与问题单关键词表）。',
      );
    } catch (err) {
      setError(readErrorMessage(err, '导出 Excel 配置文件失败'));
    }
  };

  const handleImportConfigFile = async (file: File) => {
    setError('');
    setNotice('');
    setProblemError('');
    setProblemNotice('');
    setProblemPreview(null);
    try {
      if (!displayProfile || (!displayCities.length && !displayEntries.length)) {
        throw new Error('请先登录平台并等待后台城市与站点目录加载完成，再导入匹配到对应站点');
      }

      let itemRows: Array<Record<string, unknown>> = [];
      let problemRows: Array<Record<string, unknown>> = [];

      if (/\.json$/i.test(file.name)) {
        const parsed = JSON.parse(await file.text());
        const rawList = Array.isArray(parsed) ? parsed : parsed?.rows || [];
        const classified = classifyImportedWorkbookSheets([{ name: 'config', rows: rawList }], activeColumns);
        itemRows = classified.itemRows;
        problemRows = classified.problemRows;
      } else {
        const XLSX = await import('xlsx');
        const book = XLSX.read(await file.arrayBuffer(), { type: 'array' });
        const sheets = book.SheetNames.map(name => ({
          name,
          rows: XLSX.utils.sheet_to_json(book.Sheets[name], { raw: true, defval: null }),
        }));
        const classified = classifyImportedWorkbookSheets(sheets, activeColumns);
        itemRows = classified.itemRows;
        problemRows = classified.problemRows;
      }

      if (currentPlatform === 'xiaoxiang') problemRows = [];

      if (!itemRows.length && !problemRows.length) {
        throw new Error(
          currentPlatform === 'xiaoxiang'
            ? '导入文件中没有可识别的保险费、循环物资使用费或附加险扣款项行'
            : '导入文件中没有可识别的扣款项或问题单关键词规则行',
        );
      }

      let nextCities = displayCities;
      let nextEntries = displayEntries;
      const summaryParts: string[] = [];

      if (itemRows.length > 0) {
        const itemResult = applyConfigRuleRows(itemRows, nextCities, nextEntries, activeColumns);
        if (itemResult.matchedCityCount === 0 && itemResult.matchedStationCount === 0 && !problemRows.length) {
          throw new Error('文件中未匹配到当前后台目录中的城市或站点，请核对「城市」与「团队名称」');
        }
        nextCities = itemResult.updatedCities;
        nextEntries = applyCityAmounts(itemResult.updatedEntries, nextCities, activeColumns);
        summaryParts.push(
          `扣款项：更新 ${itemResult.matchedCityCount} 个城市统一规则与 ${itemResult.matchedStationCount} 个站点${itemResult.unmatchedRows.length ? `（${itemResult.unmatchedRows.length} 行未匹配）` : ''}`,
        );
      }

      if (problemRows.length > 0) {
        const kwResult = applyProblemRuleRows(problemRows, nextCities, nextEntries);
        if (kwResult.matchedCityRules === 0 && kwResult.matchedStationRules === 0) {
          throw new Error('问题单关键词工作表中未匹配到当前目录中的城市或站点');
        }
        nextCities = kwResult.updatedCities;
        nextEntries = kwResult.updatedEntries;
        setPendingProblemRows(problemRows);

        summaryParts.push(
          `关键词规则：识别城市 ${kwResult.matchedCityRules} 条、站点 ${kwResult.matchedStationRules} 条（新增 ${kwResult.diff.addedCount} / 变更 ${kwResult.diff.updatedCount} / 移除 ${kwResult.diff.removedCount}）`,
        );

        if (!demoActive && itemRows.length === 0) {
          const res = await apiFetch(`/api/workbench/deduction-profiles/${currentPlatform}/problem-rules/preview`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ version: profile.version, rows: problemRows }),
          });
          const data = await res.json();
          if (!res.ok) throw new Error(data.detail || '问题单扣款配置预览失败');
          setProblemPreview(data);
        }
      }

      setActiveCities(nextCities);
      setActiveEntries(nextEntries);
      setDirty(true);
      setNotice(`已从 Excel 导入并解析（${summaryParts.join('；')}），核对无误后请点击“保存后续默认扣款”。`);
    } catch (err) {
      setError(readErrorMessage(err, '导入扣款配置 Excel 失败，请检查工作表列名与格式'));
    }
  };

  const applyProblemRules = async () => {
    if (!problemPreview) return;
    setProblemBusy(true);
    setProblemError('');
    try {
      const res = await apiFetch(`/api/workbench/deduction-profiles/${currentPlatform}/problem-rules`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          version: profile.version,
          preview_version: problemPreview.preview_version,
          rows: problemPreview.rows,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || '问题单扣款配置保存失败');
      setProfile((prev: any) => ({ ...prev, version: data.version, problem_rules: data.problem_rules || {} }));
      setProblemPreview(null);
      setPendingProblemRows(null);
      setDirty(false);
      setProblemNotice('问题单关键词扣款配置已保存。');
      setReloadKey(value => value + 1);
      onSaved();
    } catch (err) {
      setProblemError(readErrorMessage(err, '问题单扣款配置保存失败'));
    } finally {
      setProblemBusy(false);
    }
  };

  const handleRequestClose = () => {
    if (dirty) setConfirmClose(true);
    else onClose?.();
  };

  const errorMessage = demoActive
    ? ''
    : String(
        error ||
          (directory.error ? readErrorMessage(directory.error, '扣款配置读取失败，请检查后台连接后重试') : '') ||
          directory.data?.message ||
          '',
      );

  const visibleProblemRules = useMemo(() => {
    const visibleCityIds = activeCityGroup
      ? new Set([activeCityGroup.summary.cityId])
      : new Set(cityGroups.map(g => g.summary.cityId));
    const filteredCities = displayCities.filter(c => visibleCityIds.has(c.station.city_id));
    const filteredEntries = displayEntries.filter(e => visibleCityIds.has(e.station.city_id));
    return buildProblemRuleExportRows(filteredCities, filteredEntries);
  }, [displayCities, displayEntries, cityGroups, activeCityGroup]);

  const totalProblemRules =
    displayCities.reduce((sum: number, city: any) => sum + (city.problem_rules?.length || 0), 0) +
    displayEntries.reduce((sum: number, entry: any) => sum + (entry.problem_rules?.length || 0), 0);

  const filteredCityJumpSummaries = useMemo(() => {
    const q = citySearch.trim().toLowerCase();
    return citySummaries.filter(item => {
      if (onlyPendingCities && item.pendingStations === 0) return false;
      if (q && !item.cityName.toLowerCase().includes(q) && !item.cityId.toLowerCase().includes(q)) return false;
      return true;
    });
  }, [citySummaries, citySearch, onlyPendingCities]);

  const isOfflineLoginEmpty =
    displayEntries.length === 0 &&
    displayCities.length === 0 &&
    Boolean(errorMessage && errorMessage.includes('登录'));

  const content = (
    <>
      {/* 1. 顶部统一极简下划线操作条：业务线页签 + 精简计数 + Excel 导入导出与保存 */}
      <div className="wbx-ded-topbar">
        <div className="wbx-ded-topbar__left">
          <div className="wbx-ded-tabs" role="group" aria-label="扣款业务切换">
            <button
              type="button"
              className={`wbx-ded-tab${currentPlatform === 'fengshen' ? ' is-active' : ''}`}
              aria-pressed={currentPlatform === 'fengshen'}
              disabled={saving}
              onClick={() => requestPlatform('fengshen')}
            >
              <span>风神 / 闪购</span>
              <span className="wbx-ded-tab__count tabular-nums" title="风神 / 闪购核心扣款科目数（不含天数阈值字段）">
                {fengshenItemCount} 项
              </span>
            </button>
            <button
              type="button"
              className={`wbx-ded-tab${currentPlatform === 'xiaoxiang' ? ' is-active' : ''}`}
              aria-pressed={currentPlatform === 'xiaoxiang'}
              disabled={saving}
              onClick={() => requestPlatform('xiaoxiang')}
            >
              <span>小象超市</span>
              <span className="wbx-ded-tab__count tabular-nums" title="小象超市核心扣款科目数">
                {xiaoxiangItemCount} 项
              </span>
            </button>
          </div>

          <span className="wbx-ded-inline-meta tabular-nums">
            <strong>{citySummaries.length}</strong> 城 / <strong>{displayEntries.length}</strong> 站 · 已配 {configuredCount} · 待配 {pendingCount}
          </span>
          {dirty && <span className="wbx-ded-dirty-tag">有未保存修改</span>}
        </div>

        <div className="wbx-ded-topbar__right">
          <DemoDataChip
            demoActive={demoActive}
            canShowDemo={!isPlatformLoggedIn && !hasLiveData && demoHidden}
            onToggle={() => {
              setActiveCityId(null);
              setSelectedStations(new Set());
              toggleDemoHidden();
            }}
          />
          <button
            type="button"
            className="wbx-btn wbx-btn--sm"
            disabled={saving}
            title={currentPlatform === 'xiaoxiang'
              ? '支持导入含「城市与站点扣款项」的 Excel（保险费/循环物资使用费/附加险）'
              : '支持导入含「城市与站点扣款项」及「问题单关键词扣款」的多表 Excel（.xlsx/.xls）'}
            onClick={() => configUpload.current?.click()}
          >
            <Upload size={13.5} aria-hidden="true" />
            <span>导入配置 Excel</span>
          </button>
          <button
            type="button"
            className="wbx-btn wbx-btn--sm"
            disabled={saving}
            title={currentPlatform === 'xiaoxiang'
              ? '导出小象超市城市/站点 3 项扣款配置 Excel'
              : '导出含城市/站点扣款项与问题单关键词明细的多表 Excel'}
            onClick={() => void handleExportConfigExcel()}
          >
            <FileSpreadsheet size={13.5} aria-hidden="true" />
            <span>导出配置 Excel</span>
          </button>
        </div>

        <input
          ref={configUpload}
          type="file"
          accept=".xlsx,.xls"
          className="hidden"
          aria-label={currentPlatform === 'xiaoxiang'
            ? '导入小象超市站点扣款配置 Excel 文件'
            : '导入站点扣款与问题单关键词配置 Excel 文件'}
          onChange={event => {
            const file = event.target.files?.[0];
            event.target.value = '';
            if (file) void handleImportConfigFile(file);
          }}
        />
      </div>

      {!displayEntries.length && !errorMessage && (
        <div className="wbx-deduction-alert" role="status">
          <div className="wbx-deduction-alert__body">
            <AlertCircle size={15} aria-hidden="true" />
            <span>
              {directory.data?.status === 'ready'
                ? '暂无扣款配置。请从站点目录选择城市/站点，或导入配置 Excel 后保存。'
                : '站点目录尚未就绪，请先连接平台并刷新目录；已保存的扣款配置不会丢失。'}
            </span>
          </div>
        </div>
      )}

      {pendingPlatform && (
        <div role="alert" className="wb-inline-confirm-bar">
          <span>
            当前业务有未保存的扣款调整，切换到「{pendingPlatform === 'xiaoxiang' ? '小象超市' : '风神'}」将放弃这些修改。
          </span>
          <div className="wb-row gap-2">
            <button
              type="button"
              className="wb-button text-xs py-1 px-2.5 min-h-[30px]"
              onClick={() => setPendingPlatform(null)}
            >
              继续编辑
            </button>
            <button
              type="button"
              className="wb-primary text-xs py-1 px-3 min-h-[30px] bg-rose-600 border-rose-600 hover:bg-rose-700"
              onClick={() => switchPlatform(pendingPlatform)}
            >
              放弃并切换
            </button>
          </div>
        </div>
      )}

      {/* 仅在非「未登录空状态」时展示顶部错误条，避免与空态主引导重复 */}
      {errorMessage && !isOfflineLoginEmpty && (
        <div className="wbx-deduction-alert" role="alert">
          <div className="wbx-deduction-alert__body">
            <AlertCircle size={15} aria-hidden="true" />
            <span>{errorMessage}</span>
          </div>
          {errorMessage.includes('登录') && (
            <button
              type="button"
              className="wbx-btn wbx-btn--sm wbx-btn--danger"
              onClick={() => window.dispatchEvent(new CustomEvent('workbench:connections'))}
            >
              立即登录平台
            </button>
          )}
        </div>
      )}

      {notice && (
        <p role="status" className="wb-notice">
          {notice}
        </p>
      )}

      {/* 2. 主容器一：一级「竖向城市卡片墙」 OR 二级「全宽城市扣款表格视图」 */}
      <section className="wbx-ded-workspace" aria-label="城市与站点扣款配置工作区">
        {activeCityGroup ? (
          <CityDeductionTableView
            group={activeCityGroup}
            allCitySummaries={citySummaries}
            allEntries={displayEntries}
            columns={activeColumns}
            categorySpecs={categorySpecs}
            activeCategory={activeCategory}
            visibleColumns={visibleColumns}
            selectedStations={selectedStations}
            showProblemRules={currentPlatform !== 'xiaoxiang'}
            disabled={saving}
            onBack={() => setActiveCityId(null)}
            onSelectCity={cityId => setActiveCityId(cityId)}
            onChangeCategory={cat => setActiveCategory(cat)}
            onToggleSelectStation={(key, checked) =>
              setSelectedStations(prev => {
                const next = new Set(prev);
                if (checked) next.add(key);
                else next.delete(key);
                return next;
              })
            }
            onToggleSelectAllStations={(keys, checked) =>
              setSelectedStations(prev => {
                const next = new Set(prev);
                for (const key of keys) {
                  if (checked) next.add(key);
                  else next.delete(key);
                }
                return next;
              })
            }
            onUpdateCity={updatedCity => {
              const prevCity = displayCities.find(c => c.key === updatedCity.key);
              if (
                JSON.stringify(prevCity?.problem_rules || []) !==
                JSON.stringify((updatedCity as any).problem_rules || [])
              ) {
                setProblemDirty(true);
              }
              setActiveCities(prev => prev.map(c => (c.key === updatedCity.key ? updatedCity : c)));
              setDirty(true);
              setNotice('');
            }}
            onApplyCityToStations={cityEntry => {
              setUndoEntries(displayEntries);
              const updatedEntries = applyCityAmounts(displayEntries, [cityEntry], activeColumns);
              setActiveEntries(updatedEntries);
              setDirty(true);
              setNotice(
                `已将「${cityEntry.station.city}」统一金额同步应用到同城沿用或未配置站点，核对后请点击“保存后续默认扣款”。`,
              );
            }}
            onUpdateStation={updatedStation => {
              const prevStation = displayEntries.find(e => e.key === updatedStation.key);
              if (
                JSON.stringify(prevStation?.problem_rules || []) !==
                JSON.stringify((updatedStation as any).problem_rules || [])
              ) {
                setProblemDirty(true);
              }
              setActiveEntries(prev =>
                prev.map(e => (e.key === updatedStation.key ? updatedStation : e)),
              );
              setDirty(true);
              setNotice('');
            }}
            onBulkUpdateStations={nextEntries => {
              setUndoEntries(displayEntries);
              setActiveEntries(nextEntries);
              setDirty(true);
              setNotice('已同步批量站点金额（可点击「撤销同步」回退）。');
            }}
          />
        ) : (
          <>
            {/* 紧凑搜索与筛选条（类目列筛选仅在进入城市全宽表格后展示） */}
            <div className="wbx-ded-filterbar" aria-label="城市站点筛选与操作控制">
              <div className="wbx-ded-filterbar__left">
                <div className="wbx-ded-search">
                  <Search size={13.5} className="wbx-ded-search__icon" aria-hidden="true" />
                  <input
                    className="wbx-ded-search__input"
                    aria-label="搜索城市或站点"
                    placeholder="搜索城市、站点名称或编号…"
                    value={search}
                    onChange={e => setSearch(e.target.value)}
                  />
                  {search.trim() && (
                    <button
                      type="button"
                      className="wbx-ded-search__clear"
                      aria-label="清空搜索"
                      onClick={() => setSearch('')}
                    >
                      <X size={12} />
                    </button>
                  )}
                </div>

                {citySummaries.length > 0 && (
                  <select
                    className="wb-select wbx-ded-city-select"
                    aria-label="按城市筛选扣款配置"
                    value={cityFilter}
                    onChange={event => {
                      const targetId = event.target.value;
                      setCityFilter(targetId);
                    }}
                  >
                    <option value="">全部城市 ({citySummaries.length})</option>
                    {filteredCityJumpSummaries.map(item => (
                      <option key={item.cityId} value={item.cityId}>
                        {item.cityName} · {item.configuredStations}/{item.totalStations} 站
                      </option>
                    ))}
                  </select>
                )}

                <button
                  type="button"
                  className={`wbx-ded-filter-chip${onlyUnconfigured ? ' is-active' : ''}`}
                  aria-pressed={onlyUnconfigured}
                  onClick={() => setOnlyUnconfigured(v => !v)}
                >
                  <span className="tabular-nums">仅看未配 ({pendingCount})</span>
                </button>

                <button
                  type="button"
                  className={`wbx-ded-filter-chip${onlyPendingCities ? ' is-active' : ''}`}
                  aria-pressed={onlyPendingCities}
                  onClick={() => setOnlyPendingCities(v => !v)}
                >
                  仅看待完善城市
                </button>

                {displayProfile && currentPlatform !== 'xiaoxiang' && totalProblemRules > 0 && (
                  <button
                    type="button"
                    className="wbx-ded-filter-chip"
                    onClick={() => {
                      document
                        .getElementById('ded-keyword-section')
                        ?.scrollIntoView({ behavior: 'smooth', block: 'start' });
                    }}
                  >
                    <Tag size={12} aria-hidden="true" />
                    <span className="tabular-nums">关键词扣款 ({totalProblemRules})</span>
                  </button>
                )}
              </div>

              <div className="wbx-ded-filterbar__right">
                {undoEntries && (
                  <button
                    type="button"
                    className="wbx-btn wbx-btn--sm"
                    disabled={saving}
                    onClick={() => {
                      setActiveEntries(undoEntries);
                      setUndoEntries(null);
                      setNotice('已撤销上次站点批量同步操作。');
                    }}
                  >
                    <RotateCcw size={13} aria-hidden="true" />
                    <span>撤销同步</span>
                  </button>
                )}
                {directory.data?.fetched_at && (
                  <span className="wbx-ded-updated tabular-nums">
                    更新于 {formatPayrollDateTime(directory.data.fetched_at)}
                  </span>
                )}
                <button
                  type="button"
                  className="wbx-btn wbx-btn--sm"
                  onClick={() => directory.refresh()}
                >
                  <RefreshCw size={13} aria-hidden="true" />
                  <span>刷新目录</span>
                </button>
              </div>
            </div>

            {/* 工作区主体：统一克制的空态引导 OR 竖向城市卡片墙 */}
            <div className="wbx-ded-workspace__body">
              {displayEntries.length === 0 && displayCities.length === 0 ? (
                <div className="wbx-ded-empty">
                  <span className="wbx-ded-empty__icon" aria-hidden="true">
                    <FolderCog size={20} />
                  </span>
                  <h4 className="wbx-ded-empty__title">
                    {currentPlatform === 'xiaoxiang'
                      ? '登录小象超市后同步城市与站点目录'
                      : '登录风神 / 闪购后同步城市与站点目录'}
                  </h4>
                  <p className="wbx-ded-empty__desc">
                    {currentPlatform === 'xiaoxiang'
                      ? '小象超市扣款包含保险费、循环物资使用费、附加险 3 项。完成授权同步后即可按城市默认与站点例外配置，也可先下载标准模板离线整理。'
                      : '已就绪 3 大扣款类目、共 13 项核心扣款科目（含 2 项天数阈值）。完成平台登录同步后将展开全部城市卡片，点击即可进入表格填写。'}
                  </p>
                  <div className="wbx-ded-empty__actions">
                    <button
                      type="button"
                      className="wbx-btn wbx-btn--primary wbx-btn--sm"
                      onClick={() => window.dispatchEvent(new CustomEvent('workbench:connections'))}
                    >
                      登录平台同步城市站点
                    </button>
                    <button
                      type="button"
                      className="wbx-btn wbx-btn--sm"
                      onClick={() => void handleExportConfigExcel()}
                    >
                      <FileSpreadsheet size={13.5} aria-hidden="true" />
                      <span>下载标准配置模板</span>
                    </button>
                  </div>
                </div>
              ) : cityGroups.length === 0 ? (
                <EmptyState
                  icon={FilterX}
                  title="当前筛选下没有匹配的城市或站点"
                  description="换个城市或关键词，或清除筛选查看全部城市卡片。"
                  actions={[
                    { label: '清除筛选', tone: 'primary', icon: X, onClick: clearFilters },
                  ]}
                />
              ) : (
                <div className="wbx-city-vcard-grid">
                  {cityGroups.map(group => {
                    const cityId = group.summary.cityId;
                    return (
                      <CityStationAccordionCard
                        key={cityId}
                        group={group}
                        visibleColumns={visibleColumns}
                        onOpenCity={id => setActiveCityId(id)}
                        onToggleCity={id => setActiveCityId(id)}
                      />
                    );
                  })}
                </div>
              )}
            </div>
          </>
        )}
      </section>

      {/* 3. 主容器二：问题单关键词扣款明细面板（小象超市仅 3 项扣款，不展示） */}
      {displayProfile && currentPlatform !== 'xiaoxiang' && (
        <section id="ded-keyword-section" className="wbx-problem-panel" aria-label="问题单关键词扣款明细">
          <header className="wbx-problem-panel__head">
            <div className="wbx-problem-panel__title">
              <Tag size={14.5} aria-hidden="true" />
              <strong>问题单关键词扣款明细</strong>
              <span className="wbx-problem-panel__count tabular-nums">
                当前 {visibleProblemRules.length} / 总计 {totalProblemRules} 条
              </span>
            </div>
            <span className="wbx-problem-panel__hint">
              站点关键词优先于城市默认；可通过上方「导出 / 导入配置 Excel」统一维护
            </span>
          </header>

          {problemError && <p role="alert" className="wb-error">{problemError}</p>}
          {problemNotice && <p role="status" className="wb-success">{problemNotice}</p>}

          {problemPreview && (
            <div className="wbx-problem-preview">
              <p className="wbx-hint tabular-nums">
                Excel 关键词导入比对：新增 {problemPreview.diff.added.length} 条，更新 {problemPreview.diff.updated.length} 条，
                删除 {problemPreview.diff.removed.length} 条，未变化 {problemPreview.diff.unchanged.length} 条。
              </p>
              <div className="wb-deduction-scroll">
                <table className="wb-deduction-table">
                  <thead>
                    <tr>
                      <th>变化</th>
                      <th>城市</th>
                      <th>团队名称</th>
                      <th>团队ID</th>
                      <th>问题单类型</th>
                      <th>判责原因关键词</th>
                      <th>金额</th>
                    </tr>
                  </thead>
                  <tbody>
                    {[
                      ...problemPreview.diff.added,
                      ...problemPreview.diff.updated,
                      ...problemPreview.diff.unchanged,
                      ...problemPreview.diff.removed,
                    ]
                      .slice(0, 100)
                      .map((row: any, index: number) => (
                        <tr key={`${row.action}-${row.key}-${row.problem_type}-${row.reason_keyword}-${index}`}>
                          <td>{{ added: '新增', updated: '更新', unchanged: '不变', removed: '删除' }[row.action] || row.action}</td>
                          <td>{row.city}</td>
                          <td>{row.team_name}</td>
                          <td>{row.team_id}</td>
                          <td>{row.problem_type}</td>
                          <td>{row.reason_keyword || '（整个类型）'}</td>
                          <td className="tabular-nums">
                            {row.amount}
                            {row.action === 'updated' ? `（原 ${row.previous_amount}）` : ''}
                          </td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
              <div className="wb-row gap-2 wbx-problem-preview__actions">
                <button
                  type="button"
                  className="wbx-btn wbx-btn--primary wbx-btn--sm"
                  disabled={problemBusy}
                  onClick={() => void applyProblemRules()}
                >
                  <Check size={14} />
                  {problemBusy ? '保存中…' : '确认保存关键词规则'}
                </button>
                <button
                  type="button"
                  className="wbx-btn wbx-btn--sm"
                  disabled={problemBusy}
                  onClick={() => setProblemPreview(null)}
                >
                  取消
                </button>
              </div>
            </div>
          )}

          {!problemPreview && visibleProblemRules.length > 0 && (
            <div className="wbx-problem-table-scroll">
              <table className="wbx-table wbx-problem-table">
                <thead>
                  <tr>
                    <th>城市</th>
                    <th>生效层级 / 团队</th>
                    <th>团队ID</th>
                    <th>问题单类型</th>
                    <th>判责原因关键词</th>
                    <th className="is-num">单次扣款（元）</th>
                  </tr>
                </thead>
                <tbody>
                  {visibleProblemRules.slice(0, 80).map((row, idx) => (
                    <tr key={`${row['城市']}-${row['团队ID']}-${row['问题单类型']}-${row['判责原因关键词']}-${idx}`}>
                      <td>{row['城市']}</td>
                      <td>
                        <span className={`wbx-pill ${row['团队ID'] === '*' ? 'wbx-pill--progress' : 'wbx-pill--neutral'}`}>
                          {row['团队ID'] === '*' ? '城市统一' : String(row['团队名称'])}
                        </span>
                      </td>
                      <td className="tabular-nums">
                        {row['团队ID'] === '*' ? (
                          <span className="wbx-problem-global-scope" title="城市统一适用 (*)">全城通用</span>
                        ) : (
                          row['团队ID']
                        )}
                      </td>
                      <td><strong>{row['问题单类型']}</strong></td>
                      <td>{row['判责原因关键词'] || '（整类适用）'}</td>
                      <td className="is-num tabular-nums"><strong>¥ {row['单次扣款金额']}</strong></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {!problemPreview && visibleProblemRules.length === 0 && (
            <p className="wbx-problem-panel__empty">
              暂无已配置的问题单关键词扣款配置。同步城市目录后，可在城市/站点内添加或通过 Excel 批量导入。
            </p>
          )}
        </section>
      )}

      {!inline && (
        <footer className="wb-row wb-space">
          <button className="wb-button" disabled={saving} onClick={handleRequestClose}>
            关闭
          </button>
          <button
            className="wb-primary"
            disabled={saving || !dirty || (!demoActive && directory.data?.status !== 'ready')}
            onClick={() => void handleSave()}
          >
            {saving ? '保存中…' : '保存后续默认扣款'}
          </button>
        </footer>
      )}

      {inline && hasUnsavedChanges && (
        <div className="wbx-ded-sticky-bar" role="region" aria-label="未保存的扣款配置更改">
          <div className="wbx-ded-sticky-bar__info">
            <span className="wbx-ded-sticky-bar__dot" aria-hidden="true" />
            <span>
              有未保存的扣款配置修改
              {(modifiedCityCount > 0 || modifiedStationCount > 0) && (
                <strong className="tabular-nums">
                  （{[
                    modifiedCityCount > 0 ? `${modifiedCityCount} 个城市` : '',
                    modifiedStationCount > 0 ? `${modifiedStationCount} 个站点` : '',
                    problemDirty || pendingProblemRows?.length ? '问题单关键词' : '',
                  ]
                    .filter(Boolean)
                    .join(' · ')}）
                </strong>
              )}
            </span>
          </div>
          <div className="wbx-ded-sticky-bar__actions">
            <button
              type="button"
              className="wbx-btn wbx-btn--sm wbx-btn--ghost"
              disabled={saving}
              onClick={handleDiscard}
            >
              放弃修改
            </button>
            <button
              type="button"
              className="wbx-btn wbx-btn--primary wbx-btn--sm"
              disabled={saving || (!demoActive && directory.data?.status !== 'ready')}
              onClick={() => void handleSave()}
            >
              {saving ? '保存中…' : '保存后续默认扣款'}
            </button>
          </div>
        </div>
      )}

      {confirmClose && (
        <p className="wb-notice">
          有未保存的金额调整。
          <button className="wb-button" onClick={() => setConfirmClose(false)}>
            继续编辑
          </button>
          <button className="wb-button" onClick={onClose}>
            放弃修改并关闭
          </button>
        </p>
      )}
    </>
  );

  if (inline) {
    return (
      <section className="wbx-subview wbx-deduction" aria-label="站点扣款配置">
        {content}
      </section>
    );
  }

  return (
    <WorkbenchDrawer title="站点扣款配置" wide onClose={handleRequestClose}>
      {content}
    </WorkbenchDrawer>
  );
}

