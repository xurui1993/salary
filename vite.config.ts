import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import path from 'path';
import {defineConfig} from 'vite';

export default defineConfig(() => {
  return {
    plugins: [react(), tailwindcss()],
    resolve: {
      alias: {
        '@': path.resolve(__dirname, '.'),
      },
    },
    build: {
      rollupOptions: {
        output: {
          // 手动分包：vendor(react) / icons(lucide) / xlsx 各自独立，压低主 chunk 体积。
          manualChunks(id: string) {
            if (!id.includes('node_modules')) return undefined;
            if (id.includes('xlsx')) return 'xlsx';
            if (id.includes('lucide-react')) return 'icons';
            if (id.includes('react-dom') || id.includes('/react/') || id.includes('scheduler')) {
              return 'vendor';
            }
            return undefined;
          },
        },
      },
    },
    server: {
      allowedHosts: true as const,
      // HMR is disabled in AI Studio via DISABLE_HMR env var.
      // Do not modify—file watching is disabled to prevent flickering during agent edits.
      hmr: process.env.DISABLE_HMR !== 'true',
      // Disable file watching when DISABLE_HMR is true to save CPU during agent edits.
      watch: process.env.DISABLE_HMR === 'true' ? null : {
        // Runtime data is written by the Python backend while tasks run.
        // Watching it would make Vite reload the whole page on every write.
        ignored: [
          '**/backend/.local_downloads/**',
          '**/backend/.local_auth/**',
          '**/data/**',
          '**/outputs/**',
          '**/uploads/**',
          '**/dist/**',
          '**/__pycache__/**',
          '**/*.sqlite3',
          '**/*.sqlite3-wal',
          '**/*.sqlite3-shm',
          '**/*.log',
        ],
      },
    },
  };
});
