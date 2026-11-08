// @ts-nocheck
import React, { useEffect, useState } from 'react';
import { stationCountText, useStationDirectory } from '../lib/useStationDirectory';
import { CityDeductionAmounts } from './CityDeductionAmounts';
import { DeductionAmounts } from './DeductionAmounts';
import { WorkbenchDrawer } from './WorkbenchDrawer';

export function StationDeductionManager({
  apiFetch,
  platform = 'fengshen',
  onClose,
  onSaved,
}: {
  apiFetch: (url: string, init?: RequestInit) => Promise<Response>;
  platform?: 'fengshen' | 'xiaoxiang';
  onClose: () => void;
  onSaved: () => void;
}) {
  const [currentPlatform, setCurrentPlatform] = useState<'fengshen' | 'xiaoxiang'>(platform);
  const [profile, setProfile] = useState<any>(null);
  const [entries, setEntries] = useState<any[]>([]);
  const [cities, setCities] = useState<any[]>([]);
  const [cityFilter, setCityFilter] = useState('');
  const [search, setSearch] = useState('');
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [reloadKey, setReloadKey] = useState(0);
  const [confirmClose, setConfirmClose] = useState(false);

  const directory = useStationDirectory(currentPlatform, apiFetch);

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
        if (!controller.signal.aborted) setError(err.message);
      });
    return () => controller.abort();
  }, [currentPlatform, directory.data?.stations.length, directory.data?.fetched_at, reloadKey, dirty]);

  const filteredEntries = entries
    .filter(
      item =>
        (!cityFilter || item.station.city_id === cityFilter) &&
        `${item.station.name} ${item.station.id} ${item.station.city}`.includes(search.trim()),
    )
    .slice(0, 100);

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
      setError(err instanceof Error ? err.message : '保存失败');
    } finally {
      setSaving(false);
    }
  }

  const handleRequestClose = () => {
    if (dirty) setConfirmClose(true);
    else onClose();
  };

  return (
    <WorkbenchDrawer title="站点扣款配置" wide onClose={handleRequestClose}>
      <p className="wb-muted">
        城市与站点自动读取后台目录；刷新保留金额。新站点需填写金额或明确确认零扣款。
      </p>
      <div className="wb-row">
        <label>
          平台{' '}
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
            }}
          >
            <option value="fengshen">风神 / 闪购</option>
            <option value="xiaoxiang">小象超市</option>
          </select>
        </label>
        <label>
          城市{' '}
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
          className="wb-input"
          aria-label="搜索扣款站点"
          placeholder="搜索站点名称或编号"
          value={search}
          onChange={e => setSearch(e.target.value)}
        />
        <button className="wb-button" onClick={directory.refresh}>
          刷新目录
        </button>
      </div>

      <p className="wb-muted">
        {directory.data?.status === 'loading'
          ? '后台站点正在逐步同步。'
          : `${entries.length} 个站点 · ${entries.filter(item => !item.configured).length} 个待配置`}
        {directory.data?.fetched_at
          ? ` · 更新于 ${new Date(directory.data.fetched_at).toLocaleString('zh-CN')}`
          : ''}
      </p>

      {(error || directory.error || directory.data?.message) && (
        <p className="wb-error" role="alert">
          {error || directory.error || directory.data?.message}
        </p>
      )}
      {notice && (
        <p role="status" className="wb-notice">
          {notice}
        </p>
      )}

      {profile && (
        <section className="city-deduction-default">
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
            <p>请先选择一个城市配置默认金额。</p>
          )}
        </section>
      )}

      {profile && (
        <details className="station-exceptions">
          <summary>站点例外配置（按需展开）</summary>
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

      {filteredEntries.length === 100 && (
        <p className="wb-muted">当前显示前100个匹配站点，请按城市或名称筛选。</p>
      )}
      <p className="wb-muted">后台暂不可见的历史配置继续保留，不自动删除。</p>

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
    </WorkbenchDrawer>
  );
}
