// @ts-nocheck
import React, { useEffect, useRef, useState } from 'react';
import { stationCountText, useStationDirectory } from '../lib/useStationDirectory';
import { CityDeductionAmounts } from './CityDeductionAmounts';
import { DeductionAmounts } from './DeductionAmounts';
import { WorkbenchDrawer } from './WorkbenchDrawer';
import { EmptyState } from './EmptyState';
import { AlertCircle, Check, Download, FilterX, Upload, X } from 'lucide-react';

/**
 * 错误文案归一（A3）：浏览器原生网络错误与超时统一为中文，
 * 其余（尤其是后端返回的业务错误）原样透出，绝不吞掉。
 *
 * @param err 任意捕获值。
 * @param networkFallback 网络类错误的兜底文案。
 * @returns 面向用户的中文文案。
 */
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
  const [profile, setProfile] = useState<any>(null);
  const [entries, setEntries] = useState<any[]>([]);
  const [cities, setCities] = useState<any[]>([]);
  const [cityFilter, setCityFilter] = useState('');
  const [search, setSearch] = useState('');
  const [onlyUnconfigured, setOnlyUnconfigured] = useState(false);
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
  const problemUpload = useRef<HTMLInputElement>(null);

  const directory = useStationDirectory(currentPlatform, apiFetch);
  const exceptionsRef = useRef(null);
  const exceptionsAutoOpened = useRef(false);

  useEffect(() => {
    const controller = new AbortController();
    apiFetch(`/api/workbench/deduction-profiles/${currentPlatform}`, { signal: controller.signal })
      .then(async res => {
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || '扣款读取失败');
        if (!controller.signal.aborted) {
          setProfile((prev: any) => (dirty && prev ? prev : data));
          setEntries((prev: any[]) => {
            if (!dirty) return data.entries;
            const map = new Map(prev.map(item => [item.key, item]));
            return data.entries.map((item: any) => map.get(item.key) || item);
          });
          setCities((prev: any[]) => (dirty ? prev : data.cities || []));
          setError('');
        }
      })
      .catch(err => {
        if (!controller.signal.aborted) setError(readErrorMessage(err, '扣款配置读取失败，请检查后台连接后重试'));
      });
    return () => controller.abort();
  }, [currentPlatform, directory.data?.stations.length, directory.data?.fetched_at, reloadKey, dirty]);

  const pendingCount = entries.filter(item => !item.configured).length;
  // 城市 / 关键词 / 待配置三层筛选叠加，命中数先算再截断，避免「当前 N」被 100 条上限误导
  const matchedEntries = entries.filter(
    item =>
      (!cityFilter || item.station.city_id === cityFilter) &&
      (!onlyUnconfigured || !item.configured) &&
      `${item.station.name} ${item.station.id} ${item.station.city}`.includes(search.trim()),
  );
  const filteredEntries = matchedEntries.slice(0, 100);
  const clearFilters = () => {
    setCityFilter('');
    setSearch('');
    setOnlyUnconfigured(false);
  };

  async function handleSave() {
    if (!profile) return;
    setSaving(true);
    setError('');
    try {
      const editedEntries = entries.filter(item => item.edited);
      const editedCities = cities.filter(item => item.edited);
      if (!editedEntries.length && !editedCities.length) {
        throw new Error('请先配置金额，或明确确认零扣款');
      }
      const res = await apiFetch(`/api/workbench/deduction-profiles/${currentPlatform}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          version: profile.version,
          entries: editedEntries,
          cities: editedCities,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || '保存失败');
      setProfile({ ...profile, version: data.version });
      setDirty(false);
      setReloadKey(val => val + 1);
      setNotice('默认扣款已保存，后续核算按站点例外优先、城市默认其次沿用。');
      onSaved();
    } catch (err) {
      setError(readErrorMessage(err, '保存失败，请检查后台连接后重试'));
    } finally {
      setSaving(false);
    }
  }

  const problemExportRows = () => {
    const headers = ['城市', '团队名称', '团队ID', '问题单类型', '判责原因关键词', '单次扣款金额'];
    const rows: Record<string, any>[] = [];
    for (const city of cities) {
      for (const rule of city.problem_rules || []) {
        rows.push({ 城市: city.station.city, 团队名称: '城市统一扣款', 团队ID: '*',
          问题单类型: rule.problem_type, 判责原因关键词: rule.reason_keyword, 单次扣款金额: rule.amount });
      }
    }
    for (const entry of entries) {
      for (const rule of entry.problem_rules || []) {
        rows.push({ 城市: entry.station.city, 团队名称: entry.station.name, 团队ID: entry.station.id,
          问题单类型: rule.problem_type, 判责原因关键词: rule.reason_keyword, 单次扣款金额: rule.amount });
      }
    }
    return { headers, rows };
  };

  const exportProblemRules = async () => {
    try {
      const XLSX = await import('xlsx');
      const { headers, rows } = problemExportRows();
      const book = XLSX.utils.book_new();
      const sheet = rows.length ? XLSX.utils.json_to_sheet(rows, { header: headers }) : XLSX.utils.aoa_to_sheet([headers]);
      XLSX.utils.book_append_sheet(book, sheet, '问题单扣款规则');
      XLSX.writeFile(book, `问题单扣款规则_${currentPlatform}.xlsx`);
      setProblemError('');
    } catch (err) {
      setProblemError(readErrorMessage(err, '导出问题单扣款规则失败'));
    }
  };

  const importProblemRules = async (file: File) => {
    setProblemBusy(true);
    setProblemError('');
    setProblemNotice('');
    setProblemPreview(null);
    try {
      let rows: unknown;
      if (/\.json$/i.test(file.name)) {
        const value = JSON.parse(await file.text());
        rows = Array.isArray(value) ? value : value?.rows;
      } else {
        const XLSX = await import('xlsx');
        const book = XLSX.read(await file.arrayBuffer(), { type: 'array' });
        const sheet = book.Sheets[book.SheetNames[0]];
        rows = XLSX.utils.sheet_to_json(sheet, { raw: true, defval: null });
      }
      if (!Array.isArray(rows) || !rows.length) throw new Error('导入文件没有可用的规则行');
      const res = await apiFetch(`/api/workbench/deduction-profiles/${currentPlatform}/problem-rules/preview`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ version: profile.version, rows }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || '问题单扣款规则预览失败');
      setProblemPreview(data);
    } catch (err) {
      setProblemError(readErrorMessage(err, '问题单扣款规则导入失败，请检查文件格式'));
    } finally {
      setProblemBusy(false);
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
      setProblemNotice('问题单扣款规则已保存，后续核算按站点规则优先于城市默认。');
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

  /** 错误提示单一来源：接口错误 / 目录错误 / 目录 message 三选一。 */
  const errorMessage = String(error || (directory.error ? readErrorMessage(directory.error, '扣款配置读取失败，请检查后台连接后重试') : '') || directory.data?.message || '');

  const content = (
    <>
      {/* @wbx:deduction-head 警示与主按钮同一水平带（V7） */}
      <div className="wbx-toolbar wbx-deduction-head">
        <div className="wbx-toolbar__lead wbx-deduction-head__lead">
          <div>
            <h3 className="wbx-deduction-head__title">站点扣款默认规则配置</h3>
            <p className="wbx-hint">
              城市与站点自动读取后台目录；刷新保留金额。新站点需填写金额或明确确认零扣款。
            </p>
          </div>
        </div>
        {errorMessage && (
          <div className="wbx-toolbar__alert wbx-deduction-head__alert" role="alert">
            <AlertCircle size={14} />
            <span className="wbx-deduction-head__alert-text">{errorMessage}</span>
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
        <div className="wbx-toolbar__actions">
          <button
            className="wbx-btn wbx-btn--primary"
            disabled={saving || !dirty || directory.data?.status !== 'ready'}
            onClick={() => void handleSave()}
          >
            {saving ? '保存中…' : '保存后续默认扣款'}
          </button>
        </div>
      </div>
      <div className="wb-deduction-filter-bar wbx-deduction-filters">
        <div className="wb-deduction-filter-left">
          <label className="wb-deduction-filter-field">
            <span>平台</span>
            <select
              className="wb-select"
              aria-label="扣款平台"
              value={currentPlatform}
              disabled={dirty || saving}
              onChange={e => {
                setCurrentPlatform(e.target.value as 'fengshen' | 'xiaoxiang');
                setCityFilter('');
                setProfile(null);
                setEntries([]);
                setNotice('');
                setProblemPreview(null);
                setProblemError('');
                setProblemNotice('');
              }}
            >
              <option value="fengshen">风神 / 闪购</option>
              <option value="xiaoxiang">小象超市</option>
            </select>
          </label>
          <label className="wb-deduction-filter-field">
            <span>城市</span>
            <select
              className="wb-select"
              aria-label="扣款城市"
              value={cityFilter}
              onChange={e => setCityFilter(e.target.value)}
            >
              <option value="">全部城市</option>
              {directory.data?.cities.map((c: any) => (
                <option key={c.id} value={c.id}>
                  {c.name} · {stationCountText(directory.data, c.id)}
                </option>
              ))}
            </select>
          </label>
          <input
            className="wb-input wb-deduction-search-input"
            aria-label="搜索扣款站点"
            placeholder="搜索站点名称或编号"
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
        </div>
        <div className="wb-deduction-filter-right">
          {directory.data?.status === 'loading' ? (
            <span className="wbx-pill wbx-pill--progress tabular-nums">后台站点同步中…</span>
          ) : (
            <button
              type="button"
              className={`wbx-pill ${onlyUnconfigured ? 'wbx-pill--warn' : 'wbx-pill--neutral'} wbx-deduction-stat tabular-nums`}
              aria-pressed={onlyUnconfigured}
              title={onlyUnconfigured ? '点击恢复全部站点' : '点击只看待配置站点'}
              onClick={() => setOnlyUnconfigured(value => !value)}
            >
              <span>待配置 {pendingCount} / {entries.length}</span>
              <span className="wbx-deduction-stat__now">当前 {matchedEntries.length} / {entries.length}</span>
            </button>
          )}
          {directory.data?.fetched_at && (
            <span className="wbx-hint wbx-deduction-updated tabular-nums">
              更新于 {new Date(directory.data.fetched_at).toLocaleString('zh-CN')}
            </span>
          )}
          <button className="wbx-btn wbx-btn--sm" onClick={directory.refresh}>
            刷新目录
          </button>
        </div>
      </div>

      {notice && (
        <p role="status" className="wb-notice">
          {notice}
        </p>
      )}

      {/* P0-1：≥1280 两栏（城市 1fr / 例外 1.4fr），≤1279 上下堆叠 */}
      <div className="wbx-deduction-columns">
      {profile && (
        <section className="wbx-card wbx-deduction-city">
          <h3>城市统一扣款</h3>
          <p className="wb-muted">
            选择城市后填写一次，普通与取分离站点共同沿用；已保存的站点例外优先。
          </p>
          {cityFilter ? (
            <CityDeductionAmounts
              entries={cities.filter(item => item.station.city_id === cityFilter)}
              columns={profile.columns}
              disabled={saving}
              onChange={updated => {
                const map = new Map(updated.map(item => [item.key, item]));
                setCities(prev => prev.map(item => map.get(item.key) || item));
                setDirty(true);
                setNotice('');
              }}
            />
          ) : (
            <p className="wbx-hint">请先选择一个城市配置默认金额。</p>
          )}
        </section>
      )}

      {profile && (
        <section className="wbx-panel wbx-deduction-problem">
          <div className="wb-row wb-space">
            <div>
              <h3>问题单扣款规则</h3>
              <p className="wb-muted">
                按问题类型与判责原因关键词维护单次扣款金额；站点规则优先于城市默认。导入后先预览差异，再确认保存。
              </p>
            </div>
            <div className="wb-row gap-2">
              <button type="button" className="wb-button" disabled={problemBusy || dirty || saving}
                onClick={() => void exportProblemRules()}>
                <Download size={15} />导出规则
              </button>
              <button type="button" className="wb-button" disabled={problemBusy || dirty || saving || directory.data?.status !== 'ready'}
                onClick={() => problemUpload.current?.click()}>
                <Upload size={15} />导入规则
              </button>
            </div>
          </div>
          <p className="wbx-hint">
            当前已配置 {cities.reduce((sum: number, city: any) => sum + (city.problem_rules?.length || 0), 0) +
              entries.reduce((sum: number, entry: any) => sum + (entry.problem_rules?.length || 0), 0)} 条规则
            {(dirty || saving) && '；请先保存或放弃当前站点金额修改，再导入问题单规则'}
          </p>
          {problemError && <p role="alert" className="wb-error">{problemError}</p>}
          {problemNotice && <p role="status" className="wb-success">{problemNotice}</p>}
          {problemPreview && (
            <div className="wbx-problem-preview">
              <p className="wbx-hint">
                新增 {problemPreview.diff.added.length} 条，更新 {problemPreview.diff.updated.length} 条，
                删除 {problemPreview.diff.removed.length} 条，未变化 {problemPreview.diff.unchanged.length} 条。
                确认后将用导入文件整体替换当前问题单扣款规则。
              </p>
              <div className="wb-deduction-scroll">
                <table className="wb-deduction-table">
                  <thead>
                    <tr><th>变化</th><th>城市</th><th>团队名称</th><th>团队ID</th><th>问题单类型</th><th>判责原因关键词</th><th>金额</th></tr>
                  </thead>
                  <tbody>
                    {[...problemPreview.diff.added, ...problemPreview.diff.updated, ...problemPreview.diff.unchanged,
                     ...problemPreview.diff.removed].slice(0, 100).map((row: any, index: number) => (
                      <tr key={`${row.action}-${row.key}-${row.problem_type}-${row.reason_keyword}-${index}`}>
                        <td>{{ added: '新增', updated: '更新', unchanged: '不变', removed: '删除' }[row.action] || row.action}</td>
                        <td>{row.city}</td>
                        <td>{row.team_name}</td>
                        <td>{row.team_id}</td>
                        <td>{row.problem_type}</td>
                        <td>{row.reason_keyword || '（整个类型）'}</td>
                        <td>{row.amount}{row.action === 'updated' ? `（原 ${row.previous_amount}）` : ''}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="wb-row gap-2" style={{ marginTop: 8 }}>
                <button type="button" className="wb-primary" disabled={problemBusy}
                  onClick={() => void applyProblemRules()}>
                  <Check size={15} />{problemBusy ? '保存中…' : '确认保存规则'}
                </button>
                <button type="button" className="wb-button" disabled={problemBusy}
                  onClick={() => setProblemPreview(null)}>
                  取消
                </button>
              </div>
            </div>
          )}
          <input ref={problemUpload} type="file" accept=".xlsx,.xls,.json" className="hidden"
            aria-label="导入问题单扣款规则"
            onChange={event => {
              const file = event.target.files?.[0];
              event.target.value = '';
              if (file) void importProblemRules(file);
            }} />
        </section>
      )}

      {profile && matchedEntries.length === 0 && (
        <EmptyState
          icon={FilterX}
          title="当前筛选下没有站点"
          description="换个城市或关键词，或清除筛选查看全部站点。"
          actions={[
            { label: '清除筛选', tone: 'primary', icon: X, onClick: clearFilters },
          ]}
        />
      )}
      {profile && matchedEntries.length > 0 && (
        <details ref={el => { exceptionsRef.current = el; if (el && !exceptionsAutoOpened.current) { el.open = true; exceptionsAutoOpened.current = true; } }} className="wbx-card wbx-disclosure wbx-deduction-exceptions" open={onlyUnconfigured || undefined}>
          <summary>站点例外配置（按需展开，共 {matchedEntries.length} 个匹配站点）</summary>
          <DeductionAmounts
            entries={filteredEntries}
            columns={profile.columns}
            disabled={saving}
            onChange={updated => {
              const map = new Map(updated.map(item => [item.key, item]));
              setEntries(prev => prev.map(item => map.get(item.key) || item));
              setDirty(true);
              setNotice('');
            }}
          />
        </details>
      )}
      </div>

      {matchedEntries.length > 100 && (
        <p className="wbx-hint">当前显示前 100 个匹配站点（共 {matchedEntries.length} 个），请按城市或名称继续筛选。</p>
      )}
      <p className="wbx-hint">后台暂不可见的历史配置继续保留，不自动删除。</p>

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
