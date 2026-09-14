import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    host: '0.0.0.0',
    // THE DEV SERVER NEEDS THIS PROXY TO WORK AT ALL.
    //
    // `src/api/client.ts` sets `baseURL: ''`, so every request is a relative path and the API must
    // answer on the SAME ORIGIN as the page. In the container setup nginx provides that. Under
    // `npm run dev` nothing did: requests went to the Vite port, which serves the SPA catch-all, so
    // the browser received `index.html` with status 200 for every API call.
    //
    // That failure mode is worse than a connection error, and this repository has already paid for it
    // once: a page reported "no data" rather than an error because axios saw a 200 for a URL that
    // did not exist. Nothing looked broken, which is what made it slow to find.
    //
    // So the workflow documented in docs/how-to/local-setup.md — run the backend natively, run
    // `npm run dev` for the frontend — could not have worked. Now it does.
    proxy: {
      '/api': {
        target: process.env.VITE_DEV_API_TARGET ?? 'http://127.0.0.1:3001',
        changeOrigin: true,
      },
    },
  },
});
