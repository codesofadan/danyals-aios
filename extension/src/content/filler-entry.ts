/**
 * The content-script entry point: a thin bridge between the service worker and the page.
 *
 * SEPARATE FROM `filler.ts` on purpose. That module is pure DOM logic and is unit-tested
 * against jsdom, which has no `chrome` global — so attaching a listener at import time
 * there would make the logic untestable without stubbing the whole extension API. Here
 * the bridge is the only thing that touches `chrome`, and it holds no logic of its own.
 *
 * This script never sees the operator token or the API base. It receives a list of
 * selectors and values and returns an outcome, which is what keeps the credential out of
 * a renderer shared with the directory's own JavaScript.
 */

import { collectFormFields, type CollectedField } from "./collector";
import { fillForm, fillFormHeuristic, type FieldPlanItem, type FillOutcome, type HeuristicValue } from "./filler";

declare global {
  interface Window {
    __aiosFillerLoaded?: boolean;
  }
}

// Re-injection is idempotent for the FUNCTIONS but not for the LISTENERS: injecting a
// second time would register a second handler, and the panel would get two replies to
// one request. The sentinel makes the second injection a no-op.
if (!window.__aiosFillerLoaded) {
  window.__aiosFillerLoaded = true;
  chrome.runtime.onMessage.addListener(
    (
      msg: { type?: string; plan?: FieldPlanItem[]; values?: HeuristicValue[] },
      _sender: unknown,
      respond: (value: FillOutcome | CollectedField[]) => void,
    ) => {
      // Describe the form so the SERVER can work out what each field wants. Structure
      // only - no values, no page HTML (see collector.ts). Synchronous: the DOM is
      // already there, so there is nothing to await and no channel to keep open.
      if (msg?.type === "aios-collect") {
        respond(collectFormFields());
        return;
      }
      // Spec-driven fill (exact selectors from an earned spec).
      if (msg?.type === "aios-fill") {
        void fillForm(msg.plan ?? []).then(respond);
        return true; // keep the channel open for the async reply
      }
      // Best-effort autofill (no spec): match business values to this page's fields.
      if (msg?.type === "aios-autofill") {
        void fillFormHeuristic(msg.values ?? []).then(respond);
        return true;
      }
      return;
    },
  );
}
