// Vitest for the dashboard. Until 2026-08-24 the frontend had NO test runner at all —
// `frontend-ci.yml` ran a typecheck and a build, which prove the code COMPILES and
// nothing more. Neither can tell you whether a component renders what it claims to.
//
// jsdom, not a browser: these are component tests, and the things worth pinning here
// (does the error boundary render the message it must never render? does reset fire?)
// are DOM-level facts that do not need a real engine. End-to-end coverage of the Next
// runtime is a separate concern and is not pretended at here.

import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";
import { fileURLToPath } from "node:url";

export default defineConfig({
  plugins: [react()],
  resolve: {
    // Mirror the `@/*` path alias from tsconfig.json, or every import in a test
    // resolves differently from the same import in the app.
    alias: { "@": fileURLToPath(new URL("./", import.meta.url)) },
  },
  // Next sets `"jsx": "preserve"` in tsconfig so its own compiler owns the transform.
  // Vitest's esbuild honours that and emits untransformed JSX, which fails at runtime
  // with "React is not defined". Pin the automatic runtime here so a test file
  // compiles the same way the app does without needing a React import in every file.
  esbuild: { jsx: "automatic" },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
    include: ["**/*.test.{ts,tsx}"],
    exclude: ["node_modules/**", ".next/**"],
  },
});
