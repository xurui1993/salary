import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  ArrowRight,
  Check,
  ChevronDown,
  ChevronUp,
  Download,
  FileSpreadsheet,
  Info,
  Pencil,
  Plus,
  RefreshCw,
  RotateCcw,
  Search,
  Trash2,
  Upload,
  X,
} from 'lucide-react';
import {
  TEMPLATE_REGION_GROUPS,
  filterAndSortTemplateRows,
  getMemoryCachedTemplates,
  preloadSystemTemplates,
  resolveTemplateBusinessTag,
  setMemoryCachedTemplates,
  validateTemplateFormInput,
  type TemplateRecord,
} from '../lib/templateCenterDisplay';

export type { TemplateRecord };

export interface SystemTemplatesPanelProps {
  onNavigatePayroll?: () => void;
  onQuickUpload?: (files: File[]) => void;
  embeddedInDrawer?: boolean;
}

const REQUIRED_FIELDS = ['业务城市', '骑手ID', '开始日期', '结束日期', '结算类型'] as const;

function readFileAsBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = String(reader.result || '');
      const commaIdx = result.indexOf(',');
      resolve(commaIdx >= 0 ? result.slice(commaIdx + 1) : result);
    };
    reader.onerror = () => reject(new Error('文件读取失败'));
    reader.readAsDataURL(file);
  });
}

