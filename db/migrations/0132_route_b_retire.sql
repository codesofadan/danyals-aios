-- 0132_route_b_retire.sql - retire submission route B with the Playwright bot
-- (off-page redesign Phase 3, resolution C1).
--
-- Route B meant "an undefended open form the SELF-HOSTED BOT submits to" - a route
-- only ever entered by activating a directory spec (0111's activate promoted the
-- directory to B in the same transaction). The bot is deleted: no stealth, no
-- fingerprint masking, no CAPTCHA solving, no residential proxy - so no directory can
-- be "bot-submittable" any more, and a route that says it is would be a claim with no
-- machine behind it. Every route-B row folds back into route C (a human works the
-- directory by hand in the operator queue).
--
-- The EARNED SPECS THEMSELVES ARE KEPT: `directory_specs` rows (verified + first-live
-- + active, 0108) now power the Chrome extension's AUTOFILL in the operator queue -
-- the operator reviews and submits in their own browser. The same fail-closed drift
-- rule still governs them (an operator's `form_changed` report deactivates the spec).
--
-- Likely 0 rows today (route B was measured empty on this catalogue) - that is fine;
-- the statement is idempotent by construction (a second run matches nothing).

update public.directories set route = 'C' where route = 'B';
