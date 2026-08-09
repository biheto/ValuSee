import React from 'react';
import ReactDOM from 'react-dom/client';
import { App } from './App';
import { AdminConsole } from './AdminConsole';
import './styles.css';

class AppErrorBoundary extends React.Component<React.PropsWithChildren, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch(error: Error, info: React.ErrorInfo) { console.error('ValuSee render failure', error, info.componentStack); }
  render() { return this.state.failed ? <main className="fatal-error" role="alert"><strong>页面暂时无法显示</strong><p>你的数据没有丢失，请刷新页面后重试。</p><button onClick={() => window.location.reload()}>重新加载</button></main> : this.props.children; }
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <AppErrorBoundary>{window.location.pathname.startsWith('/admin') ? <AdminConsole /> : <App />}</AppErrorBoundary>
  </React.StrictMode>,
);

const productionHost = !['localhost', '127.0.0.1'].includes(window.location.hostname);
if ('serviceWorker' in navigator && productionHost) {
  window.addEventListener('load', () => {
    void navigator.serviceWorker.register('/sw.js');
  });
}
