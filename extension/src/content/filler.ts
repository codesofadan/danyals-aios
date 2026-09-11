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

// US state <-> abbreviation, so a "FL" region value can select a "Florida" option and
// vice versa. US-only and small on purpose; other markets fall back to text matching.
const US_STATES: Record<string, string> = {
  al: "alabama", ak: "alaska", az: "arizona", ar: "arkansas", ca: "california",
  co: "colorado", ct: "connecticut", de: "delaware", fl: "florida", ga: "georgia",
  hi: "hawaii", id: "idaho", il: "illinois", in: "indiana", ia: "iowa", ks: "kansas",
  ky: "kentucky", la: "louisiana", me: "maine", md: "maryland", ma: "massachusetts",
  mi: "michigan", mn: "minnesota", ms: "mississippi", mo: "missouri", mt: "montana",
  ne: "nebraska", nv: "nevada", nh: "new hampshire", nj: "new jersey", nm: "new mexico",
  ny: "new york", nc: "north carolina", nd: "north dakota", oh: "ohio", ok: "oklahoma",
  or: "oregon", pa: "pennsylvania", ri: "rhode island", sc: "south carolina",
  sd: "south dakota", tn: "tennessee", tx: "texas", ut: "utah", vt: "vermont",
  va: "virginia", wa: "washington", wv: "west virginia", wi: "wisconsin", wy: "wyoming",
  dc: "district of columbia",
};

/**
 * Choose the option that best represents `value` for a <select>, in decreasing
 * confidence: exact value/label, US-state abbreviation<->name, an exact comma/slash
 * token, then a contains-match. Returns -1 when nothing plausible fits — better to
 * leave a dropdown untouched than to pick a wrong option. A leading "Please select"
 * placeholder is never chosen. This is what lets a country/state/category value fill a
 * DROPDOWN as readily as a text box.
 */
function bestOptionIndex(el: HTMLSelectElement, value: string): number {
  const opts = Array.from(el.options);
  const norm = (s: string): string => s.trim().toLowerCase();
  const w = norm(value);
  if (!w) return -1;

  const accepted = new Set<string>([w]);
  const expansion = US_STATES[w];
  if (expansion) accepted.add(expansion);
  for (const [ab, full] of Object.entries(US_STATES)) if (full === w) accepted.add(ab);
  for (const tok of value.split(/[,/|]/).map(norm)) if (tok) accepted.add(tok);

  const first = opts[0];
  const firstIsPlaceholder =
    !!first && (first.value === "" || /select|choose|please|--/.test(norm(first.text)));
  const usable = (i: number): boolean => !(i === 0 && firstIsPlaceholder);

  for (let i = 0; i < opts.length; i++) {
    const o = opts[i];
    if (!o || !usable(i)) continue;
    if (accepted.has(norm(o.value)) || accepted.has(norm(o.text))) return i;
  }
  for (let i = 0; i < opts.length; i++) {
    const o = opts[i];
    if (!o || !usable(i)) continue;
    const t = norm(o.text);
    if (t.length < 3) continue;
    for (const cand of accepted) {
      if (cand.length >= 3 && (t.includes(cand) || cand.includes(t))) return i;
    }
  }
  return -1;
}