export function SystemTemplatesPanel({
  onNavigatePayroll,
  onQuickUpload,
  embeddedInDrawer = false,
}: SystemTemplatesPanelProps) {
  const initialCache = useMemo(() => getMemoryCachedTemplates(), []);
  const [templates, setTemplates] = useState<TemplateRecord[]>(initialCache.templates);
  const [hasCustomizations, setHasCustomizations] = useState<boolean>(initialCache.hasCustomizations);
  const [search, setSearch] = useState('');
  const [category, setCategory] = useState<'all' | '淘宝闪购' | '美团小象'>('all');
  const [regionFilter, setRegionFilter] = useState<string>('all');
  const [showSpec, setShowSpec] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState('');
  const [feedbackToast, setFeedbackToast] = useState('');
  const [recentlyDownloaded, setRecentlyDownloaded] = useState<Record<string, boolean>>({});
  const uploadInputRef = useRef<HTMLInputElement>(null);
  const modalFileInputRef = useRef<HTMLInputElement>(null);

  // Create / Edit modal state
  const [modalMode, setModalMode] = useState<'closed' | 'create' | 'edit'>('closed');
  const [editingRecord, setEditingRecord] = useState<TemplateRecord | null>(null);
  const [formScope, setFormScope] = useState('');
  const [formBusinessLine, setFormBusinessLine] = useState<'淘宝闪购' | '美团小象'>('淘宝闪购');
  const [formFileMode, setFormFileMode] = useState<'generate' | 'upload'>('generate');
  const [formFile, setFormFile] = useState<File | null>(null);
  const [formError, setFormError] = useState('');
  const [formSubmitting, setFormSubmitting] = useState(false);

  // Delete / Reset confirmation state
  const [confirmTarget, setConfirmTarget] = useState<
    | { type: 'delete'; record: TemplateRecord; cityName: string }
    | { type: 'reset' }
    | null
  >(null);
  const [confirmSubmitting, setConfirmSubmitting] = useState(false);

  const showNotice = (msg: string) => {
    setFeedbackToast(msg);
    setTimeout(() => {
      setFeedbackToast(prev => (prev === msg ? '' : prev));
    }, 3200);
  };

  const syncTemplates = async (force = false) => {
    setSyncing(true);
    try {
      const result = await preloadSystemTemplates(force);
      setTemplates(result.templates);
      setHasCustomizations(result.hasCustomizations);
      setError('');
    } catch {
      if (!templates.length) {
        setError('模板列表暂不可用，请刷新重试。');
      }
    } finally {
      setSyncing(false);
    }
  };

  useEffect(() => {
    void syncTemplates(!initialCache.isLoadedFromServer);
  }, []);

  const counts = useMemo(() => {
    let shangou = 0;
    let xiaoxiang = 0;
    let available = 0;
    for (const item of templates) {
      const tag = resolveTemplateBusinessTag(item);
      if (tag === '淘宝闪购') shangou += 1;
      if (tag === '美团小象') xiaoxiang += 1;
      if (item.available !== false) available += 1;
    }
    return {
      all: templates.length,
      shangou,
      xiaoxiang,
      available,
    };
  }, [templates]);

  const effectiveRegionFilter = category === '美团小象' ? 'all' : regionFilter;

  const visibleRows = useMemo(
    () =>
      filterAndSortTemplateRows(templates, {
        search,
        category,
        regionFilter: effectiveRegionFilter,
      }),
    [templates, search, category, effectiveRegionFilter],
  );

  const hasActiveFilter = Boolean(
    search.trim() || category !== 'all' || effectiveRegionFilter !== 'all',
  );

  const markDownloaded = (filename: string) => {
    setRecentlyDownloaded(prev => ({ ...prev, [filename]: true }));
    setTimeout(() => {
      setRecentlyDownloaded(prev => ({ ...prev, [filename]: false }));
    }, 2400);
  };

  const handleSelectCategory = (next: 'all' | '淘宝闪购' | '美团小象') => {
    setCategory(next);
    if (next === '美团小象') {
      setRegionFilter('all');
    }
  };

  const openCreateModal = () => {
    setModalMode('create');
    setEditingRecord(null);
    setFormScope('');
    setFormBusinessLine(category === '美团小象' ? '美团小象' : '淘宝闪购');
    setFormFileMode('generate');
    setFormFile(null);
    setFormError('');
  };

  const openEditModal = (record: TemplateRecord) => {
    const tag = resolveTemplateBusinessTag(record);
    const defaultScope = (record.scope || record.filename.replace(/-template\.xlsx$/i, '')).trim();
    setModalMode('edit');
    setEditingRecord(record);
    setFormScope(defaultScope);
    setFormBusinessLine(tag);
    setFormFileMode('generate');
    setFormFile(null);
    setFormError('');
  };

  const closeModal = () => {
    if (formSubmitting) return;
    setModalMode('closed');
    setEditingRecord(null);
    setFormError('');
  };

  const handleFormSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    const isEdit = modalMode === 'edit';
    const validationError = validateTemplateFormInput({
      scope: formScope,
      mode: formFileMode,
      hasFile: Boolean(formFile),
      isEdit,
    });
    if (validationError) {
      setFormError(validationError);
      return;
    }

    setFormSubmitting(true);
    setFormError('');
    try {
      let fileBase64: string | undefined;
      if (formFileMode === 'upload' && formFile) {
        fileBase64 = await readFileAsBase64(formFile);
      }

      const endpoint = isEdit ? '/api/templates/update' : '/api/templates/create';
      const bodyPayload = isEdit
        ? {
            original_filename: editingRecord?.filename,
            scope: formScope.trim(),
            business_line: formBusinessLine,
            ...(fileBase64 ? { file_base64: fileBase64 } : {}),
          }
        : {
            scope: formScope.trim(),
            business_line: formBusinessLine,
            mode: formFileMode,
            ...(fileBase64 ? { file_base64: fileBase64 } : {}),
          };

      const res = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(bodyPayload),
      });
      const data = await res.json();
      if (!res.ok || !data.success) {
        throw new Error(data.error || (isEdit ? '修改模板失败' : '新增模板失败'));
      }

      await syncTemplates(true);
      setModalMode('closed');
      setEditingRecord(null);
      showNotice(
        isEdit
          ? `已更新模板「${data.template?.scope || formScope.trim()}」`
          : `已新增模板「${data.template?.scope || formScope.trim()}」`,
      );
    } catch (err) {
      setFormError(err instanceof Error ? err.message : '操作失败，请重试');
    } finally {
      setFormSubmitting(false);
    }
  };

  const handleConfirmAction = async () => {
    if (!confirmTarget || confirmSubmitting) return;
    setConfirmSubmitting(true);
    try {
      if (confirmTarget.type === 'delete') {
        const res = await fetch('/api/templates/delete', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ filename: confirmTarget.record.filename }),
        });
        const data = await res.json();
        if (!res.ok || !data.success) {
          throw new Error(data.error || '删除模板失败');
        }
        const nextList = templates.filter(item => item.filename !== confirmTarget.record.filename);
        setTemplates(nextList);
        setHasCustomizations(true);
        setMemoryCachedTemplates(nextList, true);
        showNotice(`已删除模板「${confirmTarget.cityName}」`);
      } else {
        const res = await fetch('/api/templates/reset', {
          method: 'POST',
        });
        const data = await res.json();
        if (!res.ok || !data.success || !Array.isArray(data.templates)) {
          throw new Error(data.error || '恢复默认模板失败');
        }
        setTemplates(data.templates as TemplateRecord[]);
        setHasCustomizations(false);
        setMemoryCachedTemplates(data.templates as TemplateRecord[], false);
        showNotice('已恢复系统默认 13 份标准模板');
      }
      setConfirmTarget(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : '操作失败，请稍后重试');
      setConfirmTarget(null);
    } finally {
      setConfirmSubmitting(false);
    }
  };

  const previewFilename = useMemo(() => {
    const clean = formScope.trim().replace(/-template\.xlsx$/i, '').replace(/\.xlsx$/i, '').trim();
    if (!clean) return '城市名称-template.xlsx';
    if (
      modalMode === 'edit' &&
      editingRecord &&
      clean === (editingRecord.scope || editingRecord.filename.replace(/-template\.xlsx$/i, ''))
    ) {
      return editingRecord.filename;
    }
    return `${clean}-template.xlsx`;
  }, [formScope, modalMode, editingRecord]);

  return (
    <section
      className={`wbx-tpl-center${embeddedInDrawer ? ' is-drawer' : ''}`}
      aria-label="系统模板库"
    >
      {feedbackToast && (
        <div role="status" className="wbx-tpl-toast">
          <Check size={13.5} aria-hidden="true" />
          <span>{feedbackToast}</span>
        </div>
      )}

      {error && (
        <div role="alert" className="wbx-tpl-error">
          <span>{error}</span>
          <button
            type="button"
            className="wbx-tpl-action-link is-primary"
            onClick={() => {
              setError('');
              void syncTemplates(true);
            }}
          >
            立即重试
          </button>
        </div>
      )}

      {/* 统一工作台大卡容器：标题动作栏 + 下划线标签筛选条 + 按需表头规范 + 精致模板卡片阵列 + 底栏 */}
      <div className="wbx-tpl-deck-card">
        {/* 1. 卡片头部：标题统计 + 主次操作按钮 */}
        <header className="wbx-tpl-head">
          <div className="wbx-tpl-head__left">
            <h2 className="wbx-tpl-head__title">标准核算模板</h2>
            <span className="wbx-tpl-head__count tabular-nums">{counts.all}</span>
            <span className="wbx-tpl-head__summary tabular-nums">
              淘宝闪购 {counts.shangou} 份 · 美团小象 {counts.xiaoxiang} 份
            </span>
          </div>

          <div className="wbx-tpl-head__actions">
            <button
              type="button"
              className={`wbx-tpl-tool-btn${showSpec ? ' is-active' : ''}`}
              aria-expanded={showSpec}
              aria-controls="wbx-tpl-spec-panel"
              onClick={() => setShowSpec(prev => !prev)}
            >
              <Info size={13} aria-hidden="true" />
              <span>表头规范</span>
              {showSpec ? (
                <ChevronUp size={12} aria-hidden="true" />
              ) : (
                <ChevronDown size={12} aria-hidden="true" />
              )}
            </button>

            <button
              type="button"
              className="wbx-tpl-tool-btn"
              onClick={() => setConfirmTarget({ type: 'reset' })}
              title="还原系统自带的 13 份标准城市模板"
            >
              <RotateCcw size={12.5} aria-hidden="true" />
              <span>恢复默认</span>
            </button>

            {onQuickUpload && (
              <>
                <input
                  ref={uploadInputRef}
                  type="file"
                  accept=".xlsx,.xls"
                  multiple
                  className="hidden"
                  onChange={event => {
                    const files = Array.from(event.target.files || []);
                    event.target.value = '';
                    if (files.length > 0) {
                      onQuickUpload(files);
                    }
                  }}
                />
                <button
                  type="button"
                  className="wbx-tpl-tool-btn"
                  onClick={() => uploadInputRef.current?.click()}
                >
                  <Upload size={13} aria-hidden="true" />
                  <span>上传已填表去核算</span>
                </button>
              </>
            )}

            <button
              type="button"
              className="wbx-tpl-add-btn"
              onClick={openCreateModal}
            >
              <Plus size={13.5} aria-hidden="true" />
              <span>新增模板</span>
            </button>

            {embeddedInDrawer && onNavigatePayroll && (
              <button
                type="button"
                className="wbx-tpl-tool-btn"
                onClick={onNavigatePayroll}
              >
                <span>返回兼职核算</span>
                <ArrowRight size={12.5} aria-hidden="true" />
              </button>
            )}
          </div>
        </header>

        {/* 2. 统一底划线标签 + 筛选搜索条（对齐兼职核算与任务中心） */}
        <div className="wbx-tpl-filterbar">
          <div className="wbx-tpl-tabs" role="tablist" aria-label="模板业务线分类">
            <button
              type="button"
              role="tab"
              aria-selected={category === 'all'}
              className={`wbx-tpl-tab${category === 'all' ? ' is-active' : ''}`}
              onClick={() => handleSelectCategory('all')}
            >
              <span>全部</span>
              <span className="wbx-tpl-tab__count tabular-nums">{counts.all}</span>
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={category === '淘宝闪购'}
              className={`wbx-tpl-tab${category === '淘宝闪购' ? ' is-active' : ''}`}
              onClick={() => handleSelectCategory('淘宝闪购')}
            >
              <span>淘宝闪购</span>
              <span className="wbx-tpl-tab__count tabular-nums">{counts.shangou}</span>
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={category === '美团小象'}
              className={`wbx-tpl-tab${category === '美团小象' ? ' is-active' : ''}`}
              onClick={() => handleSelectCategory('美团小象')}
            >
              <span>美团小象</span>
              <span className="wbx-tpl-tab__count tabular-nums">{counts.xiaoxiang}</span>
            </button>
          </div>

          <div className="wbx-tpl-filterbar__right">
            <div className="wbx-tpl-search">
              <Search size={13.5} className="wbx-tpl-search__icon" aria-hidden="true" />
              <input
                className="wbx-tpl-search__input"
                aria-label="搜索模板"
                placeholder="搜索城市、地区或文件名…"
                value={search}
                onChange={event => setSearch(event.target.value)}
              />
              {search.trim() && (
                <button
                  type="button"
                  className="wbx-tpl-search__clear"
                  aria-label="清空搜索关键词"
                  onClick={() => setSearch('')}
                >
                  <X size={11} />
                </button>
              )}
            </div>

            {category !== '美团小象' && (
              <select
                className="wbx-tpl-region-select"
                aria-label="按地区筛选模板"
                value={regionFilter}
                onChange={event => setRegionFilter(event.target.value)}
              >
                {TEMPLATE_REGION_GROUPS.map(group => (
                  <option key={group.id} value={group.id}>
                    {group.label}
                  </option>
                ))}
              </select>
            )}

            {hasActiveFilter && (
              <button
                type="button"
                className="wbx-tpl-reset-link"
                onClick={() => {
                  setSearch('');
                  setCategory('all');
                  setRegionFilter('all');
                }}
              >
                重置筛选
              </button>
            )}
          </div>
        </div>

        {/* 3. 按需展开的表头规范说明条（内嵌于大卡，视觉连贯） */}
        {showSpec && (
          <div
            id="wbx-tpl-spec-panel"
            className="wbx-tpl-spec-drawer"
            role="region"
            aria-label="标准模板结构规范"
          >
            <div className="wbx-tpl-spec-drawer__row">
              <span className="wbx-tpl-spec-drawer__item">
                <span className="wbx-tpl-spec-drawer__label">必含工作表</span>
                <strong className="wbx-tpl-spec-drawer__sheet">申请名单</strong>
              </span>
              <span className="wbx-tpl-spec-drawer__sep" aria-hidden="true">·</span>
              <span className="wbx-tpl-spec-drawer__item">
                <span className="wbx-tpl-spec-drawer__label">核心必填表头列</span>
                <span className="wbx-tpl-spec-fields">
                  {REQUIRED_FIELDS.map(field => (
                    <code key={field} className="wbx-tpl-spec-field">
                      {field}
                    </code>
                  ))}
                </span>
              </span>
              <span className="wbx-tpl-spec-drawer__sep" aria-hidden="true">·</span>
              <span className="wbx-tpl-spec-drawer__hint">
                支持点击「新增模板」一键生成标准城市模板，或上传本地 .xlsx 文件自动校验
              </span>
            </div>
          </div>
        )}

        {/* 4. 精致卡片阵列主体 */}
        {!visibleRows.length ? (
          <div className="wbx-tpl-empty-box">
            <div className="wbx-tpl-empty">
              <FileSpreadsheet size={18} aria-hidden="true" />
              <span>
                {templates.length ? '未找到匹配当前筛选条件的模板' : '暂无可用标准模板'}
              </span>
              {hasActiveFilter && (
                <button
                  type="button"
                  className="wbx-tpl-action-link is-primary"
                  onClick={() => {
                    setSearch('');
                    setCategory('all');
                    setRegionFilter('all');
                  }}
                >
                  重置筛选
                </button>
              )}
            </div>
          </div>
        ) : (
          <div className="wbx-tpl-grid" role="list" aria-label="系统标准模板卡片列表">
            {visibleRows.map(({ record, row }) => {
              const isDownloaded = Boolean(recentlyDownloaded[row.filename]);
              const isXiaoxiang = row.businessTag === '美团小象';
              const colCountText =
                record.header_count && record.header_count > 0
                  ? `${record.header_count} 列标准`
                  : isXiaoxiang
                    ? '22 列标准'
                    : '10 列标准';
              return (
                <article
                  key={row.filename}
                  role="listitem"
                  className={`wbx-tpl-card${isXiaoxiang ? ' is-xiaoxiang' : ''}${!row.available ? ' is-disabled' : ''}`}
                >
                  <div className="wbx-tpl-card__head">
                    <span
                      className={`wbx-tpl-card__icon${isXiaoxiang ? ' is-xiaoxiang' : ''}`}
                      aria-hidden="true"
                    >
                      <FileSpreadsheet size={17} />
                    </span>
                    <div className="wbx-tpl-card__title-block">
                      <div className="wbx-tpl-card__title-row">
                        <h3 className="wbx-tpl-card__city" title={row.cityName}>
                          {row.cityName}
                        </h3>
                        {row.sourceBadge && (
                          <span className="wbx-tpl-source-tag">{row.sourceBadge}</span>
                        )}
                      </div>
                      <p className="wbx-tpl-card__biz">
                        <span className={isXiaoxiang ? 'is-xiaoxiang' : 'is-shangou'}>
                          {row.businessTag}
                        </span>
                        <span className="wbx-tpl-card__sep" aria-hidden="true">·</span>
                        <span>{row.regionTag}</span>
                      </p>
                    </div>
                    <span className="wbx-tpl-card__cols tabular-nums">{colCountText}</span>
                  </div>

                  <div className="wbx-tpl-card__spec">
                    <span className="wbx-tpl-card__file tabular-nums" title={row.filename}>
                      {row.filename}
                    </span>
                    <span className="wbx-tpl-card__size tabular-nums">
                      {row.fileSizeText}
                    </span>
                  </div>

                  <div className="wbx-tpl-card__foot">
                    <div className="wbx-tpl-card__edit-group">
                      <button
                        type="button"
                        className="wbx-tpl-card-op"
                        aria-label={`修改 ${row.cityName}`}
                        onClick={() => openEditModal(record)}
                      >
                        <Pencil size={12} aria-hidden="true" />
                        <span>修改</span>
                      </button>
                      <button
                        type="button"
                        className="wbx-tpl-card-op is-danger"
                        aria-label={`删除 ${row.cityName}`}
                        onClick={() =>
                          setConfirmTarget({
                            type: 'delete',
                            record,
                            cityName: row.cityName,
                          })
                        }
                      >
                        <Trash2 size={12} aria-hidden="true" />
                        <span>删除</span>
                      </button>
                    </div>

                    {row.available ? (
                      <a
                        className={`wbx-tpl-dl-btn${isDownloaded ? ' is-downloaded' : ''}`}
                        aria-label={`下载 ${row.filename}`}
                        href={`/api/download/template?file=${encodeURIComponent(row.filename)}`}
                        download
                        onClick={() => markDownloaded(row.filename)}
                      >
                        {isDownloaded ? (
                          <Check size={12.5} aria-hidden="true" />
                        ) : (
                          <Download size={12.5} aria-hidden="true" />
                        )}
                        <span>{isDownloaded ? '已下载' : '下载'}</span>
                      </a>
                    ) : (
                      <span className="wbx-tpl-action-disabled">不可下载</span>
                    )}
                  </div>
                </article>
              );
            })}
          </div>
        )}

        {/* 5. 底部汇总状态栏 */}
        <div className="wbx-tpl-table-foot">
          <div className="wbx-tpl-table-foot__left tabular-nums">
            <span>
              当前展示 {visibleRows.length} 份模板（淘宝闪购 {counts.shangou} · 美团小象 {counts.xiaoxiang}）
            </span>
            {hasCustomizations && (
              <span className="wbx-tpl-foot-custom-note"> · 含自定义变更，可随时点击「恢复默认」还原</span>
            )}
          </div>
          <div className="wbx-tpl-table-foot__right">
            <button
              type="button"
              className="wbx-tpl-action-link"
              disabled={syncing}
              onClick={() => void syncTemplates(true)}
            >
              <RefreshCw size={12} className={syncing ? 'animate-spin' : ''} aria-hidden="true" />
              <span>{syncing ? '同步中…' : '刷新列表'}</span>
            </button>
          </div>
        </div>
      </div>

      {/* 新增 / 修改模板弹窗 */}
      {modalMode !== 'closed' && (
        <div
          className="wbx-tpl-modal-backdrop"
          role="dialog"
          aria-modal="true"
          aria-label={modalMode === 'create' ? '新增标准模板' : '修改模板'}
          onClick={event => {
            if (event.target === event.currentTarget) closeModal();
          }}
        >
          <div className="wbx-tpl-modal">
            <div className="wbx-tpl-modal__head">
              <h3 className="wbx-tpl-modal__title">
                {modalMode === 'create' ? '新增标准模板' : `修改模板 · ${editingRecord?.filename || ''}`}
              </h3>
              <button
                type="button"
                className="wbx-tpl-modal__close"
                aria-label="关闭弹窗"
                onClick={closeModal}
              >
                <X size={15} />
              </button>
            </div>

            <form className="wbx-tpl-modal__form" onSubmit={handleFormSubmit}>
              <div className="wbx-tpl-field">
                <label className="wbx-tpl-field__label" htmlFor="wbx-tpl-scope-input">
                  城市 / 模板适用名称
                </label>
                <input
                  id="wbx-tpl-scope-input"
                  className="wbx-tpl-field__input"
                  aria-label="城市或模板名称"
                  placeholder="例如：杭州、成都、武汉…"
                  value={formScope}
                  onChange={event => {
                    setFormScope(event.target.value);
                    if (formError) setFormError('');
                  }}
                  autoFocus
                />
                <span className="wbx-tpl-field__hint tabular-nums">
                  对应标准文件名：<strong>{previewFilename}</strong>
                </span>
              </div>

              <div className="wbx-tpl-field">
                <span className="wbx-tpl-field__label">适用业务线与核算引擎</span>
                <div className="wbx-tpl-radio-row" role="group" aria-label="适用业务线">
                  <button
                    type="button"
                    className={`wbx-tpl-radio-card${formBusinessLine === '淘宝闪购' ? ' is-selected' : ''}`}
                    aria-pressed={formBusinessLine === '淘宝闪购'}
                    onClick={() => setFormBusinessLine('淘宝闪购')}
                  >
                    <span className="wbx-tpl-radio-card__title">淘宝闪购</span>
                    <span className="wbx-tpl-radio-card__desc">闪购兼职薪资申请表（10 列风神标准表头）</span>
                  </button>
                  <button
                    type="button"
                    className={`wbx-tpl-radio-card${formBusinessLine === '美团小象' ? ' is-selected' : ''}`}
                    aria-pressed={formBusinessLine === '美团小象'}
                    onClick={() => setFormBusinessLine('美团小象')}
                  >
                    <span className="wbx-tpl-radio-card__title">美团小象</span>
                    <span className="wbx-tpl-radio-card__desc">众包/灯塔薪资申请表（22 列灯塔标准表头）</span>
                  </button>
                </div>
              </div>

              <div className="wbx-tpl-field">
                <span className="wbx-tpl-field__label">
                  {modalMode === 'create' ? '模板生成方式' : 'Excel 模板文件'}
                </span>
                <div className="wbx-tpl-radio-row" role="group" aria-label="模板文件方式">
                  <button
                    type="button"
                    className={`wbx-tpl-radio-card${formFileMode === 'generate' ? ' is-selected' : ''}`}
                    aria-pressed={formFileMode === 'generate'}
                    onClick={() => {
                      setFormFileMode('generate');
                      setFormError('');
                    }}
                  >
                    <span className="wbx-tpl-radio-card__title">
                      {modalMode === 'create' ? '基于标准表头一键生成（推荐）' : '保留现有 Excel 文件'}
                    </span>
                    <span className="wbx-tpl-radio-card__desc">
                      {modalMode === 'create'
                        ? '自动克隆系统标准工作表与必填列，100% 通过核算校验'
                        : '仅更新城市名称或所属业务线，不替换工作簿内容'}
                    </span>
                  </button>

                  <button
                    type="button"
                    className={`wbx-tpl-radio-card${formFileMode === 'upload' ? ' is-selected' : ''}`}
                    aria-pressed={formFileMode === 'upload'}
                    onClick={() => {
                      setFormFileMode('upload');
                      setFormError('');
                    }}
                  >
                    <span className="wbx-tpl-radio-card__title">
                      {modalMode === 'create' ? '上传本地 Excel 模板' : '上传并替换 Excel 文件'}
                    </span>
                    <span className="wbx-tpl-radio-card__desc">
                      上传本地 .xlsx 文件，系统将自动校验「申请名单」必填列
                    </span>
                  </button>
                </div>

                {formFileMode === 'upload' && (
                  <div className="wbx-tpl-upload-box">
                    <input
                      ref={modalFileInputRef}
                      type="file"
                      accept=".xlsx"
                      className="hidden"
                      aria-label="选择本地 Excel 模板文件"
                      onChange={event => {
                        const selected = event.target.files?.[0] || null;
                        setFormFile(selected);
                        if (selected && !formScope.trim()) {
                          const inferred = selected.name
                            .replace(/-template\.xlsx$/i, '')
                            .replace(/\.xlsx$/i, '')
                            .trim();
                          if (inferred) setFormScope(inferred);
                        }
                        if (formError) setFormError('');
                      }}
                    />
                    <button
                      type="button"
                      className="wbx-tpl-upload-trigger"
                      onClick={() => modalFileInputRef.current?.click()}
                    >
                      <Upload size={14} aria-hidden="true" />
                      <span>{formFile ? formFile.name : '点击选择本地 .xlsx 模板文件'}</span>
                    </button>
                    {formFile && (
                      <span className="wbx-tpl-upload-meta tabular-nums">
                        {(formFile.size / 1024).toFixed(1)} KB
                      </span>
                    )}
                  </div>
                )}
              </div>

              {formError && (
                <div role="alert" className="wbx-tpl-form-error">
                  {formError}
                </div>
              )}

              <div className="wbx-tpl-modal__foot">
                <button
                  type="button"
                  className="wbx-tpl-tool-btn"
                  disabled={formSubmitting}
                  onClick={closeModal}
                >
                  取消
                </button>
                <button
                  type="submit"
                  className="wbx-tpl-add-btn"
                  disabled={formSubmitting}
                >
                  {formSubmitting
                    ? '保存中…'
                    : modalMode === 'create'
                      ? '确认新增'
                      : '保存修改'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* 删除 / 恢复默认 二次确认弹窗 */}
      {confirmTarget && (
        <div
          className="wbx-tpl-modal-backdrop"
          role="dialog"
          aria-modal="true"
          aria-label={confirmTarget.type === 'delete' ? '确认删除模板' : '确认恢复系统默认模板'}
          onClick={event => {
            if (event.target === event.currentTarget && !confirmSubmitting) {
              setConfirmTarget(null);
            }
          }}
        >
          <div className="wbx-tpl-modal is-compact">
            <div className="wbx-tpl-modal__head">
              <h3 className="wbx-tpl-modal__title">
                {confirmTarget.type === 'delete'
                  ? `确认删除模板「${confirmTarget.cityName}」？`
                  : '确认恢复系统默认模板？'}
              </h3>
              <button
                type="button"
                className="wbx-tpl-modal__close"
                aria-label="关闭确认弹窗"
                onClick={() => !confirmSubmitting && setConfirmTarget(null)}
              >
                <X size={15} />
              </button>
            </div>
            <div className="wbx-tpl-modal__body">
              <p className="wbx-tpl-confirm-desc">
                {confirmTarget.type === 'delete'
                  ? `将从模板列表中移除「${confirmTarget.record.filename}」。如为系统预设模板，后续随时可点击顶部「恢复默认」一键还原。`
                  : '将还原系统自带的 13 份标准城市模板（12 城淘宝闪购 + 1 份美团小象），并清理自定义新增或修改项。'}
              </p>
            </div>
            <div className="wbx-tpl-modal__foot">
              <button
                type="button"
                className="wbx-tpl-tool-btn"
                disabled={confirmSubmitting}
                onClick={() => setConfirmTarget(null)}
              >
                取消
              </button>
              <button
                type="button"
                className={`wbx-tpl-add-btn${confirmTarget.type === 'delete' ? ' is-danger' : ''}`}
                disabled={confirmSubmitting}
                onClick={handleConfirmAction}
              >
                {confirmSubmitting
                  ? '处理中…'
                  : confirmTarget.type === 'delete'
                    ? '确认删除'
                    : '确认恢复默认'}
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
