// jest-dom's matchers (`toBeInTheDocument`, `toHaveTextContent`, …) and an automatic
// DOM cleanup between tests, so one test's render cannot be found by the next one.
import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(cleanup);

// jsdom implements no `matchMedia`, and 24 components call
// `matchMedia("(prefers-reduced-motion: reduce)")` during render or in an effect to
// decide whether to animate. Without this, rendering any of them in a test throws
// "matchMedia is not a function" — a failure about the environment, not the component.
//
// Reports "no preference" so animated paths are the ones under test; a test that cares
// about the reduced-motion branch can override this per-case.
if (typeof window !== "undefined" && !window.matchMedia) {
  window.matchMedia = ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
}
