/**
 * The collector: what leaves the browser, and can the selectors find things again?
 *
 * **THE MOST IMPORTANT TEST IN THIS FILE** is
 * `a credential-shaped field is never described`.
 *
 * This is the boundary where a convenience becomes an exfiltration path. The digest
 * goes to a model; a page is visited while the operator is signed into ~50 third-party
 * directories. So the collector is a WHITELIST of field kinds, it refuses anything
 * named or labelled like a credential, and it carries no field VALUE at all — the
 * returned type has no value property, which is the strongest form of that guarantee.
 * The server sanitises again on arrival: two independent passes, on purpose.
 *
 * The second thing pinned here is that every emitted selector actually RESOLVES back
 * to the element it describes. A selector that works in the abstract and misses on the
 * page produces `selector_not_found` for every field and an operator who pastes eight
 * values by hand anyway.
 *
 * jsdom notes: it has no layout engine (`offsetParent` is null for everything) and no
 * `CSS.escape`, so both are stubbed. Without the first, `isVisible` rejects the whole
 * page and the collector returns nothing.
 */

import { beforeAll, describe, expect, it } from "vitest";
import { collectFormFields, type CollectedField } from "../src/content/collector";

beforeAll(() => {
  Object.defineProperty(HTMLElement.prototype, "offsetParent", {
    configurable: true,
    get(this: HTMLElement) {
      return this.parentElement ?? document.body;
    },
  });
  const cssGlobal = globalThis as { CSS?: { escape?: (v: string) => string } };
  if (!cssGlobal.CSS?.escape) {
    cssGlobal.CSS = {
      ...(cssGlobal.CSS ?? {}),
      escape: (v: string) => v.replace(/[^\w-]/g, "_"),
    };
  }
});

function mount(html: string): void {
  document.body.innerHTML = html;
}

/** The first collected field, asserted present - `noUncheckedIndexedAccess` makes a
 * bare `[0]` possibly-undefined, and every test below genuinely expects one. */
function first(): CollectedField {
  const fields = collectFormFields();
  expect(fields.length).toBeGreaterThan(0);
  return fields[0] as CollectedField;
}


describe("the privacy boundary", () => {
  it("a credential-shaped field is never described", () => {
    // Matched on name, id OR label - a field called one thing and labelled another
    // must still be refused.
    mount(`
      <label for="a">Business name</label><input id="a" name="company">
      <input id="p1" name="account_password" type="text">
      <input id="p2" name="x" aria-label="Password">
      <input id="p6" name="y" autocomplete="cc-number">
      <label for="p3">CVV</label><input id="p3" name="q">
      <input id="p4" name="csrf_token" type="text">
      <input id="p5" name="cc_number" type="text">
    `);
    const fields = collectFormFields();
    const blob = JSON.stringify(fields);
    for (const secret of ["password", "Password", "csrf", "cc_number", "cc-number", "CVV"]) {
      expect(blob).not.toContain(secret);
    }
    expect(fields.map((f) => f.name)).toEqual(["company"]);
  });

  it("never carries a value the operator typed", () => {
    mount(`<label for="a">Phone</label><input id="a" name="phone" value="+1 555 0199">`);
    const field = first();
    expect(JSON.stringify(field)).not.toContain("555");
    expect("value" in field).toBe(false);
  });

  it("skips the input kinds that are never listing data", () => {
    mount(`
      <label for="a">Business name</label><input id="a" name="company">
      <input id="b" name="logo" type="file">
      <input id="c" name="h" type="hidden">
      <input id="d" type="submit" value="Go">
      <input id="e" name="pw" type="password">
    `);
    expect(collectFormFields().map((f) => f.name)).toEqual(["company"]);
  });

  it("skips disabled and read-only fields", () => {
    mount(`
      <label for="a">Business name</label><input id="a" name="company">
      <input id="b" name="locked" disabled>
      <input id="c" name="ro" readonly>
    `);
    expect(collectFormFields().map((f) => f.name)).toEqual(["company"]);
  });

  it("bounds the field count and every text length", () => {
    const many = Array.from({ length: 120 }, (_, i) =>
      `<input id="f${i}" name="f${i}" placeholder="${"x".repeat(500)}">`).join("");
    mount(many);
    const fields = collectFormFields();
    expect(fields.length).toBe(60);
    for (const f of fields) expect(f.placeholder.length).toBeLessThanOrEqual(160);
  });
});

