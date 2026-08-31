import { resolve } from "node:path";
import { copyFileSync, mkdirSync } from "node:fs";
import { defineConfig, type Plugin } from "vite";

// The manifest and the panel document are STATIC and must land beside the bundles, or
// `dist/` is not a loadable extension. Copying them in the build (rather than asking a
// human to remember) is what makes "load unpacked dist/" the whole install procedure.
function copyStatic(): Plugin {
  return {
    name: "aios-copy-static",
    closeBundle() {
      mkdirSync("dist", { recursive: true });
      copyFileSync("manifest.json", "dist/manifest.json");
      copyFileSync("src/sidepanel/index.html", "dist/panel.html");
      copyFileSync("src/sidepanel/panel.css", "dist/panel.css");
    },
  };
}

// Three separate entry points, because an MV3 extension has three isolated worlds: the
// service worker (the ONLY code that talks to the API), the side panel document, and the
// content script that is injected into a directory's page on demand. Bundling them
// together would let a content script import the API client — and with it the operator
// token — into a renderer shared with hostile page JavaScript.
export default defineConfig({
  plugins: [copyStatic()],
  build: {
    outDir: "dist",
    emptyOutDir: true,
    rollupOptions: {
      input: {
        "service-worker": resolve(__dirname, "src/background/service-worker.ts"),
        panel: resolve(__dirname, "src/sidepanel/panel.ts"),
        filler: resolve(__dirname, "src/content/filler-entry.ts"),
      },
      output: {
        entryFileNames: "[name].js",
        // No shared chunks: each world loads exactly its own file. MV3's CSP forbids
        // remote code anyway, so there is nothing to gain from splitting.
        inlineDynamicImports: false,
        manualChunks: undefined,
      },
    },
  },
});
