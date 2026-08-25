// The presentation rules that keep an audit honest on screen.
//
// WHY THESE ARE TESTS AND NOT COMMENTS. Every one of them is a rule that, if
// broken, produces a CONFIDENT WRONG NUMBER in front of a client - which is
// worse than no number at all. They are not stylistic preferences:
//
//   * The engine really did score technical 97.2 having run 25 of 100 technical
//     checks. Rendering a score without its denominator is how that reads as a
//     clean bill of health.
//   * `strategy` really did run 0 of 21 checks. `score ?? 0` would print "0" and
//     tell a client their strategy is worthless when nobody looked at it.
//
// Both are recorded against real run 837b75d6 in docs/audit/fixtures/README.md.

import { describe, expect, it } from "vitest";

import {
  NOT_MEASURED,
  blastRadius,
  coverageLabel,
  coveragePct,
  fixScope,
  isMeasured,
  isTruncated,
  notMeasuredReason,
  scoreDisplay,
  ownerLabel,
  scoreTone,
  severityTone,
} from "./auditAltitude";

const rollup = (over: Partial<Parameters<typeof scoreDisplay>[0]> = {}) => ({
  score: 88.7,
  checks_ran: 25,
  ...over,
});

describe("scoreDisplay — null is not zero", () => {
  it("renders a measured score as its number", () => {
    expect(scoreDisplay(rollup())).toBe("88.7");
  });

  it("renders an unmeasured dimension as words, never 0", () => {
    // The strategy dimension on a real run: 0 of 21 checks.
    expect(scoreDisplay({ score: null, checks_ran: 0 })).toBe(NOT_MEASURED);
  });

  it("renders a MEASURED zero as zero — the opposite claim", () => {
    expect(scoreDisplay({ score: 0, checks_ran: 12 })).toBe("0");
  });

  it("refuses a score that arrived with no checks behind it", () => {
    // Defence in depth: if the API ever sends a number with checks_ran 0, the
    // number is not trustworthy and must not be shown as one.
    expect(scoreDisplay({ score: 91, checks_ran: 0 })).toBe(NOT_MEASURED);
  });
});

describe("isMeasured", () => {
  it("is false for null and for a zero denominator", () => {
    expect(isMeasured({ score: null, checks_ran: 5 })).toBe(false);
    expect(isMeasured({ score: 70, checks_ran: 0 })).toBe(false);
  });
  it("is true only when both hold", () => {
    expect(isMeasured({ score: 0, checks_ran: 1 })).toBe(true);
  });
});

describe("coverage — the denominator always travels with the number", () => {
  it("states both halves", () => {
    expect(coverageLabel({ checks_ran: 25, checks_applicable: 100 })).toBe("25 of 100");
  });
  it("computes a percentage for the bar", () => {
    expect(coveragePct({ checks_ran: 25, checks_applicable: 100 })).toBe(25);
  });
  it("does not divide by zero", () => {
    expect(coveragePct({ checks_ran: 0, checks_applicable: 0 })).toBe(0);
  });
});

describe("notMeasuredReason — the remedies differ, so the reasons must", () => {
  it("names a tier restriction, which the operator can change", () => {
    expect(notMeasuredReason({ skip_reasons: { source_not_permitted: 71 } })).toMatch(/tier/);
  });
  it("names a missing analyzer, which is engineering work, not an operator action", () => {
    expect(notMeasuredReason({ skip_reasons: { analyzer_path_unresolved: 94 } })).toMatch(
      /analyzer/,
    );
  });
  it("distinguishes 'ran and found nothing' from 'never ran'", () => {
    expect(notMeasuredReason({ skip_reasons: { no_finding_emitted: 1 } })).toMatch(/ran/);
  });
  it("falls back rather than inventing a cause", () => {
    expect(notMeasuredReason({ skip_reasons: {} })).toBe("not run");
  });
});

describe("scoreTone — an unmeasured dimension is ABSENT, not FAILING", () => {
  it("never returns a failure tone for null", () => {
    // This is what stops the UI painting "we did not look" in red.
    expect(scoreTone(null)).toBe("none");
    expect(scoreTone(null)).not.toBe("crit");
  });
  it("bands match the existing workspace", () => {
    expect(scoreTone(80)).toBe("ok");
    expect(scoreTone(79)).toBe("warn");
    expect(scoreTone(65)).toBe("warn");
    expect(scoreTone(64)).toBe("crit");
  });
});

describe("severityTone", () => {
  it("maps the four engine severities", () => {
    expect(severityTone("critical")).toBe("crit");
    expect(severityTone("major")).toBe("warn");
    expect(severityTone("minor")).toBe("ok");
    expect(severityTone("info")).toBe("none");
  });
  it("does not crash on an unknown severity", () => {
    expect(severityTone("whatever")).toBe("none");
  });
});

describe("blastRadius — the sentence that replaces 8,077 rows", () => {
  it("states the page count for a template finding", () => {
    expect(blastRadius({ instance_count: 121, locus_kind: "template" })).toBe("121 pages");
  });
  it("says site-wide rather than a misleading count", () => {
    // A robots.txt problem has one instance but affects everything.
    expect(blastRadius({ instance_count: 1, locus_kind: "site" })).toBe("site-wide");
  });
  it("keeps the singular readable", () => {
    expect(blastRadius({ instance_count: 1, locus_kind: "url" })).toBe("1 page");
  });
  it("groups thousands for a large site", () => {
    expect(blastRadius({ instance_count: 8077, locus_kind: "template" })).toBe("8,077 pages");
  });
});

describe("fixScope — a cause is a cause because the fix is in one place", () => {
  it("names the template, which is the whole argument for grouping", () => {
    expect(fixScope({ locus_kind: "template", locus_value: "/services/{slug}" })).toBe(
      "One template: /services/{slug}",
    );
  });
  it("distinguishes a one-page problem", () => {
    expect(fixScope({ locus_kind: "url", locus_value: "https://x/1" })).toBe("This page only");
  });
});

describe("isTruncated — a cap may never masquerade as a smaller problem", () => {
  it("is true when fewer instances were stored than observed", () => {
    expect(isTruncated({ instance_count: 50000, instances_stored: 20000 })).toBe(true);
  });
  it("is false in the normal case", () => {
    expect(isTruncated({ instance_count: 121, instances_stored: 121 })).toBe(false);
  });
});

describe("ownerLabel — a job title, never an internal agent code", () => {
  it("names the role that owns the work", () => {
    // 'A3' is an engine identity. On screen it reads as a serial number where a
    // person's job belongs.
    expect(ownerLabel({ dimension: "onpage", owner_agent: "A3" })).toBe("SEO Specialist");
    expect(ownerLabel({ dimension: "technical", owner_agent: "B1" })).toBe("Developer");
    expect(ownerLabel({ dimension: "geo", owner_agent: "A5" })).toBe("Blog Writer");
    expect(ownerLabel({ dimension: "local", owner_agent: "D1" })).toBe("Local Specialist");
  });

  it("falls back to the agent code rather than rendering blank", () => {
    expect(ownerLabel({ dimension: "unknown", owner_agent: "Z9" })).toBe("Z9");
  });
});