describe("finding the label a human actually reads", () => {
  it("reads a bound label", () => {
    mount(`<label for="a">Company Name</label><input id="a" name="x">`);
    expect(first().label).toBe("Company Name");
  });

  it("reads an ancestor label", () => {
    mount(`<label>Contact Number <input name="x"></label>`);
    expect(first().label).toBe("Contact Number");
  });

  it("reads aria-labelledby", () => {
    mount(`<span id="lab">Web Address</span><input name="x" aria-labelledby="lab">`);
    expect(first().label).toBe("Web Address");
  });

  it("falls back to the text sitting beside an unlabelled field", () => {
    // THE CASE THAT RESCUES THE WORST FORMS. `f_1` with no label at all, where a div
    // above the box is the only thing a human reads either - and the exact case the
    // keyword heuristic provably cannot handle.
    mount(`<div>Listing title</div><input id="f_1" name="f_1">`);
    expect(first().near).toBe("Listing title");
  });

  it("does not send nearby text when a real label exists", () => {
    mount(`<div>Some unrelated blurb</div>
           <label for="a">Business name</label><input id="a" name="x">`);
    const field = first();
    expect(field.label).toBe("Business name");
    expect(field.near).toBe("");
  });

  it("refuses a long paragraph as nearby text", () => {
    mount(`<div>${"terms and conditions ".repeat(20)}</div><input id="f_1" name="f_1">`);
    expect(first().near).toBe("");
  });
});

describe("selectors that survive a reload", () => {
  function resolves(selector: string): boolean {
    try {
      return document.querySelector(selector) !== null;
    } catch {
      return false;
    }
  }

  it("every emitted selector resolves to an element", () => {
    mount(`
      <label for="biz">Business</label><input id="biz" name="company">
      <input name="phone">
      <div><div><input placeholder="anonymous"></div></div>
      <select name="state"><option>Florida</option></select>
      <textarea name="about"></textarea>
    `);
    const fields = collectFormFields();
    expect(fields.length).toBe(5);
    for (const f of fields) {
      expect(resolves(f.selector), `${f.selector} did not resolve`).toBe(true);
    }
  });

  it("prefers an authored id", () => {
    mount(`<input id="business-name" name="x">`);
    expect(first().selector).toBe("#business-name");
  });

  it("refuses a generated id and falls back to something stable", () => {
    // A framework-generated id changes every reload, so a selector built on it works
    // exactly once - and would poison the cache if it fed the fingerprint.
    mount(`<input id="radix-12345" name="company">`);
    const selector = first().selector;
    expect(selector).not.toContain("radix");
    expect(resolves(selector)).toBe(true);
  });

  it("does not use a name shared by a radio group", () => {
    // `input[name="pick"]` matches three elements; filling "the" radio would pick
    // whichever came first.
    mount(`
      <input type="radio" name="pick" id="r1">
      <input type="radio" name="pick" id="r2">
      <input type="radio" name="pick" id="r3">
    `);
    for (const f of collectFormFields()) {
      expect(document.querySelectorAll(f.selector).length).toBe(1);
    }
  });

  it("never builds a selector out of class names", () => {
    // Generated class names (`css-1a2b3c`) change per build and per page load.
    mount(`<div class="css-1a2b3c"><input class="css-9z8y7x" name="company"></div>`);
    const selector = first().selector;
    expect(selector).not.toContain("css-");
    expect(selector).not.toContain(".");
  });
});

describe("what the server needs to reason", () => {
  it("carries select option labels", () => {
    mount(`<label for="s">State</label>
           <select id="s" name="st"><option>Select</option><option>Florida</option></select>`);
    expect(first().options).toEqual(["Select", "Florida"]);
  });

  it("caps the option list", () => {
    const opts = Array.from({ length: 80 }, (_, i) => `<option>Opt ${i}</option>`).join("");
    mount(`<select id="s" name="st">${opts}</select>`);
    expect(first().options.length).toBe(25);
  });

  it("carries required, from either the attribute or aria", () => {
    mount(`<input id="a" name="a" required>
           <input id="b" name="b" aria-required="true">
           <input id="c" name="c">`);
    expect(collectFormFields().map((f) => f.required)).toEqual([true, true, false]);
  });

  it("carries the step of a multi-step form", () => {
    mount(`<div data-step="2"><input id="a" name="a"></div><input id="b" name="b">`);
    const byName = Object.fromEntries(collectFormFields().map((f) => [f.name, f.step]));
    expect(byName.a).toBe(2);
    expect(byName.b).toBe(0);
  });

  it("reports the field kind, not just the tag", () => {
    mount(`<input id="a" name="a" type="tel">
           <textarea id="b" name="b"></textarea>
           <select id="c" name="c"></select>`);
    expect(collectFormFields().map((f) => f.kind)).toEqual(["tel", "textarea", "select"]);
  });
});
