import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    globals: true,
    // The filler manipulates real DOM elements and depends on how a browser reports a
    // value back, so it must run against a DOM rather than a mock.
    environment: "jsdom",
    include: ["tests/**/*.test.ts"],
  },
});
