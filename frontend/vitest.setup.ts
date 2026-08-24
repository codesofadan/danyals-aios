// jest-dom's matchers (`toBeInTheDocument`, `toHaveTextContent`, …) and an automatic
// DOM cleanup between tests, so one test's render cannot be found by the next one.
import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(cleanup);
