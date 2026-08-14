import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Tauri drives this dev server, so the port is fixed and failure to bind must
// be an error rather than a silent hop to another port the shell won't find.
export default defineConfig({
  plugins: [react()],
  clearScreen: false,
  server: {
    port: 1420,
    strictPort: true,
    watch: {
      // Rust rebuilds are Cargo's job; watching them would restart Vite on
      // every incremental compile.
      ignored: ["**/src-tauri/**", "**/target/**", "**/crates/**"],
    },
  },
  build: {
    // NOT `dist/` — that still holds the legacy PyInstaller AutoTidy.exe, and
    // Vite empties its output directory on every build. Keeping the frontend
    // in its own folder means the v1.5.0 artifact survives until cutover
    // deliberately retires it, rather than being deleted as a side effect.
    outDir: "dist-web",
    emptyOutDir: true,
    target: "chrome110",
    sourcemap: false,
    // The bundle ships inside the installer, so size is worth the build time.
    minify: "esbuild",
  },
});
