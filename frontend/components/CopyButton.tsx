"use client";

import { useState } from "react";

// A tiny copy-to-clipboard icon button. Reuses the small icon-button chrome
// (`pass-eye` by default) so it drops into credential rows without new styling.
// Flashes a check on success; a blocked clipboard is a silent no-op.
export default function CopyButton({
  value,
  label,
  className = "pass-eye",
}: {
  value: string;
  label: string;
  className?: string;
}) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 1400);
    } catch {
      /* clipboard blocked — no-op */
    }
  }

  return (
    <button
      type="button"
      className={`${className}${copied ? " ok" : ""}`}
      onClick={copy}
      title={`Copy ${label}`}
      aria-label={`Copy ${label}`}
    >
      <span className="material-symbols-rounded">{copied ? "check" : "content_copy"}</span>
    </button>
  );
}
