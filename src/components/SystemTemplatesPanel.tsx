import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  ArrowRight,
  Check,
  ChevronDown,
  ChevronUp,
  Download,
  FileSpreadsheet,
  Info,
  RefreshCw,
  Search,
  ShieldCheck,
  Upload,
  X,
} from 'lucide-react';
import { classifyTemplateCategory } from '../lib/workbench';

export interface TemplateRecord {
  filename: string;
  business_line?: string;
  scope?: string;
  size: number;
  mtime?: number;
  content_version?: string;
  available?: boolean;
  error?: string;
}

export interface SystemTemplatesPanelProps {
  onNavigatePayroll?: () => void;
  onQuickUpload?: (files: File[]) => void;
  embeddedInDrawer?: boolean;
}

const REQUIRED_FIELDS = ['业务城市', '骑手ID', '开始日期', '结束日期', '结算类型'] as const;

const REGION_GROUPS: { id: string; label: string; cities: string[] }[] = [
  { id: 'all', label: '全部地区', cities: [] },
  { id: 'south', label: '华南地区', cities: ['广州', '深圳', '东莞', '韶关', '三亚'] },
  { id: 'east', label: '华东地区', cities: ['上海', '宁波', '泉州'] },
  { id: 'north', label: '华北与东北', cities: ['北京', '天津', '保定', '大连'] },
];

function formatTemplateDisplayTitle(item: TemplateRecord, categoryTag: string): {
  displayTitle: string;
  accountingHint: string;
} {
  const baseName = item.filename.replace(/-template\.xlsx$/i, '').replace(/\.xlsx$/i, '');
  if (categoryTag === '美团小象' || baseName.includes('小象')) {
    return {
      displayTitle: '美团小象 · 灯塔薪资申请表',
      accountingHint: '自动匹配灯塔核算 · 已校验',
    };
  }
  const city = item.scope || baseName;
  return {
    displayTitle: `${city} · 闪购兼职薪资申请表`,
    accountingHint: '自动匹配风神核算 · 已校验',
  };
}

