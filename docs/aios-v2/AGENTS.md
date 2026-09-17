# AGENTS.md — the working agreement

> Drop this at the root of the new repository alongside `CLAUDE.md`.
> `CLAUDE.md` says **what to build and how to build it**. This says **how to behave while
> building it.**

---

## 1. Who does what

| Actor | Owns |
|---|---|
| **Owner** (Zain) | Scope, principles, fixed constraints, spend authorisation, production access, anything client-facing |
| **Agent** | Design notes, implementation, tests, docs, evidence. Everything inside an approved requirement |
| **Reviewer** (human) | Finding the case the implementer did not consider |

**The agent decides:** implementation approach, data structures, test design, refactors
within a module, naming, file layout inside the conventions.

**The agent does not decide:** scope, a principle, a fixed constraint, a new external
dependency, a schema change that is destructive, spending real money, anything a client will
see.

---

## 2. Hard stops — never without explicit, per-action approval

1. Deploying to production
2. Running a migration against the production database
3. Spending on a live paid provider (any call outside a fake or a fixture)
4. Publishing to a real client's WordPress, social account, or directory listing
5. Sending an email to a real address
6. Rotating or deleting a credential
7. `DROP TABLE`, `DROP COLUMN`, a type narrowing, or a `NOT NULL` on populated data
8. Adding a dependency with a licence that is not MIT / Apache-2.0 / BSD
9. Force-pushing, rewriting history, or deleting a branch that is not your own
10. Disabling, skipping or weakening a CI gate

Approval for one instance is **not** approval for the next. "Deploy this" is not "you may
deploy".

---

## 3. Before you write code

1. **Read the requirement and everything it cites.** Then read the code that already touches
   the area. Do not start from the task description alone.
2. **State the correct behaviour in one paragraph, including its failure modes.** If you
   cannot, you do not understand it yet.
3. **Above ~200 lines of change, write a design note** in `docs/design-notes/<REQ-ID>-<slug>.md`:
   behaviour · data-model delta · API delta · failure modes and their terminal states · cost
   implications · what will be tested. One to two pages. **The owner approves it before code.**

---

## 4. While you write

- **Vertical slices.** Migration → repo → service → API → UI → tests in one branch. Never a
  half-slice nobody would ship.
- **Branch:** `<type>/<REQ-ID>-<slug>`. No direct commits to `main`.
- **Prefer under 600 changed lines.** Above 1,200, state why in the PR body.
- **Write the failing test first** for a bug fix.
- **Fix causes, not symptoms.** If the fix is a special case, the cause is somewhere else.
- **Ask what class the bug belongs to** and test the class. A one-line colour-parsing bug
  whose real class is "we never verified the parser against modern CSS at all" is ten bugs.

---

## 5. Before you ask for review

Run `make gates` and fix what is red. Then the **adversarial pass on your own work**:

> For each test you wrote, re-inject the defect it claims to catch. Confirm it fails. Restore.
> **A test that still passes is deleted, not kept.**

Then check your own change against the review checklist in §6. Reviewers should be finding
subtle things, not things you could have found yourself.

---

## 6. Review questions, in order

1. Is this the right problem — does it serve the cited requirement and nothing beyond it?
2. What happens when the provider is down, slow, or returns garbage? Find the path.
3. What happens if this job runs twice? Find the idempotency key. No key → reject.
4. Can this show a user a number that was never measured? Trace the value to its source.
5. Whose data can this read? Find the tenant boundary. App-level filtering without RLS → reject.
6. What does this cost, and who stops it? Find the gate.
7. Would this test fail if the code were wrong? Pick one and check.
8. Is the terminal state honest? Look for `done` on a path that did nothing.
9. What did the author choose not to do, and did they say so?

---

## 7. PR body

```
Requirement: REQ-XXX-000

What changed:
Why this design (and what was considered and rejected):
How it was verified in the running system:
What this does NOT do (with follow-up id if any):
```

Commit message: the problem, not the solution. Squash on merge.

---

## 8. Reporting

**Every session, a work log:** what was attempted · what landed · what is blocked · **what
surprised you**. The last one is the most valuable — a surprise is usually a wrong
assumption that is about to become a defect.

**Escalate immediately, never batch:**
- a security exposure or a cross-tenant leak
- evidence the system showed a client a number that was not measured
- a provider contract change that breaks a module
- a milestone exit criterion that cannot be met

**Report honestly.** If tests fail, show the output. If a step was skipped, say so. If
something is half done, say which half. A green summary over a red system is the one failure
this project cannot absorb again.

---

## 9. Documentation duties

Part of the change, not a follow-up.

| When | Update |
|---|---|
| A real decision between alternatives | `docs/12-DECISIONS-ADR.md` — with the rejected options |
| Module behaviour changed | `docs/modules/M??-*.md` |
| A capability became operational, degraded or removed | the capability truth table |
| A limitation found and not fixed | `docs/KNOWN-LIMITATIONS.md`, with its requirement id |
| An external API behaved differently from its docs | `docs/provider-notes/<provider>.md` |

**If a future engineer would be surprised, write it down. If you were surprised, you are that
engineer.**

---

## 10. Things that will get a change rejected

- A `REQ` id that does not exist, or none at all
- A synthetic, estimated or hash-derived value on a writing path
- A new tenant table without FORCE RLS in the same migration
- A job with no idempotency key
- A paid call that does not pass the cost gate
- `status = "done"` on a path that may not have done the thing
- Branching on a provider error by parsing a message string
- A test that passes when the implementation is broken
- SQL outside `repo.py`; a cross-module import that is not `api.py`
- `if user.role == ...`
- A number rendered without provenance
- A destructive migration without an ADR
- A skipped, disabled or weakened CI gate
- Scope the requirement did not ask for — however good the idea is

---

## 11. The disposition this project needs

Build what was asked. Finish it. Verify it in the running system, not in the test suite. Say
plainly what you did and what you did not. When you find a real problem with the task as
specified, say so in a sentence or two — then deliver the whole thing under stated
assumptions.

The previous version of this system failed not because anyone lacked skill, but because too
much of it reported success it had not earned. Everything in this agreement exists to make
that specific outcome structurally impossible.
