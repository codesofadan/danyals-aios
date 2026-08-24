// ESLint flat config for the dashboard.
//
// WHY THIS FILE EXISTS. `npm run lint` ran `next lint`, and with no config present
// that command drops into an INTERACTIVE PROMPT asking which preset to install. So the
// dashboard's lint step could not run at all — not locally, and certainly not in CI,
// where an interactive prompt hangs the job rather than failing it. The plan records
// this as "get ESLint running (it currently cannot)".
//
// `next lint` is also deprecated and is removed in Next.js 16, so the script now calls
// the ESLint CLI directly and this flat config replaces the prompt.
//
// WHAT IS ON, and why it is this and not "strict". The dashboard is ~27k lines written
// without a linter, so switching on a maximal preset would produce a wall of findings
// that gets suppressed wholesale — which is worse than no linter, because it looks like
// coverage. This config turns on the rules that catch REAL defects in this codebase's
// idiom, and leaves style to the reviewer:
//
//   * next/core-web-vitals — the Next.js correctness rules, including the App Router
//     server/client boundary mistakes that `tsc` cannot see.
//   * react-hooks/rules-of-hooks + exhaustive-deps — this app is built on react-query
//     and context; a missing dependency here is a stale-render bug, and `ClientContext`
//     already carries a hand-written comment explaining a deps subtlety it got wrong
//     once.
//   * no-unused-vars via TypeScript's own rule, with the `_` prefix escape hatch the
//     backend already uses.
//
// Anything that fires today is a real finding to fix or to justify, not noise to mute.

import { FlatCompat } from "@eslint/eslintrc";

const compat = new FlatCompat({ baseDirectory: import.meta.dirname });

const config = [
  {
    // Generated, vendored, or not ours. `.next` in particular contains emitted code
    // that will never satisfy any rule and is rebuilt on every run.
    ignores: [
      ".next/**",
      "node_modules/**",
      "out/**",
      "public/**",
      "next-env.d.ts",
    ],
  },
  ...compat.extends("next/core-web-vitals", "next/typescript"),
  {
    rules: {
      // A dependency array that lies is a stale render. Warn rather than error: the
      // fix is sometimes a deliberate `useRef`, and this codebase has at least one
      // documented case, so a hard failure would push people to blanket-disable it.
      "react-hooks/exhaustive-deps": "warn",

      // Unused code in a 27k-line app that has never been linted is mostly ORPHANS —
      // the plan estimates ~5,900 lines of them. Surfacing it is the point; `_`-prefixed
      // names stay legal so a deliberately-ignored parameter reads as deliberate.
      "@typescript-eslint/no-unused-vars": [
        "error",
        {
          argsIgnorePattern: "^_",
          varsIgnorePattern: "^_",
          caughtErrorsIgnorePattern: "^_",
        },
      ],

      // `any` erases the contract the whole `lib/*.ts` type layer exists to enforce —
      // those types are locked against the backend's response models by
      // `backend/tests/test_contract_lock.py`, and an `any` on the way through defeats
      // that lock silently. Warn for now: this is a pre-existing debt to pay down, not
      // a reason to block the build on day one.
      "@typescript-eslint/no-explicit-any": "warn",
    },
  },
];

export default config;