export function SystemTemplatesPanel({
  onNavigatePayroll,
  onQuickUpload,
  embeddedInDrawer = false,
}: SystemTemplatesPanelProps) {
  const [templates, setTemplates] = useState<TemplateRecord[]>([]);
  const [search, setSearch] = useState('');
  const [category, setCategory] = useState<'all' | '淘宝闪购' | '美团小象'>('all');
  const [regionFilter, setRegionFilter] = useState<string>('all');
  const [showSpec, setShowSpec] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [version, setVersion] = useState(0);
  const [recentlyDownloaded, setRecentlyDownloaded] = useState<Record<string, boolean>>({});
  const loaded = useRef(false);
  const uploadInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;

    async function refresh() {
      if (!loaded.current) setLoading(true);
      try {
        const response = await fetch('/api/templates/list', {
          signal: AbortSignal.any([controller.signal, AbortSignal.timeout(10000)]),
        });
        const data = await response.json();
        if (!response.ok || !data.success || !Array.isArray(data.templates)) {
          throw new Error('模板列表读取失败');
        }
        if (!controller.signal.aborted) {
          setTemplates(data.templates as TemplateRecord[]);
          setError('');
          loaded.current = true;
        }
      } catch {
        if (!controller.signal.aborted) {
          setError('模板列表暂不可用，请刷新重试。');
        }
      } finally {
        if (!controller.signal.aborted) {
          setLoading(false);
          timer = setTimeout(refresh, 15000);
        }
      }
    }

    void refresh();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [version]);

  const counts = useMemo(() => {
    let shangou = 0;
    let xiaoxiang = 0;
    let available = 0;
    for (const item of templates) {
      const tag = classifyTemplateCategory(item.filename).tag;
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

  const visible = useMemo(() => {
    const keyword = search.trim().toLowerCase();
    const activeRegion = REGION_GROUPS.find(group => group.id === regionFilter);

    const filtered = templates.filter(item => {
      const meta = classifyTemplateCategory(item.filename);
      const { displayTitle, accountingHint } = formatTemplateDisplayTitle(item, meta.tag);
      const matchesSearch =
        !keyword ||
        item.filename.toLowerCase().includes(keyword) ||
        displayTitle.toLowerCase().includes(keyword) ||
        accountingHint.toLowerCase().includes(keyword) ||
        (item.scope || '').toLowerCase().includes(keyword);
      if (!matchesSearch) return false;
      if (category !== 'all' && meta.tag !== category) return false;
      if (activeRegion && activeRegion.cities.length > 0) {
        const city = item.scope || item.filename.replace(/-template\.xlsx$/i, '');
        if (!activeRegion.cities.includes(city)) return false;
      }
      return true;
    });

    return [...filtered].sort((a, b) => {
      const rankA = classifyTemplateCategory(a.filename).tag === '美团小象' ? 1 : 0;
      const rankB = classifyTemplateCategory(b.filename).tag === '美团小象' ? 1 : 0;
      return rankA - rankB;
    });
  }, [templates, search, category, regionFilter]);

  const hasActiveFilter = Boolean(search.trim() || category !== 'all' || regionFilter !== 'all');

  const markDownloaded = (filename: string) => {
    setRecentlyDownloaded(prev => ({ ...prev, [filename]: true }));
    setTimeout(() => {
      setRecentlyDownloaded(prev => ({ ...prev, [filename]: false }));
    }, 2600);
  };

  return (
    <section
      className={`wbx-tpl-center${embeddedInDrawer ? ' is-drawer' : ''}`}
      aria-label="系统模板库"
    >
      {/* 1. 顶部精简下划线导航条：业务线页签 + 校验状态 + 表头规范按需展开 + 主操作 */}
      <div className="wbx-tpl-topbar">
        <div className="wbx-tpl-tabs" role="group" aria-label="模板业务线分类">
          <button
            type="button"
            className={`wbx-tpl-tab${category === 'all' ? ' is-active' : ''}`}
            aria-pressed={category === 'all'}
            onClick={() => setCategory('all')}
          >
            <span>全部模板</span>
            <span className="wbx-tpl-tab__count tabular-nums">{counts.all}</span>
          </button>
          <button
            type="button"
            className={`wbx-tpl-tab${category === '淘宝闪购' ? ' is-active' : ''}`}
            aria-pressed={category === '淘宝闪购'}
            onClick={() => setCategory('淘宝闪购')}
          >
            <span>淘宝闪购</span>
            <span className="wbx-tpl-tab__count tabular-nums">{counts.shangou}</span>
          </button>
          <button
            type="button"
            className={`wbx-tpl-tab${category === '美团小象' ? ' is-active' : ''}`}
            aria-pressed={category === '美团小象'}
            onClick={() => {
              setCategory('美团小象');
              setRegionFilter('all');
            }}
          >
            <span>美团小象</span>
            <span className="wbx-tpl-tab__count tabular-nums">{counts.xiaoxiang}</span>
          </button>
        </div>

        <div className="wbx-tpl-topbar__right">
          <span
            className="wbx-tpl-verify-meta tabular-nums"
            title="官方只读标准模板已自动完成 SHA-256 完整性校验"
          >
            <ShieldCheck size={13.5} aria-hidden="true" />
            <span>
              {counts.available}/{counts.all || 13} 已校验
            </span>
          </span>

          <button
            type="button"
            className={`wbx-tpl-spec-toggle${showSpec ? ' is-open' : ''}`}
            aria-expanded={showSpec}
            aria-controls="wbx-tpl-spec-panel"
            onClick={() => setShowSpec(prev => !prev)}
          >
            <Info size={13} aria-hidden="true" />
            <span>表头规范</span>
            {showSpec ? <ChevronUp size={13} aria-hidden="true" /> : <ChevronDown size={13} aria-hidden="true" />}
          </button>

          {onNavigatePayroll && (
            <button
              type="button"
              className="wbx-btn wbx-btn--sm"
              onClick={onNavigatePayroll}
            >
              <span>前往核算批次</span>
              <ArrowRight size={13} aria-hidden="true" />
            </button>
          )}

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
                className="wbx-btn wbx-btn--primary wbx-btn--sm"
                onClick={() => uploadInputRef.current?.click()}
              >
                <Upload size={13.5} aria-hidden="true" />
                <span>上传已填模板去核算</span>
              </button>
            </>
          )}
        </div>
      </div>

      {/* 按需展开的模板表头结构规范说明条 */}
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
              <span className="wbx-tpl-spec-drawer__label">必填表头列</span>
              <span className="wbx-tpl-spec-fields">
                {REQUIRED_FIELDS.map(field => (
                  <code key={field} className="wbx-tpl-spec-field">
                    {field}
                  </code>
                ))}
              </span>
            </span>
          </div>
          <div className="wbx-tpl-spec-drawer__steps" aria-label="模板使用流程">
            <span className="wbx-tpl-step">
              <span className="wbx-tpl-step__num">01</span>
              <span>下载对应城市标准模板</span>
            </span>
            <span className="wbx-tpl-step-arrow" aria-hidden="true">→</span>
            <span className="wbx-tpl-step">
              <span className="wbx-tpl-step__num">02</span>
              <span>在「申请名单」填写骑手与账期</span>
            </span>
            <span className="wbx-tpl-step-arrow" aria-hidden="true">→</span>
            <span className="wbx-tpl-step">
              <span className="wbx-tpl-step__num">03</span>
              <span>点击右上角上传至核算批次自动计算</span>
            </span>
          </div>
        </div>
      )}

      {error && (
        <div role="alert" className="wbx-tpl-error">
          <span>{error}</span>
          <button
            type="button"
            className="wbx-btn wbx-btn--sm"
            onClick={() => setVersion(value => value + 1)}
          >
            立即重试
          </button>
        </div>
      )}

      {/* 2. 主体统一白色工作卡：片区筛选 + 搜索 + 3 列精炼模板卡 + 底部三步流程条 */}
      <div className="wbx-tpl-workspace">
        <div className="wbx-tpl-subbar">
          <div className="wbx-tpl-subbar__left">
            {category !== '美团小象' ? (
              <div className="wbx-tpl-regions" role="group" aria-label="城市片区快速筛选">
                {REGION_GROUPS.map(group => (
                  <button
                    key={group.id}
                    type="button"
                    className={`wbx-tpl-region-btn${regionFilter === group.id ? ' is-active' : ''}`}
                    aria-pressed={regionFilter === group.id}
                    onClick={() => setRegionFilter(group.id)}
                  >
                    {group.label}
                  </button>
                ))}
              </div>
            ) : (
              <span className="wbx-tpl-subbar__caption">
                美团小象超市 / 灯塔全国通用薪资申请模板
              </span>
            )}

            {hasActiveFilter && !loading && (
              <span className="wbx-tpl-subbar__count tabular-nums">
                匹配 {visible.length} 份
              </span>
            )}
          </div>

          <div className="wbx-tpl-subbar__right">
            <div className="wbx-tpl-search">
              <Search size={13.5} className="wbx-tpl-search__icon" aria-hidden="true" />
              <input
                className="wbx-tpl-search__input"
                aria-label="搜索模板"
                placeholder="搜索城市或模板文件名…"
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
                  <X size={12} />
                </button>
              )}
            </div>

            <button
              type="button"
              className="wbx-tpl-refresh-btn"
              aria-label="刷新模板列表"
              title="重新校验并刷新模板列表"
              disabled={loading}
              onClick={() => setVersion(value => value + 1)}
            >
              <RefreshCw size={13.5} className={loading ? 'animate-spin' : ''} />
            </button>
          </div>
        </div>

        {/* 模板卡片网格 */}
        <div className="wbx-tpl-workspace__body">
          <div className="wbx-tpl-grid" tabIndex={0} aria-label="可下载模板">
            {loading ? (
              <div role="status" className="wbx-tpl-empty">
                <RefreshCw size={18} className="animate-spin text-sky-600" />
                <span>正在校验并加载系统标准模板…</span>
              </div>
            ) : !visible.length ? (
              <div className="wbx-tpl-empty">
                <span className="wbx-tpl-empty__icon" aria-hidden="true">
                  <FileSpreadsheet size={20} />
                </span>
                <p className="wbx-tpl-empty__title">
                  {templates.length ? '未找到匹配当前筛选条件的模板' : '暂无可用标准模板'}
                </p>
                {hasActiveFilter && (
                  <button
                    type="button"
                    className="wbx-btn wbx-btn--sm"
                    onClick={() => {
                      setSearch('');
                      setCategory('all');
                      setRegionFilter('all');
                    }}
                  >
                    重置全部筛选条件
                  </button>
                )}
              </div>
            ) : (
              visible.map(item => {
                const meta = classifyTemplateCategory(item.filename);
                const isXiaoxiang = meta.tag === '美团小象';
                const { displayTitle, accountingHint } = formatTemplateDisplayTitle(item, meta.tag);
                const isDownloaded = Boolean(recentlyDownloaded[item.filename]);
                const shortHash = item.content_version ? item.content_version.slice(0, 8) : '';
                const verifyTooltip = shortHash
                  ? `已通过 SHA-256 校验（#${shortHash}）· 完整哈希：${item.content_version}`
                  : '官方标准只读模板';

                return (
                  <article
                    key={item.filename}
                    className={`wbx-tpl-card${isXiaoxiang ? ' is-xiaoxiang' : ' is-shangou'}${item.available === false ? ' is-disabled' : ''}`}
                  >
                    <div className="wbx-tpl-card__head">
                      <div className="wbx-tpl-card__identity">
                        <span
                          className={`wbx-tpl-card__emblem${isXiaoxiang ? ' is-xiaoxiang' : ' is-shangou'}`}
                          aria-hidden="true"
                        >
                          <FileSpreadsheet size={16} />
                        </span>
                        <div className="wbx-tpl-card__titles">
                          <h3 className="wbx-tpl-card__title" title={displayTitle}>
                            {displayTitle}
                          </h3>
                          <div className="wbx-tpl-card__file-meta tabular-nums" title={verifyTooltip}>
                            <span className="wbx-tpl-card__filename">{item.filename}</span>
                            <span className="wbx-tpl-card__dot" aria-hidden="true">·</span>
                            <span>{(item.size / 1024).toFixed(1)} KB</span>
                          </div>
                        </div>
                      </div>

                      <span
                        className={`wbx-tpl-card__tag${isXiaoxiang ? ' is-xiaoxiang' : ' is-shangou'}`}
                      >
                        {meta.tag}
                      </span>
                    </div>

                    <div className="wbx-tpl-card__foot">
                      <span className="wbx-tpl-card__scope" title={verifyTooltip}>
                        <ShieldCheck size={12} aria-hidden="true" />
                        <span>{accountingHint}</span>
                      </span>

                      {item.available === false ? (
                        <div className="wbx-tpl-card__err-wrap">
                          <span className="wbx-tpl-card__err-text">
                            {item.error || '模板不可用'}
                          </span>
                          <button type="button" className="wbx-btn wbx-btn--sm" disabled>
                            不可下载
                          </button>
                        </div>
                      ) : (
                        <a
                          className={`wbx-tpl-download-btn${isDownloaded ? ' is-downloaded' : ''}`}
                          aria-label={`下载 ${item.filename}`}
                          href={`/api/download/template?file=${encodeURIComponent(item.filename)}`}
                          download
                          onClick={() => markDownloaded(item.filename)}
                        >
                          {isDownloaded ? (
                            <>
                              <Check size={13} aria-hidden="true" />
                              <span>已开始下载</span>
                            </>
                          ) : (
                            <>
                              <Download size={13} aria-hidden="true" />
                              <span>下载模板</span>
                            </>
                          )}
                        </a>
                      )}
                    </div>
                  </article>
                );
              })
            )}
          </div>
        </div>

      </div>
    </section>
  );
}
