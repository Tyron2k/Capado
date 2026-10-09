/// <reference types="vitest" />
import { configDefaults, defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  test: {
    globals: true,
    exclude: [...configDefaults.exclude, 'e2e/**'],
    environment: 'jsdom',
    // Property-based jsdom tests occasionally exceed the 5s default when the
    // suite runs several workers in parallel.
    testTimeout: 15000,
  },
});
