import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { viteSingleFile } from 'vite-plugin-singlefile';

// The cloud control plane (server.py) is a single-file deployment. To keep that
// spirit — and avoid teaching the Python server to serve hashed asset chunks —
// we build the whole React app into ONE self-contained index.html (all JS/CSS
// inlined). server.py serves that file at "/" and the browser talks to the same
// REST API the old inline page used.
export default defineConfig({
  plugins: [react(), viteSingleFile()],
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    // one file, no external chunks
    assetsInlineLimit: 100000000,
    chunkSizeWarningLimit: 100000000,
    cssCodeSplit: false,
  },
});
