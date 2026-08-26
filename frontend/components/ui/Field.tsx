"use client";

// An input field, as one thing.
//
// There was no such thing in this codebase. There were 155 form controls in 34
// files, each assembled by hand as `<div class="fld"><label>X</label><input/></div>`
// — a CSS CONVENTION, not a component. Every new form re-litigated focus ring,
// spacing, error placement and label wiring, and every one got it slightly
// differently: 9 distinct input styling implementations, 39 CSS rules touching
// `input`, and 5 separate re-declarations of the same focus ring.
//
// The cost was not only visual. Of 164 `<label>` elements only 14 carried
// `htmlFor`, and only 12 inputs had an `id` — and because the labels sit as
// SIBLINGS of their input inside `.fld` rather than wrapping it, there was no
// implicit association either. A screen reader announced roughly 141 of the 155
// controls as unlabelled. Required-ness was indicated on two controls in the
// whole product, and field-level errors did not exist at all: every failure
// surfaced as one banner at the bottom of the form, which in the largest modal
// meant an error 31 fields away from the thing that caused it.
//
// DELIBERATELY RENDERS THE EXISTING `.fld` MARKUP. Adopting this changes no
// pixels — it is the same structure globals.css already styles — so a form can
// move onto it one field at a time without a visual review. What it adds is the
// wiring: a generated id, htmlFor, aria-describedby, aria-invalid, a real
// required marker, and somewhere for an error to live next to its own input.

import { useId, type ReactNode, type SelectHTMLAttributes, type InputHTMLAttributes } from "react";

type FieldShellProps = {
  label: ReactNode;
  /** Marks the control required, visually AND to assistive tech. */
  required?: boolean;
  /** Quiet guidance shown under the label. Say the format, not the obvious. */
  hint?: ReactNode;
  /** The message for THIS field. Its presence sets aria-invalid on the control. */
  error?: string | null;
  className?: string;
  /** Receives the ids to wire onto the control. */
  children: (wiring: {
    id: string;
    "aria-describedby": string | undefined;
    "aria-invalid": boolean | undefined;
    required: boolean | undefined;
  }) => ReactNode;
};

export function Field({
  label,
  required,
  hint,
  error,
  className,
  children,
}: FieldShellProps) {
  const id = useId();
  const hintId = `${id}-hint`;
  const errorId = `${id}-error`;
  // Point the control at whichever of the two actually rendered, so a screen
  // reader never chases a dangling id.
  const describedBy = [hint ? hintId : null, error ? errorId : null]
    .filter(Boolean)
    .join(" ");

  return (
    <div className={className ? `fld ${className}` : "fld"}>
      <label htmlFor={id}>
        {label}
        {required ? (
          <>
            {" "}
            <span aria-hidden="true" style={{ color: "var(--crit)" }}>
              *
            </span>
            <span className="sr-only"> (required)</span>
          </>
        ) : null}
      </label>
      {hint ? (
        <div id={hintId} style={{ fontSize: "var(--fs-xs)", color: "var(--muted)" }}>
          {hint}
        </div>
      ) : null}
      {children({
        id,
        "aria-describedby": describedBy || undefined,
        "aria-invalid": error ? true : undefined,
        required: required || undefined,
      })}
      {error ? (
        // role="alert" so the message is announced when it appears, rather than
        // only being found by someone who happens to tab back to the field.
        <div
          id={errorId}
          role="alert"
          style={{
            marginTop: "var(--s-2)",
            fontSize: "var(--fs-xs)",
            color: "var(--crit)",
          }}
        >
          {error}
        </div>
      ) : null}
    </div>
  );
}

type Shared = Omit<FieldShellProps, "children">;

/** A labelled text input. Covers the 103 bare `<input>` elements. */
export function TextField({
  label,
  required,
  hint,
  error,
  className,
  ...input
}: Shared & Omit<InputHTMLAttributes<HTMLInputElement>, "id" | "required">) {
  return (
    <Field label={label} required={required} hint={hint} error={error} className={className}>
      {(wiring) => <input type="text" {...input} {...wiring} />}
    </Field>
  );
}

/** A labelled select. Covers the 38 bare `<select>` elements.
 *  `placeholder` becomes the empty-value option, which is how every hand-rolled
 *  client picker in this codebase already behaves. */
export function SelectField({
  label,
  required,
  hint,
  error,
  className,
  placeholder,
  children,
  ...select
}: Shared &
  Omit<SelectHTMLAttributes<HTMLSelectElement>, "id" | "required"> & {
    placeholder?: string;
  }) {
  return (
    <Field label={label} required={required} hint={hint} error={error} className={className}>
      {(wiring) => (
        <select {...select} {...wiring}>
          {placeholder !== undefined ? <option value="">{placeholder}</option> : null}
          {children}
        </select>
      )}
    </Field>
  );
}

export default Field;
