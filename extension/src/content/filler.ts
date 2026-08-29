/**
 * Filling a directory's form without lying about whether it worked.
 *
 * THE FAILURE THIS FILE EXISTS TO PREVENT. Setting `el.value = x` on a React-controlled
 * input updates the DOM property and nothing else: React tracks values on an internal
 * `_valueTracker`, its synthetic `onChange` never fires, and on the next render the
 * component writes its own state back — an empty string. The operator sees a filled
 * form, presses submit, and the directory receives nothing. The extension, meanwhile,
 * reports nine fields filled.
 *
 * That is the same class of defect as reporting a screenshot as a live listing, and it
 * is why this file does two things that look redundant and are not:
 *
 *   1. writes through the PROTOTYPE's value setter, which is what React's tracker
 *      actually observes; and
 *   2. READS THE VALUE BACK after a frame and reports per-field success or failure.
 *
 * Without (2) the extension is confidently wrong. With it, the panel can say "7 of 9
 * filled, 2 rejected by the site" — which is the truth, and which tells the operator
 * exactly where to look.
 *
 * This script is injected on the operator's explicit click, never on navigation. That
 * keeps the permission at `activeTab` instead of `<all_urls>`, and it means a page is
 * only ever touched when a human asked for it.
 */

export type FieldPlanItem = {
  selector: string;
  valueKey: string;
  value: string;
};

export type FillOutcome = {
  filled: string[];
  failed: { key: string; reason: string }[];
};

/** The native setter React's `_valueTracker` watches, for whichever element this is. */
function nativeSetter(el: Element): ((v: string) => void) | null {
  const proto =
    el instanceof HTMLTextAreaElement
      ? HTMLTextAreaElement.prototype
      : el instanceof HTMLSelectElement
        ? HTMLSelectElement.prototype
        : el instanceof HTMLInputElement
          ? HTMLInputElement.prototype
          : null;
  if (!proto) return null;
  const desc = Object.getOwnPropertyDescriptor(proto, "value");
  const set = desc?.set;
  return set ? (v: string) => set.call(el, v) : null;
}

function fire(el: Element, ...types: string[]): void {
  for (const type of types) {
    el.dispatchEvent(new Event(type, { bubbles: true }));
  }
}

function setOne(el: Element, value: string): void {
  if (el instanceof HTMLSelectElement) {
    // Match by value, then by visible label — a directory's category dropdown usually
    // carries a numeric value and a human label, and we hold the label.
    const wanted = value.trim().toLowerCase();
    const idx = Array.from(el.options).findIndex(
      (o) => o.value.toLowerCase() === wanted || o.text.trim().toLowerCase() === wanted,
    );
    if (idx >= 0) el.selectedIndex = idx;
    fire(el, "input", "change");
    return;
  }

  if (el instanceof HTMLInputElement && (el.type === "checkbox" || el.type === "radio")) {
    const want = value !== "" && value !== "false" && value !== "0";
    if (el.checked !== want) {
      // `click`, not `change`: React's synthetic handler is bound to click for these,
      // and dispatching `change` alone leaves its state untouched.
      el.click();
    }
    return;
  }

  const set = nativeSetter(el);
  if (set) set(value);
  else (el as HTMLElement & { value?: string }).value = value;
  // `blur` matters for Angular and Vue validators, which often only run on touch.
  fire(el, "input", "change", "blur");
}

function readBack(el: Element): string {
  if (el instanceof HTMLSelectElement) {
    return el.options[el.selectedIndex]?.value ?? "";
  }
  if (el instanceof HTMLInputElement && (el.type === "checkbox" || el.type === "radio")) {
    return el.checked ? "on" : "";
  }
  return (el as HTMLElement & { value?: string }).value ?? "";
}

function matches(el: Element, wanted: string): boolean {
  const got = readBack(el).trim();
  if (el instanceof HTMLSelectElement) {
    const w = wanted.trim().toLowerCase();
    const label = el.options[el.selectedIndex]?.text.trim().toLowerCase() ?? "";
    return got.toLowerCase() === w || label === w;
  }
  if (el instanceof HTMLInputElement && (el.type === "checkbox" || el.type === "radio")) {
    return (got === "on") === (wanted !== "" && wanted !== "false" && wanted !== "0");
  }
  return got === wanted.trim();
}

const nextFrame = (): Promise<void> =>
  new Promise((resolve) => requestAnimationFrame(() => resolve()));

/**
 * Fill every field in the plan and report, per field, what actually stuck.
 *
 * A missing selector and a rejected value are DIFFERENT failures and are reported
 * differently: the first means the spec has drifted from the live form (and the backend
 * deactivates the spec on that signal), the second means the site refused the value.
 * Collapsing them would throw away the only clue that distinguishes "fix the spec" from
 * "fix the data".
 */
export async function fillForm(plan: FieldPlanItem[]): Promise<FillOutcome> {
  const out: FillOutcome = { filled: [], failed: [] };

  for (const item of plan) {
    let el: Element | null = null;
    try {
      el = document.querySelector(item.selector);
    } catch {
      out.failed.push({ key: item.valueKey, reason: "invalid_selector" });
      continue;
    }
    if (!el) {
      out.failed.push({ key: item.valueKey, reason: "selector_not_found" });
      continue;
    }
    try {
      setOne(el, item.value);
    } catch {
      out.failed.push({ key: item.valueKey, reason: "set_threw" });
      continue;
    }
    out.filled.push(item.valueKey);
  }

  // ONE frame, after everything is written. A React re-render that reverts a field
  // happens on the next tick, so reading immediately would confirm a value that is about
  // to disappear — which is precisely the lie this read-back exists to catch.
  await nextFrame();

  const reverted: string[] = [];
  for (const item of plan) {
    if (!out.filled.includes(item.valueKey)) continue;
    let el: Element | null = null;
    try {
      el = document.querySelector(item.selector);
    } catch {
      el = null;
    }
    if (!el || !matches(el, item.value)) {
      reverted.push(item.valueKey);
      out.failed.push({ key: item.valueKey, reason: "reverted_by_page" });
    }
  }
  out.filled = out.filled.filter((k) => !reverted.includes(k));
  return out;
}