function setOne(el: Element, value: string): void {
  if (el instanceof HTMLSelectElement) {
    const idx = bestOptionIndex(el, value);
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

// ============================================================================
// BEST-EFFORT AUTOFILL (no earned spec).
//
// When a directory has NO verified spec, there are no selectors — but copying ten
// fields by hand across ten sites is the friction this exists to remove. This matches
// each business value to the page's OWN form fields by the same signals a browser's
// built-in autofill uses (the `autocomplete` attribute first, then name / id /
// placeholder / aria-label / the associated <label> text), and fills the ones it can
// identify.
//
// It is deliberately conservative and HONEST, never "magic":
//   • it never touches a password, CAPTCHA, checkbox/radio, hidden or disabled field;
//   • a business name is never dropped into a person-name field (first/last/your name);
//   • every value is READ BACK (same as fillForm) so the panel reports what actually
//     stuck, and a wrong guess is visible on the page before the operator submits;
//   • NOTHING is ever submitted here — the human reviews and submits.
// A field it cannot confidently identify is left for the copy-buttons.
// ============================================================================

export type HeuristicValue = { key: string; label: string; value: string };

const AUTOCOMPLETE_TOKENS: Record<string, string[]> = {
  email: ["email"],
  phone: ["tel", "tel-national", "tel-local"],
  postal_code: ["postal-code"],
  website_url: ["url"],
  city: ["address-level2"],
  region: ["address-level1"],
  country: ["country", "country-name"],
  address_line1: ["address-line1", "street-address"],
  address_line2: ["address-line2"],
  business_name: ["organization"],
};

const SYNONYMS: Record<string, string[]> = {
  email: ["email", "e mail"],
  phone: ["phone", "telephone", "tel", "mobile", "cell", "contact number"],
  postal_code: ["zip", "zipcode", "postal", "postcode", "post code"],
  website_url: ["website", "web site", "url", "homepage", "web address", "site url"],
  city: ["city", "town", "locality", "suburb"],
  region: ["state", "province", "region", "county"],
  country: ["country", "nation"],
  address_line2: ["address line 2", "address2", "apt", "apartment", "suite", "unit", "floor"],
  address_line1: ["address", "street", "addr", "address line 1", "address1"],
  business_name: [], // matched by matchesBusinessName (person-name-safe)
  description: ["description", "about", "bio", "details", "summary", "overview", "message"],
  sub_category: ["sub category", "subcategory", "sub-category", "secondary category", "sub type"],
  category: ["category", "categories", "industry", "business type", "type of business", "primary category"],
};

// Specific, unambiguous keys FIRST, so an email field is claimed by `email` before a
// looser "address"/"name" rule can grab it. `country` before `region` so a "state"
// rule never grabs the country box, and before `address` since both mention location.
// `sub_category` before `category` so "sub category" is claimed before a bare
// "category" rule can grab that box.
const KEY_PRIORITY = [
  "email", "phone", "postal_code", "website_url", "city", "country", "region",
  "address_line2", "address_line1", "business_name", "sub_category", "category", "description",
];

const BUSINESS_TOKENS = [
  "business", "company", "organization", "organisation", "org", "listing",
  "trade name", "establishment", "venue", "practice", "store", "shop", "brand", "firm",
];
const PERSON_TOKENS = [
  "first name", "last name", "your name", "full name", "contact name",
  "given name", "surname", "middle name", "user name", "username",
];
const NEVER_TOKENS = [
  "captcha", "recaptcha", "hcaptcha", "password", "passwd", "pwd", "passcode",
  "otp", "one time", "security code", "verification code", "verify code", "confirm",
];

function labelTextFor(el: Element): string {
  const parts: string[] = [];
  const id = el.getAttribute("id");
  if (id) {
    try {
      const forLabel = document.querySelector(`label[for="${CSS.escape(id)}"]`);
      if (forLabel?.textContent) parts.push(forLabel.textContent);
    } catch {
      /* an id that CSS.escape cannot handle is simply skipped */
    }
  }
  const wrapping = el.closest("label");
  if (wrapping?.textContent) parts.push(wrapping.textContent);
  const labelledby = el.getAttribute("aria-labelledby");
  if (labelledby) {
    for (const lid of labelledby.split(/\s+/)) {
      const n = document.getElementById(lid);
      if (n?.textContent) parts.push(n.textContent);
    }
  }
  return parts.join(" ");
}

function fieldHaystack(el: Element): string {
  const bits = ["name", "id", "placeholder", "aria-label", "title"].map((a) => el.getAttribute(a) ?? "");
  bits.push(labelTextFor(el));
  return bits.join(" ").toLowerCase().replace(/[_\-]+/g, " ");
}

function isVisibleField(el: HTMLElement): boolean {
  if (el.offsetParent !== null) return true;
  const style = window.getComputedStyle(el);
  // offsetParent is null for position:fixed too — those can still be real inputs.
  return style.position === "fixed" && style.display !== "none" && style.visibility !== "hidden";
}

function isFillableField(el: Element): boolean {
  if (el instanceof HTMLTextAreaElement) return !el.disabled && !el.readOnly;
  if (el instanceof HTMLSelectElement) return !el.disabled;
  if (el instanceof HTMLInputElement) {
    const bad = new Set([
      "password", "hidden", "submit", "button", "reset", "image",
      "file", "checkbox", "radio", "range", "color",
    ]);
    return !bad.has(el.type) && !el.disabled && !el.readOnly;
  }
  return false;
}

function containsAny(hay: string, needles: string[]): boolean {
  return needles.some((n) => n !== "" && hay.includes(n));
}

function matchesBusinessName(hay: string): boolean {
  if (containsAny(hay, PERSON_TOKENS)) return false;
  if (containsAny(hay, BUSINESS_TOKENS)) return true;
  // A bare "name" is the business field on many directory forms — accept it only when
  // nothing marks it as a person's or a different entity's name.
  const otherEntity = ["website", "page", "site", "file", "user", "login", "card", "account", "domain"];
  return hay.includes("name") && !containsAny(hay, otherEntity);
}

export async function fillFormHeuristic(values: HeuristicValue[]): Promise<FillOutcome> {
  const out: FillOutcome = { filled: [], failed: [] };
  const byKey = new Map(values.map((v) => [v.key, v] as const));

  const candidates = Array.from(document.querySelectorAll<HTMLElement>("input, textarea, select")).filter(
    (el) => isFillableField(el) && isVisibleField(el) && !containsAny(fieldHaystack(el), NEVER_TOKENS),
  );

  const used = new Set<Element>();
  const chosen: { key: string; el: Element; value: string }[] = [];

  for (const key of KEY_PRIORITY) {
    const v = byKey.get(key);
    if (!v || !v.value.trim()) continue;

    // 1) an exact `autocomplete` attribute is the strongest, least-ambiguous signal.
    const acTokens = AUTOCOMPLETE_TOKENS[key] ?? [];
    let pick: Element | undefined = acTokens.length
      ? candidates.find((el) => !used.has(el) && acTokens.includes((el.getAttribute("autocomplete") ?? "").toLowerCase().trim()))
      : undefined;

    // 2) otherwise, a keyword in the field's own attributes / label, in DOM order.
    if (!pick) {
      pick = candidates.find((el) => {
        if (used.has(el)) return false;
        const hay = fieldHaystack(el);
        return key === "business_name" ? matchesBusinessName(hay) : containsAny(hay, SYNONYMS[key] ?? []);
      });
    }

    if (pick) {
      used.add(pick);
      chosen.push({ key, el: pick, value: v.value });
    } else {
      out.failed.push({ key, reason: "no_field_matched" });
    }
  }

  for (const c of chosen) {
    try {
      setOne(c.el, c.value);
      out.filled.push(c.key);
    } catch {
      out.failed.push({ key: c.key, reason: "set_threw" });
    }
  }

  await nextFrame();
  const reverted: string[] = [];
  for (const c of chosen) {
    if (!out.filled.includes(c.key)) continue;
    // For a <select>, a fuzzy pick (FL->Florida, a category token) will not be a
    // byte-exact match — so "filled" means a real, non-placeholder option is now
    // selected. Text/textarea fields still require the exact value to have stuck.
    const ok =
      c.el instanceof HTMLSelectElement
        ? c.el.selectedIndex > 0 && (c.el.value ?? "") !== ""
        : matches(c.el, c.value);
    if (!ok) {
      reverted.push(c.key);
      out.failed.push({ key: c.key, reason: "reverted_by_page" });
    }
  }
  out.filled = out.filled.filter((k) => !reverted.includes(k));
  return out;
}

