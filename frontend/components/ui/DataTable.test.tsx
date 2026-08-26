// Each case here is a defect the 20 hand-copied table bodies actually produced.

import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import DataTable, { type Column } from "./DataTable";

type Row = { id: string; client: string; spam: number };

const ROWS: Row[] = [
  { id: "a", client: "NorthPeak Dental", spam: 4 },
  { id: "b", client: "Alligator Pools", spam: 31 },
];

const COLUMNS: Column<Row>[] = [
  { key: "client", header: "Client", cell: (r) => r.client },
  { key: "spam", header: "Spam", cell: (r) => r.spam, numeric: true },
];

function table(props: Partial<React.ComponentProps<typeof DataTable<Row>>> = {}) {
  return render(
    <DataTable
      columns={COLUMNS}
      rows={ROWS}
      rowKey={(r) => r.id}
      label="backlinks"
      {...props}
    />,
  );
}

describe("DataTable", () => {
  it("renders a row per record", () => {
    table();
    expect(screen.getByText("NorthPeak Dental")).toBeInTheDocument();
    expect(screen.getByText("Alligator Pools")).toBeInTheDocument();
  });

  it("scrolls sideways instead of forcing the page to — no @media rule in this app touches a table", () => {
    const { container } = table();
    expect(container.querySelector(".tbl-wrap")).not.toBeNull();
  });

  it("right-aligns numeric columns through the existing .num convention", () => {
    table();
    expect(screen.getByRole("columnheader", { name: "Spam" })).toHaveClass("num");
  });

  describe("the three branches", () => {
    it("says it is loading, and asserts no rows while it does", () => {
      table({ query: { isLoading: true } });
      expect(screen.getByRole("status")).toHaveTextContent(/loading backlinks/i);
      expect(screen.queryByText("NorthPeak Dental")).toBeNull();
    });

    it("says a FAILED read is unavailable, not empty", () => {
      table({ rows: [], query: { isError: true }, empty: "No links match this filter." });
      expect(screen.getByRole("alert")).toHaveTextContent(/unavailable, not absent/i);
      // The exact lie this replaces: an empty table for a failed request.
      expect(screen.queryByText("No links match this filter.")).toBeNull();
    });

    it("prefers the failure message when a stale-data refetch fails", () => {
      table({ query: { isLoading: true, isError: true } });
      expect(screen.getByRole("alert")).toBeInTheDocument();
      expect(screen.queryByRole("status")).toBeNull();
    });

    it("shows the caller's empty copy when the read genuinely returned nothing", () => {
      table({ rows: [], empty: "No links match this filter." });
      expect(screen.getByRole("status")).toHaveTextContent("No links match this filter.");
    });

    it("falls back to an honest default empty message", () => {
      table({ rows: [] });
      expect(screen.getByRole("status")).toHaveTextContent("No backlinks yet.");
    });
  });

  it("spans the placeholder across every column, derived not hand-written", () => {
    // The hand-written colSpan drifted from the column count whenever a column
    // was added, leaving the message boxed into the first cell.
    table({ rows: [] });
    const cell = screen.getByRole("status").closest("td")!;
    expect(cell).toHaveAttribute("colspan", String(COLUMNS.length));
  });

  describe("clickable rows", () => {
    it("activates on click", async () => {
      const onRowClick = vi.fn();
      table({ onRowClick });
      await userEvent.click(screen.getByText("Alligator Pools"));
      expect(onRowClick).toHaveBeenCalledWith(ROWS[1]);
    });

    it("activates from the keyboard — a <tr onClick> alone is mouse-only", async () => {
      const onRowClick = vi.fn();
      table({ onRowClick });
      await userEvent.tab();
      await userEvent.keyboard("{Enter}");
      expect(onRowClick).toHaveBeenCalledWith(ROWS[0]);
    });

    it("activates on Space too", async () => {
      const onRowClick = vi.fn();
      table({ onRowClick });
      await userEvent.tab();
      await userEvent.keyboard(" ");
      expect(onRowClick).toHaveBeenCalledWith(ROWS[0]);
    });

    it("leaves rows unfocusable when they do nothing", () => {
      table();
      const body = screen.getAllByRole("row")[1];
      expect(body).not.toHaveAttribute("tabindex");
    });
  });

  it("labels the table for assistive tech when given a caption", () => {
    table({ caption: "Referring domains" });
    expect(within(screen.getByRole("table")).getByText("Referring domains")).toBeInTheDocument();
  });
});
