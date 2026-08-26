// The wiring is the whole point of this component, so it is pinned.
//
// Before it existed, ~141 of the product's 155 form controls were announced as
// unlabelled: 164 `<label>` elements carried only 14 `htmlFor` between them, and
// the labels sat as SIBLINGS inside `.fld` rather than wrapping the input, so
// there was no implicit association either. Required-ness was marked on two
// controls in the whole product, and field-level errors did not exist.

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import Field, { SelectField, TextField } from "./Field";

describe("TextField", () => {
  it("associates the label with the control", () => {
    render(<TextField label="Site URL" />);
    // getByLabelText only resolves through a REAL association.
    expect(screen.getByLabelText("Site URL")).toBeInstanceOf(HTMLInputElement);
  });

  it("announces required-ness in words, not just an asterisk", () => {
    render(<TextField label="Client name" required />);
    const input = screen.getByLabelText(/client name/i);
    expect(input).toBeRequired();
    expect(screen.getByLabelText(/\(required\)/i)).toBe(input);
  });

  it("is not required unless asked", () => {
    render(<TextField label="Notes" />);
    expect(screen.getByLabelText("Notes")).not.toBeRequired();
  });

  it("ties an error to its own field and announces it", () => {
    render(<TextField label="Site URL" error="Enter a full URL, including https://" />);
    const input = screen.getByLabelText("Site URL");
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input).toHaveAccessibleDescription(/enter a full url/i);
    expect(screen.getByRole("alert")).toHaveTextContent(/enter a full url/i);
  });

  it("carries a hint as the description when there is no error", () => {
    render(<TextField label="Slug" hint="Lower case, dashes instead of spaces" />);
    expect(screen.getByLabelText("Slug")).toHaveAccessibleDescription(
      /lower case, dashes/i,
    );
  });

  it("describes by BOTH hint and error when both are present", () => {
    render(<TextField label="Slug" hint="Lower case" error="Already taken" />);
    const desc = screen.getByLabelText("Slug").getAttribute("aria-describedby") ?? "";
    expect(desc.trim().split(/\s+/)).toHaveLength(2);
  });

  it("never points at an element that was not rendered", () => {
    render(<TextField label="Slug" />);
    expect(screen.getByLabelText("Slug")).not.toHaveAttribute("aria-describedby");
  });

  it("is invalid only when it has an error", () => {
    render(<TextField label="Slug" />);
    expect(screen.getByLabelText("Slug")).not.toHaveAttribute("aria-invalid");
  });

  it("gives each field its own ids, so two fields never collide", () => {
    render(
      <>
        <TextField label="First" />
        <TextField label="Second" />
      </>,
    );
    expect(screen.getByLabelText("First").id).not.toBe(screen.getByLabelText("Second").id);
  });

  it("keeps the .fld structure the stylesheet already targets", () => {
    const { container } = render(<TextField label="Slug" />);
    expect(container.querySelector(".fld")).not.toBeNull();
  });
});

describe("SelectField", () => {
  it("labels the select and renders its placeholder as the empty option", () => {
    render(
      <SelectField label="Client" placeholder="Choose a client…">
        <option value="c1">NorthPeak Dental</option>
      </SelectField>,
    );
    const select = screen.getByLabelText("Client");
    expect(select).toBeInstanceOf(HTMLSelectElement);
    expect(screen.getByRole("option", { name: "Choose a client…" })).toHaveValue("");
  });

  it("omits the empty option when no placeholder is given", () => {
    render(
      <SelectField label="Mode">
        <option value="a">A</option>
      </SelectField>,
    );
    expect(screen.getAllByRole("option")).toHaveLength(1);
  });
});

describe("Field (custom controls)", () => {
  it("hands the wiring to whatever control the caller renders", () => {
    render(
      <Field label="Notes" required error="Too short">
        {(wiring) => <textarea {...wiring} />}
      </Field>,
    );
    const area = screen.getByLabelText(/notes/i);
    expect(area.tagName).toBe("TEXTAREA");
    expect(area).toBeRequired();
    expect(area).toHaveAttribute("aria-invalid", "true");
  });
});
