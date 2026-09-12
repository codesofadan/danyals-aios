/**
 * Describe a directory's form STRUCTURALLY, so the server can work out what each
 * field wants without ever seeing the page.
 *
 * WHAT LEAVES THE BROWSER, AND WHAT DOES NOT. This produces field structure only:
 * kind, name, id, label, placeholder, aria-label, the visible text beside the field,
 * `<select>` option labels, required, and which step of a multi-step form it sits on.
 * It never reads a field's VALUE, never serialises the page, and never touches a
 * password, a file input or anything named like a credential. The server sanitises
 * again on arrival — two independent whitelists, because this is the boundary where a
 * convenience could quietly become an exfiltration path through a directory nobody
 * audited.
 *
 * WHY A LABEL IS FOUND FIVE WAYS. On a real directory form the single most useful
 * clue is often the only one present: `<label for>` on one site, an ancestor `<label>`
 * on another, `aria-labelledby` on a third, and on the worst ones nothing at all but a
 * `<div>` sitting immediately above the input. A collector that reads only `label[for]`
 * hands the server a form of anonymous `f_1..f_9` fields and gets an honest shrug back.
 *
 * SELECTORS ARE BUILT TO SURVIVE A RELOAD. `#id` when the id looks authored, then
 * `[name=...]`, then a structural `nth-of-type` path. A selector built from generated
 * class names (`.css-1a2b3c`) would work once and miss on the next page load, which is
 * also why the server fingerprints the form on field STRUCTURE and not on selectors.
 */

export type CollectedField = {
  selector: string;
  kind: string;
  name: string;
  id: string;
  label: string;
  placeholder: string;
  aria: string;
  near: string;
  options: string[];
  required: boolean;
  step: number;
};

/** Never describe these, whatever the page calls them. Mirrors the server's list. */
const NEVER = /(?:^|[\W_])(?:passw(?:or)?d|pwd|cc[-_]?num|card[-_]?num|cvv|cvc|ssn|csrf|xsrf|authenticity[-_]?token|api[-_]?key|secret)/i;

/** Input types that are never business-listing data. */
const SKIP_TYPES = new Set([
  "password", "hidden", "file", "submit", "button", "reset", "image",
]);

const MAX_FIELDS = 60;
const MAX_TEXT = 160;
const MAX_OPTIONS = 25;

function trim(value: string | null | undefined): string {
  return (value ?? "").replace(/\s+/g, " ").trim().slice(0, MAX_TEXT);
}

/** Does this id look authored, or generated? A generated id is useless in a selector
 * and worse than useless in a fingerprint, because it changes every reload. */
function stableId(id: string): boolean {
  if (!id || id.length > 60) return false;
  if (/^[0-9]/.test(id)) return false;               // not a valid bare CSS id
  if (/^(?:radix|headless|mui|rc|react|:r)/i.test(id)) return false;  // widget libs
  if (/\d{4,}/.test(id)) return false;               // react-generated counters
  return /^[A-Za-z][\w-]*$/.test(id);
}

function cssEscape(value: string): string {
  const api = (globalThis as { CSS?: { escape?: (v: string) => string } }).CSS;
  if (api?.escape) return api.escape(value);
  return value.replace(/[^\w-]/g, (c) => `\\${c}`);
}

/**
 * A selector that finds this element again after a reload.
 *
 * Ordered by durability, not by brevity: an authored id is stable, a `name` is stable
 * (forms are posted by name, so authors do not churn them), and a structural path is
 * stable as long as the markup is. Class names are deliberately never used.
 */
function selectorFor(el: Element): string {
  const id = el.getAttribute("id") ?? "";
  if (stableId(id)) return `#${cssEscape(id)}`;

  const name = el.getAttribute("name") ?? "";
  if (name) {
    const tag = el.tagName.toLowerCase();
    const scoped = `${tag}[name="${cssEscape(name)}"]`;
    // Only if it is UNIQUE - a radio group shares one name, and filling "the" radio
    // would pick whichever came first.
    try {
      if (document.querySelectorAll(scoped).length === 1) return scoped;
    } catch {
      /* fall through to the structural path */
    }
  }

  const parts: string[] = [];
  let node: Element | null = el;
  while (node && node !== document.body && parts.length < 6) {
    const parent: Element | null = node.parentElement;
    if (!parent) break;
    const tag = node.tagName.toLowerCase();
    const sameTag = Array.from(parent.children).filter((c) => c.tagName === node!.tagName);
    const index = sameTag.indexOf(node) + 1;
    parts.unshift(sameTag.length > 1 ? `${tag}:nth-of-type(${index})` : tag);
    node = parent;
  }
  return parts.length ? `body ${parts.join(" > ")}` : "";
}

