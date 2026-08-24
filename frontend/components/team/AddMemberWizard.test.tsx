// The add-member wizard, now that its role catalogue is server-owned.
//
// `roleTemplates` used to be a hand-mirrored constant in `lib/data.ts`. It is now
// `GET /rbac/templates`, so what was a synchronous array is an async fetch — and that
// change introduces two failure modes that did not exist before, both silent:
//
//   1. The operator acts BEFORE the catalogue arrives. The submit path falls back to
//      `features: []`, provisioning a member with no feature grants at all. Nothing
//      errors. It surfaces weeks later as "why can't they see anything".
//   2. The fetch FAILS and the dropdown is simply empty — which reads as "this agency
//      has no role templates" rather than "the request failed".
//
// Both are the same species as the `avatar_color` defect that prompted this work: a
// missing value quietly becoming a wrong record, rather than an error anybody sees.

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AddMemberWizard from "./AddMemberWizard";
import type { RbacTemplate } from "@/lib/hooks/team";

const TEMPLATES: RbacTemplate[] = [
  {
    key: "seo",
    label: "SEO Specialist",
    tagline: "Analytics & optimization",
    icon: "query_stats",
    role: "Specialist",
    grants: ["technical_audit", "reporting"],
  },
  {
    key: "super",
    label: "Super Admin",
    tagline: "Full access",
    icon: "shield_person",
    role: "Owner",
    grants: ["technical_audit", "reporting", "key_vault"],
  },
];

const query = { data: undefined as RbacTemplate[] | undefined, isPending: true, isError: false };
vi.mock("@/lib/hooks/team", () => ({ useRbacTemplates: () => query }));

function loaded() {
  query.data = TEMPLATES;
  query.isPending = false;
  query.isError = false;
}

beforeEach(() => {
  query.data = undefined;
  query.isPending = true;
  query.isError = false;
});

describe("AddMemberWizard — the server-owned role catalogue", () => {
  it("lists the templates the server sent", async () => {
    loaded();
    render(<AddMemberWizard onClose={() => {}} onAdd={() => {}} />);

    await waitFor(() => {
      expect(screen.getByRole("option", { name: /SEO Specialist/ })).toBeInTheDocument();
    });
    expect(screen.getByRole("option", { name: /Super Admin/ })).toBeInTheDocument();
  });

  // Filling both fields is what makes the next two tests MEAN anything. Without it
  // the button is disabled by the empty name/email and the assertion passes whether
  // or not the template guard exists — a vacuous test that would never go red. This
  // was caught by deleting the guard and watching the suite stay green.
  async function fillIdentity() {
    await userEvent.type(screen.getByPlaceholderText("e.g. Ali Hassan"), "Ali Hassan");
    await userEvent.type(screen.getByPlaceholderText("ali@qanry.com"), "ali@qanry.com");
  }

  it("cannot proceed while the catalogue is still loading, even with the form filled", async () => {
    // The guard that stops a member being provisioned with `features: []`.
    render(<AddMemberWizard onClose={() => {}} onAdd={() => {}} />);
    await fillIdentity();

    expect(screen.getByRole("option", { name: /loading/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /next/i })).toBeDisabled();
  });

  it("proceeds once the catalogue has arrived and the form is filled", async () => {
    // The other half of the guard: it must not be permanently disabling.
    loaded();
    render(<AddMemberWizard onClose={() => {}} onAdd={() => {}} />);
    await fillIdentity();

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /next/i })).toBeEnabled();
    });
  });

  it("says the catalogue FAILED rather than showing an empty dropdown", async () => {
    // An empty <select> reads as "no roles exist". It is a fetch failure, and the
    // operator is the only one who can act on the difference.
    query.isPending = false;
    query.isError = true;
    render(<AddMemberWizard onClose={() => {}} onAdd={() => {}} />);
    await fillIdentity();

    expect(screen.getByRole("option", { name: /couldn't load roles/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /next/i })).toBeDisabled();
  });

  it("selects the first template once the catalogue arrives", async () => {
    loaded();
    render(<AddMemberWizard onClose={() => {}} onAdd={() => {}} />);

    await waitFor(() => {
      expect(screen.getByLabelText("Role template")).toHaveValue("seo");
    });
  });
});
