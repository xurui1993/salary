// @ts-nocheck
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { useStationDirectory } from '../lib/useStationDirectory';
import { CityStationAccordionCard } from './CityStationAccordionCard';
import { WorkbenchDrawer } from './WorkbenchDrawer';
import { EmptyState } from './EmptyState';
import {
  applyConfigRuleRows,
  applyProblemRuleRows,
  buildDeductionCategories,
  buildProblemRuleExportRows,
  buildUnifiedConfigWorkbookData,
  classifyImportedWorkbookSheets,
  CONFIG_RULE_COLUMNS_WITH_THRESHOLDS,
  columnDisplayLabel,
  groupDeductionsByCity,
  resolveCityChipAction,
  summarizeCitiesProgress,
  toggleGridCityExpansion,
  visibleColumnsForCategory,
  type DeductionCategoryId,
} from '../lib/deductionCategories';
import { applyCityAmounts } from '../lib/payrollReviewActions';
import {
  AlertCircle,
  Check,
  ChevronsDownUp,
  ChevronsUpDown,
  FileSpreadsheet,
  FilterX,
  FolderCog,
  RefreshCw,
  RotateCcw,
  Tag,
  Upload,
  X,
} from 'lucide-react';

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
  const [expandedCities, setExpandedCities] = useState<Set<string>>(new Set());
  const [expandedStations, setExpandedStations] = useState<Set<string>>(new Set());
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

  useEffect(() => {
    const controller = new AbortController();
    apiFetch(`/api/workbench/deduction-profiles/${currentPlatform}`, { signal: controller.signal })
      .then(async res => {
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || '扣款读取失败');
        if (controller.signal.aborted) return;
        setProfile((prev: any) => (dirty && prev ? prev : data));
        setEntries((prev: any[]) => {
          if (!dirty) return data.entries;
          const map = new Map(prev.map(item => [item.key, item]));
          return data.entries.map((item: any) => map.get(item.key) || item);
        });
        setCities((prev: any[]) => (dirty ? prev : data.cities || []));
        setError('');
      })
      .catch(err => {
        if (controller.signal.aborted) return;
        setError(readErrorMessage(err, '扣款配置读取失败，请检查后台连接后重试'));
      });
    return () => controller.abort();
  }, [currentPlatform, directory.data?.stations.length, directory.data?.fetched_at, directory.data?.status, reloadKey, dirty]);

  const effectiveDirectoryCities = useMemo(
    () => directory.data?.cities || [],
    [directory.data?.cities],
  );

  const activeColumns: string[] = useMemo(
    () => (profile?.columns?.length ? profile.columns : [...CONFIG_RULE_COLUMNS_WITH_THRESHOLDS]),
    [profile?.columns],
  );

  const categorySpecs = useMemo(
    () => buildDeductionCategories(activeColumns),
    [activeColumns],
  );

  const visibleColumns = useMemo(
    () => visibleColumnsForCategory(activeColumns, activeCategory),
    [activeColumns, activeCategory],
  );

  const citySummaries = useMemo(
    () => summarizeCitiesProgress(cities, entries, effectiveDirectoryCities),
    [cities, entries, effectiveDirectoryCities],
  );

  const cityGroups = useMemo(
    () =>
      groupDeductionsByCity(cities, entries, effectiveDirectoryCities, {
        cityFilter,
        citySearch,
        stationSearch: search,
        onlyPendingCities,
        onlyUnconfigured,
      }),
    [cities, entries, effectiveDirectoryCities, cityFilter, citySearch, search, onlyPendingCities, onlyUnconfigured],
  );

  useEffect(() => {
    if (!cities.length && !entries.length) return;
    const firstCityId = cities[0]?.station?.city_id || entries[0]?.station?.city_id || '';
    if (!firstCityId) return;
    const signature = `${currentPlatform}:${firstCityId}:${entries.length > 0 ? '1' : '0'}`;
    if (initializedExpandRef.current !== signature) {
      initializedExpandRef.current = signature;
      setExpandedCities(new Set());
      setExpandedStations(new Set());
    }
  }, [cities, entries, currentPlatform]);

  useEffect(() => {
    if (search.trim()) {
      setExpandedCities(new Set(cityGroups.map(g => g.summary.cityId)));
      setExpandedStations(
        new Set(cityGroups.flatMap(g => g.stations.slice(0, 6).map(s => s.key))),
      );
    }
  }, [search, cityGroups]);

  const pendingCount = entries.filter(item => !item.configured).length;
  const configuredCount = entries.length - pendingCount;
  const allCitiesExpanded =
    cityGroups.length > 0 && cityGroups.every(g => expandedCities.has(g.summary.cityId));

  const clearFilters = () => {
    setCityFilter('');
    setCitySearch('');
    setSearch('');
    setOnlyUnconfigured(false);
    setOnlyPendingCities(false);
    setExpandedCities(new Set());
    setExpandedStations(new Set());
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
    setExpandedCities(new Set());
    setExpandedStations(new Set());
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

  async function handleSave() {
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
      const workbook = buildUnifiedConfigWorkbookData(cities, entries, activeColumns);
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
          ? '小象超市扣款规则配置.xlsx'
          : `站点扣款规则配置_${currentPlatform}.xlsx`,
      );
      setNotice(
        currentPlatform === 'xiaoxiang'
          ? `已导出小象超市扣款配置：包含「${workbook.itemSheetName}」${workbook.itemRows.length} 行。`
          : entries.length > 0
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
      if (!profile || (!cities.length && !entries.length)) {
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

      let nextCities = cities;
      let nextEntries = entries;
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

        if (itemRows.length === 0) {
          const res = await apiFetch(`/api/workbench/deduction-profiles/${currentPlatform}/problem-rules/preview`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ version: profile.version, rows: problemRows }),
          });
          const data = await res.json();
          if (!res.ok) throw new Error(data.detail || '问题单扣款规则预览失败');
          setProblemPreview(data);
        }
      }

      setCities(nextCities);
      setEntries(nextEntries);
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
      if (!res.ok) throw new Error(data.detail || '问题单扣款规则保存失败');
      setProfile((prev: any) => ({ ...prev, version: data.version, problem_rules: data.problem_rules || {} }));
      setProblemPreview(null);
      setPendingProblemRows(null);
      setDirty(false);
      setProblemNotice('问题单关键词扣款规则已保存。');
      setReloadKey(value => value + 1);
      onSaved();
    } catch (err) {
      setProblemError(readErrorMessage(err, '问题单扣款规则保存失败'));
    } finally {
      setProblemBusy(false);
    }
  };

  const handleRequestClose = () => {
    if (dirty) setConfirmClose(true);
    else onClose?.();
  };

  const errorMessage = String(
    error ||
      (directory.error ? readErrorMessage(directory.error, '扣款配置读取失败，请检查后台连接后重试') : '') ||
      directory.data?.message ||
      '',
  );

  const visibleProblemRules = useMemo(() => {
    const visibleCityIds = new Set(cityGroups.map(g => g.summary.cityId));
    const filteredCities = cities.filter(c => visibleCityIds.has(c.station.city_id));
    const filteredEntries = entries.filter(e => visibleCityIds.has(e.station.city_id));
    return buildProblemRuleExportRows(filteredCities, filteredEntries);
  }, [cities, entries, cityGroups]);

  const totalProblemRules =
    cities.reduce((sum: number, city: any) => sum + (city.problem_rules?.length || 0), 0) +
    entries.reduce((sum: number, entry: any) => sum + (entry.problem_rules?.length || 0), 0);

  const filteredCityJumpSummaries = useMemo(() => {
    const q = citySearch.trim().toLowerCase();
    return citySummaries.filter(item => {
      if (onlyPendingCities && item.pendingStations === 0) return false;
      if (q && !item.cityName.toLowerCase().includes(q) && !item.cityId.toLowerCase().includes(q)) return false;
      return true;
    });
  }, [citySummaries, citySearch, onlyPendingCities]);

  const content = (
    <>
      {/* 1. 顶部操作卡 */}
      <div className="wbx-toolbar wbx-deduction-head">
        <div className="wbx-toolbar__lead wbx-deduction-head__lead">
          <div>
            <h3 className="wbx-deduction-head__title">
              {currentPlatform === 'xiaoxiang' ? '小象超市扣款规则配置' : '站点扣款规则配置'}
            </h3>
            <p className="wbx-hint tabular-nums">
              {citySummaries.length} 城 / {entries.length} 站 · 已配 {configuredCount} · 待配 {pendingCount} ·{' '}
              {currentPlatform === 'xiaoxiang' ? '小象超市' : '风神/闪购'}（{activeColumns.length} 项）
            </p>
          </div>
          <div className="wbx-row gap-2 items-center">
            <div className="wb-segment" role="group" aria-label="扣款业务切换">
              <button
                type="button"
                aria-pressed={currentPlatform === 'fengshen'}
                disabled={saving}
                onClick={() => requestPlatform('fengshen')}
              >
                风神
              </button>
              <button
                type="button"
                aria-pressed={currentPlatform === 'xiaoxiang'}
                disabled={saving}
                onClick={() => requestPlatform('xiaoxiang')}
              >
                小象超市
              </button>
            </div>
            {dirty && <span className="wbx-hint">有未保存修改</span>}
          </div>
        </div>
        <div className="wbx-toolbar__actions">
          <button
            type="button"
            className="wbx-btn wbx-btn--sm"
            disabled={saving}
            title={currentPlatform === 'xiaoxiang'
              ? '支持导入含「城市与站点扣款项」的 Excel（保险费/循环物资使用费/附加险）'
              : '支持导入含「城市与站点扣款项」及「问题单关键词扣款」的多表 Excel（.xlsx/.xls）'}
            onClick={() => configUpload.current?.click()}
          >
            <Upload size={14} />
            导入配置 Excel
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
            <FileSpreadsheet size={14} />
            导出配置 Excel
          </button>
          <button
            className="wbx-btn wbx-btn--primary"
            disabled={saving || !dirty || directory.data?.status !== 'ready'}
            onClick={() => void handleSave()}
          >
            {saving ? '保存中…' : '保存后续默认扣款'}
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

      {errorMessage && (
        <div className="wbx-deduction-alert" role="alert">
          <div className="wbx-deduction-alert__body">
            <AlertCircle size={15} />
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

      {/* 2. 单行扣款项类目切换条（替代原重复标签+大卡两层结构） */}
      <section className="wbx-category-strip" aria-label="切换扣款项类目">
        <button
          type="button"
          className={`wbx-category-card is-all ${activeCategory === 'all' ? 'is-active' : ''}`}
          onClick={() => setActiveCategory('all')}
        >
          <div className="wbx-category-card__head">
            <strong>全部类目</strong>
            <span className="tabular-nums">{activeColumns.length} 项</span>
          </div>
          <p className="wbx-category-card__fields">
            展示全部 {categorySpecs.length} 个类目扣款金额{currentPlatform === 'xiaoxiang' ? '' : '与天数阈值'}
          </p>
        </button>
        {categorySpecs.map(cat => {
          const isSelected = activeCategory === cat.id;
          return (
            <button
              key={cat.id}
              type="button"
              className={`wbx-category-card ${isSelected ? 'is-active' : ''}`}
              onClick={() => setActiveCategory(prev => (prev === cat.id ? 'all' : cat.id))}
            >
              <div className="wbx-category-card__head">
                <strong>{cat.label}</strong>
                <span className="tabular-nums">{cat.columns.length} 项 · {cat.unitHint}</span>
              </div>
              <p className="wbx-category-card__fields">
                {cat.columns.map(col => columnDisplayLabel(col)).join(' · ')}
              </p>
            </button>
          );
        })}
      </section>

      {/* 3. 城市与站点层级精简工具栏 + 20城快选矩阵 */}
      <section className="wbx-hierarchy-toolbar" aria-label="城市站点筛选与层级控制">
        <div className="wbx-hierarchy-toolbar__row">
          <div className="wbx-hierarchy-toolbar__filters">
            <input
              className="wb-input wbx-hierarchy-search"
              aria-label="搜索城市或站点"
              placeholder="搜索城市、站点名称或编号..."
              value={search}
              onChange={e => setSearch(e.target.value)}
            />
            <button
              type="button"
              className={`wbx-btn wbx-btn--sm ${onlyUnconfigured ? 'wbx-btn--primary' : ''}`}
              aria-pressed={onlyUnconfigured}
              onClick={() => setOnlyUnconfigured(v => !v)}
            >
              <span className="tabular-nums">
                {onlyUnconfigured ? `仅看未配 (${pendingCount})` : `仅看未配 (${pendingCount})`}
              </span>
            </button>
            <button
              type="button"
              className={`wbx-btn wbx-btn--sm ${onlyPendingCities ? 'wbx-btn--primary' : ''}`}
              aria-pressed={onlyPendingCities}
              onClick={() => setOnlyPendingCities(v => !v)}
            >
              仅看待完善城市
            </button>
          </div>

          <div className="wbx-hierarchy-toolbar__actions">
            {undoEntries && (
              <button
                type="button"
                className="wbx-btn wbx-btn--sm"
                disabled={saving}
                onClick={() => {
                  setEntries(undoEntries);
                  setUndoEntries(null);
                  setNotice('已撤销上次站点批量同步操作。');
                }}
              >
                <RotateCcw size={13} />
                撤销同步
              </button>
            )}
            {cityGroups.length > 0 && (
              <button
                type="button"
                className="wbx-btn wbx-btn--sm"
                onClick={() => {
                  if (allCitiesExpanded) {
                    setExpandedCities(new Set());
                  } else {
                    setExpandedCities(new Set(cityGroups.map(g => g.summary.cityId)));
                  }
                }}
              >
                {allCitiesExpanded ? <ChevronsDownUp size={13} /> : <ChevronsUpDown size={13} />}
                {allCitiesExpanded ? '收起全部城市' : '展开全部城市'}
              </button>
            )}
            {directory.data?.fetched_at && (
              <span className="wbx-hint wbx-deduction-updated tabular-nums">
                更新于 {new Date(directory.data.fetched_at).toLocaleString('zh-CN')}
              </span>
            )}
            <button
              className="wbx-btn wbx-btn--sm"
              onClick={() => directory.refresh()}
            >
              <RefreshCw size={13} />
              刷新目录
            </button>
          </div>
        </div>

        {citySummaries.length > 0 && (
          <div className="wbx-city-jump-strip" aria-label="城市快速定位">
            <button
              type="button"
              className={`wbx-city-jump-chip ${cityFilter === '' ? 'is-active' : ''}`}
              onClick={() => {
                const { nextCityFilter, nextExpandedCities } = resolveCityChipAction(cityFilter, '');
                setCityFilter(nextCityFilter);
                setExpandedCities(nextExpandedCities);
                setExpandedStations(new Set());
              }}
            >
              <strong>全部 ({citySummaries.length})</strong>
            </button>
            {filteredCityJumpSummaries.map(item => {
              const active = cityFilter === item.cityId;
              const isComplete = item.totalStations > 0 && item.pendingStations === 0;
              return (
                <button
                  key={item.cityId}
                  type="button"
                  className={`wbx-city-jump-chip ${active ? 'is-active' : ''} ${isComplete ? 'is-complete' : 'is-pending'}`}
                  onClick={() => {
                    const { nextCityFilter, nextExpandedCities } = resolveCityChipAction(cityFilter, item.cityId);
                    setCityFilter(nextCityFilter);
                    setExpandedCities(nextExpandedCities);
                    if (nextCityFilter) {
                      const cityStations = entries.filter(e => e.station.city_id === nextCityFilter);
                      if (cityStations.length > 0) {
                        setExpandedStations(prev => {
                          if (cityStations.some(s => prev.has(s.key))) return prev;
                          const next = new Set(prev);
                          next.add(cityStations[0].key);
                          return next;
                        });
                      }
                    } else {
                      setExpandedStations(new Set());
                    }
                  }}
                >
                  <strong>{item.cityName}</strong>
                  <span className="tabular-nums">
                    {item.configuredStations}/{item.totalStations}
                  </span>
                </button>
              );
            })}
          </div>
        )}
      </section>

      {notice && (
        <p role="status" className="wb-notice">
          {notice}
        </p>
      )}

      {/* 4. 主体卡片区：未登录引导 OR 14+城市紧凑折叠面板列表 */}
      {entries.length === 0 && cities.length === 0 ? (
        <section className="wbx-panel wbx-deduction-offline-panel">
          <EmptyState
            icon={FolderCog}
            title={currentPlatform === 'xiaoxiang' ? '等待读取小象超市城市与站点目录' : '等待读取平台城市与站点目录'}
            description={currentPlatform === 'xiaoxiang'
              ? '小象超市扣款规则包含保险费、循环物资使用费、附加险 3 项。登录小象平台并同步目录后，将按「城市折叠面板 → 站点分组卡片」展开城市与下属站点。'
              : '已按标准 config 规则模板就绪 3 大扣款类目卡片、共 13 个配置字段。登录风神/闪购平台并同步目录后，将按「城市折叠面板 → 站点分组卡片」展开全部 14+ 城市与下属站点。'}
            actions={[
              {
                label: '登录平台同步城市站点',
                tone: 'primary',
                onClick: () => window.dispatchEvent(new CustomEvent('workbench:connections')),
              },
              {
                label: '下载标准配置模板',
                onClick: () => void handleExportConfigExcel(),
              },
            ]}
          />
        </section>
      ) : cityGroups.length === 0 ? (
        <section className="wbx-panel wbx-deduction-offline-panel">
          <EmptyState
            icon={FilterX}
            title="当前筛选下没有匹配的城市或站点"
            description="换个城市或关键词，或清除筛选查看全部城市与站点卡片。"
            actions={[
              { label: '清除筛选', tone: 'primary', icon: X, onClick: clearFilters },
            ]}
          />
        </section>
      ) : (
        <div className="wbx-city-accordion-list is-grid">
          {cityGroups.map(group => {
            const cityId = group.summary.cityId;
            return (
              <CityStationAccordionCard
                key={cityId}
                group={group}
                allEntries={entries}
                columns={activeColumns}
                activeCategory={activeCategory}
                visibleColumns={visibleColumns}
                expanded={expandedCities.has(cityId)}
                expandedStations={expandedStations}
                selectedStations={selectedStations}
                disabled={saving}
                onToggleCity={id => {
                  const willOpen = !expandedCities.has(id);
                  setExpandedCities(prev => toggleGridCityExpansion(prev, id));
                  if (willOpen) {
                    const cityStations = entries.filter(e => e.station.city_id === id);
                    if (cityStations.length > 0) {
                      setExpandedStations(prev => {
                        if (cityStations.some(s => prev.has(s.key))) return prev;
                        const next = new Set(prev);
                        next.add(cityStations[0].key);
                        return next;
                      });
                    }
                  }
                }}
                onToggleStation={key =>
                  setExpandedStations(prev => {
                    const next = new Set(prev);
                    if (next.has(key)) next.delete(key);
                    else next.add(key);
                    return next;
                  })
                }
                onToggleAllCityStations={(keys, open) =>
                  setExpandedStations(prev => {
                    const next = new Set(prev);
                    for (const k of keys) {
                      if (open) next.add(k);
                      else next.delete(k);
                    }
                    return next;
                  })
                }
                onToggleSelectStation={(key, checked) =>
                  setSelectedStations(prev => {
                    const next = new Set(prev);
                    if (checked) next.add(key);
                    else next.delete(key);
                    return next;
                  })
                }
                onUpdateCity={updatedCity => {
                  const prevCity = cities.find(c => c.key === updatedCity.key);
                  if (
                    JSON.stringify(prevCity?.problem_rules || []) !==
                    JSON.stringify((updatedCity as any).problem_rules || [])
                  ) {
                    setProblemDirty(true);
                  }
                  setCities(prev => prev.map(c => (c.key === updatedCity.key ? updatedCity : c)));
                  setDirty(true);
                  setNotice('');
                }}
                onApplyCityToStations={cityEntry => {
                  setUndoEntries(entries);
                  const updatedEntries = applyCityAmounts(entries, [cityEntry], activeColumns);
                  setEntries(updatedEntries);
                  setDirty(true);
                  setNotice(
                    `已将「${cityEntry.station.city}」统一金额同步应用到同城沿用或未配置站点，核对后请点击“保存后续默认扣款”。`,
                  );
                }}
                onUpdateStation={updatedStation => {
                  const prevStation = entries.find(e => e.key === updatedStation.key);
                  if (
                    JSON.stringify(prevStation?.problem_rules || []) !==
                    JSON.stringify((updatedStation as any).problem_rules || [])
                  ) {
                    setProblemDirty(true);
                  }
                  setEntries(prev =>
                    prev.map(e => (e.key === updatedStation.key ? updatedStation : e)),
                  );
                  setDirty(true);
                  setNotice('');
                }}
                onBulkUpdateStations={nextEntries => {
                  setUndoEntries(entries);
                  setEntries(nextEntries);
                  setDirty(true);
                  setNotice('已同步批量站点金额（可通过上方“撤销同步”回退）。');
                }}
              />
            );
          })}
        </div>
      )}

      {/* 5. 问题单关键词扣款汇总面板（小象超市仅 3 项扣款，不展示） */}
      {profile && currentPlatform !== 'xiaoxiang' && (
        <section className="wbx-problem-panel" aria-label="问题单关键词扣款明细">
          <header className="wbx-problem-panel__head">
            <div className="wbx-problem-panel__title">
              <Tag size={15} />
              <strong>问题单关键词扣款明细</strong>
              <span className="wbx-pill wbx-pill--neutral tabular-nums">
                当前显示 {visibleProblemRules.length} 条 / 总计 {totalProblemRules} 条
              </span>
            </div>
            <span className="wbx-hint">
              站点关键词优先于城市默认；可通过上方「导出配置 Excel / 导入配置 Excel」一次性维护扣款项与关键词工作表。
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
                    <th>单次扣款（元）</th>
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
                      <td className="tabular-nums">{row['团队ID']}</td>
                      <td><strong>{row['问题单类型']}</strong></td>
                      <td>{row['判责原因关键词'] || '（整类适用）'}</td>
                      <td className="tabular-nums"><strong>{row['单次扣款金额']}</strong></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
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
            disabled={saving || !dirty || directory.data?.status !== 'ready'}
            onClick={() => void handleSave()}
          >
            {saving ? '保存中…' : '保存后续默认扣款'}
          </button>
        </footer>
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

