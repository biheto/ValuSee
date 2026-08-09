import React from 'react';
import ReactDOM from 'react-dom/client';
import { App } from './App';
import { AdminConsole } from './AdminConsole';
import './styles.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    {window.location.pathname.startsWith('/admin') ? <AdminConsole /> : <App />}
  </React.StrictMode>,
);

const productionHost = !['localhost', '127.0.0.1'].includes(window.location.hostname);
if ('serviceWorker' in navigator && productionHost) {
  window.addEventListener('load', () => {
    void navigator.serviceWorker.register('/sw.js');
  });
}
