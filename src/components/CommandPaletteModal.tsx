import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  BadgeDollarSign,
  Building2,
  Check,
  Compass,
  CornerDownLeft,
  FileSpreadsheet,
  FolderCheck,
  FolderDown,
  KeyRound,
  Layers,
  PanelLeft,
  Radar,
  Search,
  Settings2,
  ShieldCheck,
  SlidersHorizontal,
  Terminal,
  UsersRound,
  WalletCards,
  X,
} from 'lucide-react';
import {
  filterShellCommands,
  type ShellCommandAction,
  type ShellCommandItem,
} from '../lib/shellNav';

export interface CommandPaletteModalProps {
  open: boolean;
  commands: ShellCommandItem[];
  onClose: () => void;
  onExecute: (action: ShellCommandAction) => void;
}

function CommandIcon({ item }: { item: ShellCommandItem }) {
  const { action } = item;
  if (action.type === 'platform') {
    if (action.platform === 'lanorange') return <Layers size={15} />;
    if (action.platform === 'lanorange_mdr') return <Building2 size={15} />;
    if (action.platform === 'payout') return <UsersRound size={15} />;
    if (action.platform === 'xiaoxiang') return <Radar size={15} />;
    return <Compass size={15} />;
  }
  if (action.type === 'payroll') {
    if (action.subView === 'deductions') return <SlidersHorizontal size={15} />;
    if (action.subView === 'templates') return <FileSpreadsheet size={15} />;
    return <WalletCards size={15} />;
  }
  if (action.type === 'workspace') {
    if (action.view === 'history') return <FolderCheck size={15} />;
    if (action.view === 'pickup') return <FolderDown size={15} />;
    if (action.view === 'platform-auth') return <KeyRound size={15} />;
    if (action.view === 'accounts') return <ShieldCheck size={15} />;
    if (action.view === 'global-config') return <Settings2 size={15} />;
    return <BadgeDollarSign size={15} />;
  }
  if (action.type === 'open-dock') return <ShieldCheck size={15} />;
  if (action.type === 'open-logs') return <Terminal size={15} />;
  return <PanelLeft size={15} />;
}

export function CommandPaletteModal({
  open,
  commands,
  onClose,
  onExecute,
}: CommandPaletteModalProps) {
  const [query, setQuery] = useState('');
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const filtered = useMemo(() => filterShellCommands(commands, query), [commands, query]);

  const grouped = useMemo(() => {
    const groups: { name: string; items: { item: ShellCommandItem; flatIndex: number }[] }[] = [];
    const byName = new Map<string, { item: ShellCommandItem; flatIndex: number }[]>();
    filtered.forEach((item, flatIndex) => {
      let bucket = byName.get(item.group);
      if (!bucket) {
        bucket = [];
        byName.set(item.group, bucket);
        groups.push({ name: item.group, items: bucket });
      }
      bucket.push({ item, flatIndex });
    });
    return groups;
  }, [filtered]);

  useEffect(() => {
    if (!open) return;
    setQuery('');
    setSelectedIndex(0);
    const frame = requestAnimationFrame(() => {
      inputRef.current?.focus();
    });
    return () => cancelAnimationFrame(frame);
  }, [open]);

  useEffect(() => {
    setSelectedIndex(0);
  }, [query]);

  useEffect(() => {
    if (!open) return;
    const activeEl = listRef.current?.querySelector<HTMLElement>('[data-cmd-selected="true"]');
    activeEl?.scrollIntoView({ block: 'nearest' });
  }, [selectedIndex, open]);

  if (!open) return null;

  const handleKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === 'Escape') {
      event.preventDefault();
      onClose();
      return;
    }
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      if (filtered.length > 0) {
        setSelectedIndex(prev => (prev + 1) % filtered.length);
      }
      return;
    }
    if (event.key === 'ArrowUp') {
      event.preventDefault();
      if (filtered.length > 0) {
        setSelectedIndex(prev => (prev - 1 + filtered.length) % filtered.length);
      }
      return;
    }
    if (event.key === 'Enter') {
      event.preventDefault();
      const target = filtered[selectedIndex];
      if (target) {
        onExecute(target.action);
        onClose();
      }
    }
  };

  return (
    <div
      className="wbx-cmdk-backdrop"
      role="presentation"
      onMouseDown={event => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        className="wbx-cmdk-dialog"
        role="dialog"
        aria-modal="true"
        aria-label="全局快捷命令面板"
        onKeyDown={handleKeyDown}
      >
        <div className="wbx-cmdk-input-row">
          <Search size={16} className="wbx-cmdk-search-icon" aria-hidden="true" />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={event => setQuery(event.target.value)}
            placeholder="跳转平台、核算模块或快捷操作…（支持中文 / 拼音首字母）"
            className="wbx-cmdk-input"
            aria-label="搜索命令或页面"
          />
          {query && (
            <button
              type="button"
              className="wbx-cmdk-clear"
              onClick={() => {
                setQuery('');
                inputRef.current?.focus();
              }}
              aria-label="清空搜索"
            >
              <X size={14} />
            </button>
          )}
          <kbd className="wbx-cmdk-kbd">ESC</kbd>
        </div>

        <div className="wbx-cmdk-list" ref={listRef} role="listbox" aria-label="快捷入口列表">
          {grouped.length === 0 ? (
            <div className="wbx-cmdk-empty">
              <span>未找到匹配「{query}」的模块或快捷操作</span>
            </div>
          ) : (
            grouped.map(group => (
              <div key={group.name} className="wbx-cmdk-group">
                <div className="wbx-cmdk-group__label">{group.name}</div>
                {group.items.map(({ item, flatIndex }) => {
                  const isSelected = flatIndex === selectedIndex;
                  return (
                    <button
                      key={item.id}
                      type="button"
                      role="option"
                      aria-selected={isSelected}
                      data-cmd-selected={isSelected ? 'true' : 'false'}
                      className={`wbx-cmdk-item${isSelected ? ' is-selected' : ''}${item.active ? ' is-current' : ''}`}
                      onMouseEnter={() => setSelectedIndex(flatIndex)}
                      onClick={() => {
                        onExecute(item.action);
                        onClose();
                      }}
                    >
                      <span className="wbx-cmdk-item__icon" aria-hidden="true">
                        <CommandIcon item={item} />
                      </span>
                      <span className="wbx-cmdk-item__copy">
                        <span className="wbx-cmdk-item__label">{item.label}</span>
                        <span className="wbx-cmdk-item__sub">{item.subtitle}</span>
                      </span>
                      <span className="wbx-cmdk-item__trail">
                        {item.active && (
                          <span className="wbx-cmdk-item__active" title="当前页面">
                            <Check size={13} />
                            <span>当前</span>
                          </span>
                        )}
                        {item.shortcut && <kbd className="wbx-cmdk-kbd">{item.shortcut}</kbd>}
                        {isSelected && <CornerDownLeft size={13} className="wbx-cmdk-item__enter" />}
                      </span>
                    </button>
                  );
                })}
              </div>
            ))
          )}
        </div>

        <div className="wbx-cmdk-foot">
          <span>
            <kbd className="wbx-cmdk-kbd">↑</kbd> <kbd className="wbx-cmdk-kbd">↓</kbd> 选择
          </span>
          <span>
            <kbd className="wbx-cmdk-kbd">Enter</kbd> 执行
          </span>
          <span>
            <kbd className="wbx-cmdk-kbd">[</kbd> 折叠侧栏
          </span>
        </div>
      </div>
    </div>
  );
}
