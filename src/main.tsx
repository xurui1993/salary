import React from 'react';
import {createRoot} from 'react-dom/client';
import App from './App.tsx';
// 唯一 CSS 入口：L0 兼容层必须先落地，L1–L5 由 index.css 的 @import 顺序接管。
import './workbench.css';
import './index.css';

interface ErrorBoundaryState {
  error: Error | null;
}

class AppErrorBoundary extends React.Component<{children: React.ReactNode}, ErrorBoundaryState> {
  state: ErrorBoundaryState = {error: null};

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return {error};
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error('[AppErrorBoundary]', error, info.componentStack);
  }

  handleReset = () => {
    try {
      localStorage.removeItem('appConfig');
      localStorage.removeItem('workbench_task_kind');
      localStorage.removeItem('workbench_download_platform');
      localStorage.removeItem('workbench_active_report_id');
    } catch {
      // ignore storage errors
    }
    window.location.reload();
  };

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="min-h-screen flex items-center justify-center p-6 bg-[#F6F7F8] text-[#18191C]">
        <div className="max-w-md w-full rounded-2xl bg-white/90 border border-slate-200/80 shadow-sm p-6 space-y-4">
          <div className="space-y-1">
            <h1 className="text-base font-semibold text-[#18191C]">页面加载异常</h1>
            <p className="text-sm text-[#61666D] leading-relaxed">
              工作台渲染时遇到意外错误，可刷新页面或重置本地缓存状态后恢复。
            </p>
          </div>
          <pre className="text-xs text-rose-700 bg-rose-50/80 border border-rose-200/70 rounded-xl p-3 overflow-auto max-h-32 whitespace-pre-wrap break-all">
            {this.state.error.message || String(this.state.error)}
          </pre>
          <div className="flex items-center gap-2.5 pt-1">
            <button
              type="button"
              onClick={() => window.location.reload()}
              className="px-4 py-2 rounded-xl text-sm font-medium bg-[#00AEEC] text-white hover:opacity-95 cursor-pointer"
            >
              重新加载
            </button>
            <button
              type="button"
              onClick={this.handleReset}
              className="px-4 py-2 rounded-xl text-sm font-medium bg-slate-100 text-[#18191C] hover:bg-slate-200/80 cursor-pointer"
            >
              重置缓存并恢复
            </button>
          </div>
        </div>
      </div>
    );
  }
}

createRoot(document.getElementById('root')!).render(
  <AppErrorBoundary>
    <App />
  </AppErrorBoundary>,
);
