import {createRoot} from 'react-dom/client';
import App from './App.tsx';
// 唯一 CSS 入口：L0 兼容层必须先落地，L1–L5 由 index.css 的 @import 顺序接管。
import './workbench.css';
import './index.css';

createRoot(document.getElementById('root')!).render(<App />);
