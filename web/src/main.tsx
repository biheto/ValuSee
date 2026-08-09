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
