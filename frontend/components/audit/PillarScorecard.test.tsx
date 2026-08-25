// The pillar cards are where a client first reads a number, so this is where a
// confident wrong number does the most damage.
//
// Two real defects are pinned here, both measured on run 837b75d6:
//   * technical scored 97.2 having run 25 of 100 technical checks;
//   * strategy ran 0 of 21 and had been silently dropped from the composite.
//
// The rendering rules that follow are therefore not cosmetic. A card must never
// show a score without its denominator, and must never show "0" for a dimension
// nobody measured.

import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import PillarScorecard from "./PillarScorecard";
import type { Rollup } from "@/lib/auditAltitude";

const base: Rollup = {
  level: "dimension",
  key: "technical",
  label: "Technical",
  score: 97.2,
  checks_applicable: 100,
  checks_planned: 25,
  checks_ran: 25,
  checks_skipped: 75,
  skip_reasons: {},
  findings_open: 4,
  instances_open: 4,
  pages_affected: 1,
  pages_crawled: 197,
  severity_counts: {},
  url_health_pct: null,
  basis_hash: "b",
  scoring_model_version: "v",
};

const strategy: Rollup = {
  ...base,
  key: "strategy",
  label: "Strategy",
  score: null,
  checks_applicable: 21,
  checks_planned: 0,
  checks_ran: 0,
  checks_skipped: 21,
  skip_reasons: { analyzer_path_unresolved: 21 },
  findings_open: 0,
  instances_open: 0,
};

describe("PillarScorecard", () => {
  it("never shows a score without the checks behind it", () => {
    render(<PillarScorecard rollups={[base]} selected={null} onSelect={() => {}} />);
    expect(screen.getByText("97.2")).toBeInTheDocument();
    // The denominator is on the card, not in a tooltip somebody has to find.
    expect(screen.getByText(/ran 25 of 100 checks/i)).toBeInTheDocument();
  });

  it("renders an unmeasured dimension as words, never as 0", () => {
    render(<PillarScorecard rollups={[strategy]} selected={null} onSelect={() => {}} />);
    expect(screen.getByText(/not measured/i)).toBeInTheDocument();
    expect(screen.queryByText("0")).not.toBeInTheDocument();
  });

  it("says WHY it was not measured, because the remedy depends on it", () => {
    render(<PillarScorecard rollups={[strategy]} selected={null} onSelect={() => {}} />);
    expect(screen.getByText(/no working analyzer/i)).toBeInTheDocument();
  });

  it("styles an unmeasured pillar as absent, not as failing", () => {
    // A red card says "this is broken". A muted, dashed card says "we did not
    // look". Those are different messages and must not be confused.
    const { container } = render(
      <PillarScorecard rollups={[strategy]} selected={null} onSelect={() => {}} />,
    );
    const card = container.querySelector(".alt-pillar");
    expect(card?.className).toContain("t-none");
    expect(card?.className).not.toContain("t-crit");
  });

  it("lets an operator filter to a dimension, and toggle it back off", () => {
    const onSelect = vi.fn();
    render(<PillarScorecard rollups={[base]} selected={null} onSelect={onSelect} />);
    screen.getByRole("button").click();
    expect(onSelect).toHaveBeenCalledWith("technical");
  });

  it("deselects when the already-selected card is clicked again", () => {
    const onSelect = vi.fn();
    render(<PillarScorecard rollups={[base]} selected="technical" onSelect={onSelect} />);
    screen.getByRole("button").click();
    expect(onSelect).toHaveBeenCalledWith(null);
  });

  it("renders nothing rather than an empty shell when there are no dimensions", () => {
    const { container } = render(
      <PillarScorecard rollups={[]} selected={null} onSelect={() => {}} />,
    );
    expect(container.firstChild).toBeNull();
  });
});
