/**
 * Every `.modal-scrim` must sit under a `.tw` ancestor the component provides itself.
 *
 * THE BUG THIS EXISTS TO STOP, which has now shipped four separate times:
 * `globals.css` scopes the overlay as `.tw .modal-scrim`, and the ADMIN LAYOUT
 * PROVIDES NO `.tw`. A modal that does not self-wrap therefore gets no `position:
 * fixed`, no scrim and no centring — it renders as a plain block at the BOTTOM OF THE
 * PAGE. The operator clicks a button in a table row and the confirmation appears a
 * screen and a half below, off-view, looking like the page simply did nothing.
 *
 * It is invisible to a type-checker, invisible to lint, and invisible to a component
 * test that renders the dialog on its own (there is no admin layout in jsdom, and the
 * stylesheet is not loaded either). The only cheap way to catch it is to read the
 * source, which is what this does — including for files nobody has written yet.
 *
 * Caught in production use: "when we press get link on audit card, it takes us to end
 * of page to confirm" — that was `ConfirmDialog`, shared by every confirmation in the
 * admin area.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const ROOTS = ["components", "app"];

function walk(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    if (entry === "node_modules" || entry.startsWith(".")) continue;
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) walk(full, out);
    else if (entry.endsWith(".tsx") && !entry.endsWith(".test.tsx")) out.push(full);
  }
  return out;
}

const sources = ROOTS.flatMap((r) => walk(r)).map((path) => ({
  path,
  text: readFileSync(path, "utf8"),
}));

describe("modal overlays are scoped so they actually overlay", () => {
  const overlays = sources.filter((f) => f.text.includes('className="modal-scrim"'));

  it("finds the modal components at all (guards the guard)", () => {
    // If a refactor renames the class, this test would otherwise pass by checking
    // nothing at all — which is the failure mode of every source-scanning test.
    expect(overlays.length).toBeGreaterThan(5);
  });

  it.each(overlays.map((f) => f.path))("%s wraps its scrim in .tw", (path) => {
    const text = sources.find((f) => f.path === path)!.text;
    expect(
      /className="tw(\s|")/.test(text),
      `${path} renders .modal-scrim but never sets a "tw" class. The overlay CSS is ` +
        `scoped ".tw .modal-scrim", so without it this dialog renders inline at the ` +
        `bottom of the page instead of over it. Wrap the return in <div className="tw">.`,
    ).toBe(true);
  });
});
