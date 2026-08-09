import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': process.env.VALUSee_API_TARGET || 'http://127.0.0.1:8100',
      '/health': process.env.VALUSee_API_TARGET || 'http://127.0.0.1:8100',
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
});
