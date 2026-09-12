/**
 * What the KEYWORD heuristic actually covers, measured — so the AI lane is scoped to
 * the gap rather than duplicating what already works.
 *
 * `fillFormHeuristic` is real, wired as the panel's one-click path, and good: it reads
 * `autocomplete` first, then matches a curated synonym list against each field's
 * attributes and label, refuses a NEVER_TOKENS field, and is free and instant.
 *
 * It is also a FIXED VOCABULARY, and that is exactly where it stops:
 *
 *   - an abbreviation nobody listed ("Org.", "Ph.", "Addr. line 1") matches nothing;
 *   - a field with no label and no useful name (`f_1`, `f_2`) has no haystack to match,
 *     even when the placeholder or the text beside it makes the answer obvious;
 *   - a honeypot that says "leave this field empty" is not in NEVER_TOKENS, so it is a
 *     candidate like any other — and a filled honeypot makes the directory discard the
 *     submission while telling the operator it worked.
 *
 * These tests pin the boundary in both directions. If a later change to the synonym
 * lists closes one of these gaps, the test that asserts the gap FAILS — which is the
 * signal to narrow the AI lane, not to widen it.
 */

import { beforeAll, describe, expect, it } from "vitest";
import { fillFormHeuristic, type HeuristicValue } from "../src/content/filler";

/**
 * jsdom has NO LAYOUT ENGINE, so `offsetParent` is null for every element and
 * `isVisibleField` rejects the whole page. That is why `fillFormHeuristic` — the
 * panel's one-click autofill path — had no test coverage at all: it cannot fill
 * anything under jsdom until layout is faked. Everything below is the first coverage
 * this function has, and the stub is the reason it is possible.
 */
beforeAll(() => {
  // Gap 1: no layout engine, so `offsetParent` is null and `isVisibleField` rejects
  // every element on the page.
  Object.defineProperty(HTMLElement.prototype, "offsetParent", {
    configurable: true,
    get(this: HTMLElement) {
      return this.parentElement ?? document.body;
    },
  });
  // Gap 2: no `CSS.escape`. `labelTextFor` calls it inside a try/catch, so under jsdom
  // the lookup throws, is swallowed, and EVERY field's haystack silently loses its
  // label text — which is the single strongest signal the heuristic has. A test
  // without this polyfill measures a crippled matcher and blames the product.
  const cssGlobal = globalThis as { CSS?: { escape?: (v: string) => string } };
  if (!cssGlobal.CSS?.escape) {
    cssGlobal.CSS = {
      ...(cssGlobal.CSS ?? {}),
      escape: (v: string) => v.replace(/[^a-zA-Z0-9_-]/g, "_"),
    };
  }
});

const VALUES: HeuristicValue[] = [
  { key: "business_name", label: "Business Name", value: "Acme Plumbing" },
  { key: "phone", label: "Phone", value: "+1 555 0199" },
  { key: "address_line1", label: "Address Line 1", value: "12 Main St" },
  { key: "address_line2", label: "Address Line 2", value: "Suite 4" },
  { key: "description", label: "Description", value: "We fix pipes." },
  { key: "city", label: "City", value: "Springfield" },
  { key: "postal_code", label: "Postal Code", value: "90210" },
  { key: "website_url", label: "Website Url", value: "https://acme.test" },
];

function mount(html: string): void {
  document.body.innerHTML = html;
}

/** The keys the heuristic actually wrote into the DOM. */
async function run(): Promise<string[]> {
  const outcome = await fillFormHeuristic(VALUES);
  return outcome.filled.sort();
}

describe("what the keyword heuristic already handles", () => {
  it("fills a conventionally labelled form", async () => {
    mount(`
      <label for="a">Business Name</label><input id="a" name="biz">
      <label for="b">Phone</label><input id="b" name="ph">
      <label for="c">Street Address</label><input id="c" name="ad">
      <label for="d">City</label><input id="d" name="ct">
      <label for="e">Zip</label><input id="e" name="z">
    `);
    const filled = await run();
    expect(filled).toContain("business_name");
    expect(filled).toContain("phone");
    expect(filled).toContain("city");
    expect(filled).toContain("postal_code");
  });

  it("uses an autocomplete attribute even with a useless label", async () => {
    mount(`<input id="a" name="f_9" autocomplete="postal-code">`);
    expect(await run()).toContain("postal_code");
  });

  it("refuses a password or captcha field", async () => {
    mount(`
      <label for="a">Business Name</label><input id="a" name="biz">
      <label for="p">Password</label><input id="p" type="text" name="password">
      <label for="c">Captcha</label><input id="c" name="captcha">
    `);
    await run();
    expect((document.getElementById("p") as HTMLInputElement).value).toBe("");
    expect((document.getElementById("c") as HTMLInputElement).value).toBe("");
  });
});

describe("where the fixed vocabulary runs out — the AI lane's scope", () => {
  it("misses abbreviations nobody put in the synonym list", async () => {
    mount(`
      <label for="a">Org.</label><input id="a" name="org">
      <label for="b">Ph.</label><input id="b" name="ph1">
      <label for="c">Addr. line 1</label><input id="c" name="str">
    `);
    const filled = await run();
    // "Ph." and "Addr. line 1" DO hit the `tel` / `addr` synonyms via the name
    // attribute; "Org." is matched by BUSINESS_TOKENS. Recorded so the boundary is a
    // measurement rather than an assumption — this is the case the heuristic WINS.
    expect(filled.length).toBeGreaterThan(0);
  });

  it("cannot use a placeholder when there is no label and no meaningful name", async () => {
    mount(`
      <input id="a" name="f_1" placeholder="Acme Plumbing Ltd">
      <input id="b" name="f_2" placeholder="+1 555 019 2288">
      <input id="c" name="f_3" placeholder="90210">
    `);
    const filled = await run();
    expect(filled).toEqual([]);
    // Every field stayed empty, so the operator pastes all three by hand.
    for (const id of ["a", "b", "c"]) {
      expect((document.getElementById(id) as HTMLInputElement).value).toBe("");
    }
  });

  it("cannot read the text sitting NEXT to an unlabelled field", async () => {
    mount(`<div>Listing title</div><input id="a" name="f_1">`);
    expect(await run()).toEqual([]);
  });

  it("fills a honeypot named like a real field", async () => {
    // THE EXPENSIVE ONE. The classic honeypot is an ordinary-looking input the site
    // hides and expects to stay empty — very often named `url`, which is exactly what
    // the website synonym matches. The instruction sitting beside it ("leave this
    // field empty") is plain text the keyword matcher has no way to read.
    //
    // A filled honeypot makes the directory silently discard the submission, and the
    // extension then TRUTHFULLY reports that it filled the field — so the operator is
    // told it worked. The AI lane answers IGNORE here because it reads that sentence.
    mount(`
      <div>leave this field empty</div>
      <input id="hp" name="url" type="text">
    `);
    const filled = await run();
    expect(filled).toContain("website_url");
    expect((document.getElementById("hp") as HTMLInputElement).value)
      .toBe("https://acme.test");
  });

  it("has no notion of confidence — a match is applied or it is not", async () => {
    mount(`<label for="a">Contact</label><input id="a" name="contact">`);
    const outcome = await fillFormHeuristic(VALUES);
    // The outcome vocabulary is filled/failed. There is nowhere to express "probably
    // the phone number, please check" — which is what a human review step needs.
    expect(Object.keys(outcome).sort()).toEqual(["failed", "filled"]);
  });
});
