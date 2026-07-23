// Copy text to the clipboard with a fallback for INSECURE contexts. The Clipboard
// API (navigator.clipboard) only works in a secure context - HTTPS or localhost - so
// on the production HTTP host (http://<ip>:3000) it is unavailable and a plain
// navigator.clipboard.writeText throws. This falls back to the legacy
// execCommand("copy") over a hidden textarea, which works over plain HTTP.
export async function copyText(value: string): Promise<boolean> {
  try {
    if (typeof navigator !== "undefined" && navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(value);
      return true;
    }
  } catch {
    // fall through to the legacy path
  }
  try {
    const ta = document.createElement("textarea");
    ta.value = value;
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.top = "-1000px";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(ta);
    return ok;
  } catch {
    return false;
  }
}
