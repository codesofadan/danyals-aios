// The avatar accent a newly provisioned member is stamped with.
//
// WHY THIS IS A TEST AND NOT A COMMENT. `AddMemberWizard` sends `avatar_color` to
// `POST /admin/users`, which defaults it to `#7B69EE` and writes it to `public.users`.
// So a MISSING colour is not a crash and not a visual glitch — it is a wrong row in
// the database, written silently, for every member created from that point on. The
// kind of defect found months later as "why is everyone purple".
//
// The template catalogue (keys, labels, grants) is moving to `GET /rbac/templates`,
// whose response deliberately carries no `color` — colour is a theme token with no
// server-side reader, and it was the field that had actually drifted. `TEMPLATE_COLOR`
// is the frontend's half of that split, and this pins it so the split cannot quietly
// lose a colour on the way.

import { describe, expect, it } from "vitest";

import { SERIES, TEMPLATE_COLOR } from "./data";

// The default `provisioning.py` writes when the wizard sends nothing. If a template
// ever resolves to this, the split has silently failed.
const PROVISIONING_DEFAULT = "#7B69EE";

describe("TEMPLATE_COLOR", () => {
  // WHERE THE COVERAGE GUARD WENT, and why it is not here.
  //
  // This file used to assert "every role template has a colour" by looping over
  // `roleTemplates` — the frontend's own copy of the catalogue. That copy is now
  // deleted: templates come from `GET /rbac/templates`, owned by `matrix.py`.
  //
  // So the guard cannot live on this side any more, and the tempting rewrite is a
  // TRAP: looping over `Object.keys(TEMPLATE_COLOR)` asserts "every key I have, I
  // have" — vacuously green, and blind to the exact slip it existed to catch (a
  // template added with no colour, which now originates in the BACKEND and which this
  // side cannot see at all).
  //
  // A guard needs a template-key source independent of `TEMPLATE_COLOR`, and only the
  // backend has one. It belongs in the suite that already reads this file and compares
  // it to `matrix.py` by value. Stated here rather than faked here, because a
  // frontend-side version could only ever be theatre.

  it("never resolves to the provisioning fallback", () => {
    for (const [key, color] of Object.entries(TEMPLATE_COLOR)) {
      expect(color, `template "${key}" is the legacy violet default`).not.toBe(
        PROVISIONING_DEFAULT,
      );
    }
  });

  it("uses the dashboard's own palette rather than loose hex", () => {
    // Keeps colour a THEME decision. A hand-typed hex here is how the backend's copy
    // drifted nine times before it was deleted.
    const palette = new Set<string>(Object.values(SERIES));
    for (const [key, color] of Object.entries(TEMPLATE_COLOR)) {
      expect(palette.has(color), `template "${key}" uses ${color}, which is not in SERIES`).toBe(
        true,
      );
    }
  });

  it("preserves the accents the dashboard renders today", () => {
    // Pinned by value so the migration off `roleTemplates[].color` is provably a
    // no-op visually, not a redesign smuggled in behind a refactor.
    expect(TEMPLATE_COLOR).toEqual({
      seo: SERIES.c4,
      content: SERIES.c3,
      va: SERIES.c1,
      super: SERIES.c1,
    });
  });
});
