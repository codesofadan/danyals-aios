import { beforeEach, describe, expect, it } from "vitest";
import { fillForm } from "../src/content/filler";

/**
 * The read-back is the point of this file.
 *
 * A filler that only writes values is confidently wrong on any React-controlled form:
 * the value goes into the DOM, the framework reverts it on the next render, and the
 * operator submits an empty form believing it was filled.
 */

function html(markup: string): void {
  document.body.innerHTML = markup;
}

describe("fillForm", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
  });

  it("fills a plain text input and reports it", async () => {
    html(`<input id="name">`);
    const out = await fillForm([
      { selector: "#name", valueKey: "business_name", value: "Acme Dental" },
    ]);
    expect(out.filled).toEqual(["business_name"]);
    expect(out.failed).toEqual([]);
    expect((document.querySelector("#name") as HTMLInputElement).value).toBe("Acme Dental");
  });

  it("writes through the prototype setter, which is what a framework observes", async () => {
    html(`<input id="name">`);
    const el = document.querySelector("#name") as HTMLInputElement;
    const seen: string[] = [];
    // Stand in for React's `_valueTracker`: it only learns about a write that goes
    // through the prototype's setter. A direct `el.value = x` assignment is invisible.
    el.addEventListener("input", () => seen.push(el.value));

    await fillForm([{ selector: "#name", valueKey: "business_name", value: "Acme" }]);
    expect(seen).toEqual(["Acme"]);
  });

  it("dispatches input, change AND blur", async () => {
    html(`<input id="name">`);
    const el = document.querySelector("#name") as HTMLInputElement;
    const types: string[] = [];
    for (const t of ["input", "change", "blur"]) {
      el.addEventListener(t, () => types.push(t));
    }
    await fillForm([{ selector: "#name", valueKey: "k", value: "v" }]);
    // blur matters for Angular/Vue validators, which often only run on touch.
    expect(types).toEqual(["input", "change", "blur"]);
  });

  it("CATCHES a page that reverts the value, instead of reporting success", async () => {
    // The exact React failure: the component writes its own state back on the next
    // tick. Without a read-back the extension would report this field as filled.
    html(`<input id="name">`);
    const el = document.querySelector("#name") as HTMLInputElement;
    el.addEventListener("input", () => {
      queueMicrotask(() => {
        el.value = "";
      });
    });

    const out = await fillForm([
      { selector: "#name", valueKey: "business_name", value: "Acme Dental" },
    ]);
    expect(out.filled).toEqual([]);
    expect(out.failed).toEqual([{ key: "business_name", reason: "reverted_by_page" }]);
  });

  it("distinguishes a missing selector from a rejected value", async () => {
    // Different failures with different fixes: the first means the SPEC drifted from the
    // live form, the second means the site refused the DATA. Collapsing them throws away
    // the only clue that says which.
    html(`<input id="present">`);
    const out = await fillForm([
      { selector: "#present", valueKey: "a", value: "x" },
      { selector: "#gone", valueKey: "b", value: "y" },
    ]);
    expect(out.filled).toEqual(["a"]);
    expect(out.failed).toEqual([{ key: "b", reason: "selector_not_found" }]);
  });

  it("survives an invalid selector rather than aborting the whole fill", async () => {
    html(`<input id="present">`);
    const out = await fillForm([
      { selector: "((((", valueKey: "bad", value: "x" },
      { selector: "#present", valueKey: "good", value: "y" },
    ]);
    expect(out.failed).toEqual([{ key: "bad", reason: "invalid_selector" }]);
    expect(out.filled).toEqual(["good"]);
  });

  it("selects a dropdown option by its visible label, not only its value", async () => {
    // A directory's category select usually carries a numeric value and a human label,
    // and the canonical profile holds the label.
    html(`<select id="cat"><option value="1">Dentist</option><option value="2">Plumber</option></select>`);
    const out = await fillForm([{ selector: "#cat", valueKey: "category", value: "Dentist" }]);
    expect(out.filled).toEqual(["category"]);
    expect((document.querySelector("#cat") as HTMLSelectElement).value).toBe("1");
  });

  it("reports a dropdown that has no matching option", async () => {
    html(`<select id="cat"><option value="1">Dentist</option></select>`);
    const out = await fillForm([{ selector: "#cat", valueKey: "category", value: "Astronaut" }]);
    expect(out.filled).toEqual([]);
    expect(out.failed[0]?.reason).toBe("reverted_by_page");
  });

  it("ticks a checkbox with click, which is what a synthetic handler listens for", async () => {
    html(`<input type="checkbox" id="tos">`);
    const el = document.querySelector("#tos") as HTMLInputElement;
    const clicks: number[] = [];
    el.addEventListener("click", () => clicks.push(1));

    const out = await fillForm([{ selector: "#tos", valueKey: "accept", value: "true" }]);
    expect(el.checked).toBe(true);
    expect(clicks).toHaveLength(1);
    expect(out.filled).toEqual(["accept"]);
  });

  it("does not re-click a checkbox that is already in the wanted state", async () => {
    html(`<input type="checkbox" id="tos" checked>`);
    const el = document.querySelector("#tos") as HTMLInputElement;
    const clicks: number[] = [];
    el.addEventListener("click", () => clicks.push(1));
    await fillForm([{ selector: "#tos", valueKey: "accept", value: "true" }]);
    expect(clicks).toHaveLength(0);
    expect(el.checked).toBe(true);
  });

  it("fills a textarea", async () => {
    html(`<textarea id="desc"></textarea>`);
    const out = await fillForm([{ selector: "#desc", valueKey: "description", value: "Hello" }]);
    expect(out.filled).toEqual(["description"]);
    expect((document.querySelector("#desc") as HTMLTextAreaElement).value).toBe("Hello");
  });

  it("an empty plan is a clean no-op", async () => {
    expect(await fillForm([])).toEqual({ filled: [], failed: [] });
  });
});