/** Every way a real form labels a field, in decreasing reliability. */
function labelFor(el: Element): string {
  const id = el.getAttribute("id");
  if (id) {
    try {
      const bound = document.querySelector(`label[for="${cssEscape(id)}"]`);
      if (bound?.textContent) return trim(bound.textContent);
    } catch {
      /* an unusable id is not an error here */
    }
  }
  const labelledBy = el.getAttribute("aria-labelledby");
  if (labelledBy) {
    const texts = labelledBy
      .split(/\s+/)
      .map((ref) => document.getElementById(ref)?.textContent ?? "")
      .filter(Boolean);
    if (texts.length) return trim(texts.join(" "));
  }
  const ancestor = el.closest("label");
  if (ancestor?.textContent) return trim(ancestor.textContent);
  return "";
}

/**
 * Visible text immediately before the field, when nothing else labels it.
 *
 * This is the clue that rescues the worst forms - the ones whose inputs are named
 * `f_1..f_9` with no label at all, where a `<div>Listing title</div>` above the box is
 * the only thing a human reads either. Bounded to one short hop so a whole paragraph
 * of terms text never travels.
 */
function nearTextFor(el: Element): string {
  let sibling = el.previousElementSibling;
  let hops = 0;
  while (sibling && hops < 3) {
    if (!/^(script|style|svg|noscript)$/i.test(sibling.tagName)) {
      const text = trim(sibling.textContent);
      if (text && text.length <= 80) return text;
    }
    sibling = sibling.previousElementSibling;
    hops += 1;
  }
  const parent = el.parentElement;
  if (parent) {
    // The parent's own text, excluding every child's - the "floating label" pattern.
    const own = Array.from(parent.childNodes)
      .filter((n) => n.nodeType === Node.TEXT_NODE)
      .map((n) => trim(n.textContent))
      .filter(Boolean)
      .join(" ");
    if (own && own.length <= 80) return own;
  }
  return "";
}

/** Which step of a multi-step form, when the page exposes one. 0 = not stepped. */
function stepFor(el: Element): number {
  const holder = el.closest("[data-step],[data-page],fieldset[data-index]");
  if (!holder) return 0;
  const raw = holder.getAttribute("data-step")
    ?? holder.getAttribute("data-page")
    ?? holder.getAttribute("data-index")
    ?? "";
  const n = Number.parseInt(raw, 10);
  return Number.isFinite(n) && n > 0 ? n : 0;
}

function isVisible(el: HTMLElement): boolean {
  // Same rule the filler uses, including the position:fixed carve-out - a field the
  // filler cannot see is one the server should not be asked to map.
  if (el.offsetParent !== null) return true;
  const style = getComputedStyle(el);
  return style.position === "fixed" && style.display !== "none"
    && style.visibility !== "hidden";
}

function kindOf(el: Element): string {
  if (el instanceof HTMLTextAreaElement) return "textarea";
  if (el instanceof HTMLSelectElement) return "select";
  if (el instanceof HTMLInputElement) return (el.type || "text").toLowerCase();
  return "";
}

/**
 * Collect the open page's form fields as a PII-free digest.
 *
 * Runs on the operator's explicit click, never on navigation - the same rule as the
 * filler, which is what keeps the permission at `activeTab`.
 */
export function collectFormFields(): CollectedField[] {
  const out: CollectedField[] = [];
  const candidates = Array.from(
    document.querySelectorAll<HTMLElement>("input, textarea, select"),
  );

  for (const el of candidates) {
    if (out.length >= MAX_FIELDS) break;

    const kind = kindOf(el);
    if (!kind || SKIP_TYPES.has(kind)) continue;
    if (el instanceof HTMLInputElement && (el.disabled || el.readOnly)) continue;
    if (el instanceof HTMLTextAreaElement && (el.disabled || el.readOnly)) continue;
    if (el instanceof HTMLSelectElement && el.disabled) continue;
    if (!isVisible(el)) continue;

    const name = el.getAttribute("name") ?? "";
    const id = el.getAttribute("id") ?? "";
    const label = labelFor(el);
    const aria = trim(el.getAttribute("aria-label"));
    const autocomplete = el.getAttribute("autocomplete") ?? "";
    // EVERY identifying string, because a field called one thing and labelled another
    // must still be refused. `aria-label` and `autocomplete` are in here deliberately:
    // an accessible form often puts "Password" in aria-label alone, and
    // `autocomplete="cc-number"` is the browser's own declaration that a box holds a
    // card number. Missing either sends a credential-shaped field to a third party.
    if (NEVER.test(`${name} ${id} ${label} ${aria} ${autocomplete}`)) continue;

    const selector = selectorFor(el);
    if (!selector) continue;

    const options = el instanceof HTMLSelectElement
      ? Array.from(el.options).slice(0, MAX_OPTIONS).map((o) => trim(o.textContent || o.value))
        .filter(Boolean)
      : [];

    out.push({
      selector,
      kind,
      name: trim(name),
      id: trim(id),
      label,
      placeholder: trim(el.getAttribute("placeholder")),
      aria,
      near: label ? "" : nearTextFor(el),
      options,
      required: el.hasAttribute("required")
        || el.getAttribute("aria-required") === "true",
      step: stepFor(el),
    });
  }

  return out;
}
