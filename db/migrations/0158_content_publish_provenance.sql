-- 0158_content_publish_provenance.sql - what we published, and when, so a re-push can
-- tell whether it is about to destroy someone else's work.
--
-- THE DEFECT. `POST /content/jobs/{code}/republish` re-pushes an approved page to the
-- client's WordPress site, and the push is idempotent by `wp_post_id` - it UPDATES the
-- same post rather than creating a second one. That idempotency is correct and load-
-- bearing: without it a re-push would litter the client's site with duplicates.
--
-- It also means the post's body is REPLACED. If the client edited that page themselves -
-- fixed a phone number, softened a sentence, added a paragraph - their edit is gone, with
-- no warning, no record, and nothing anywhere that could have warned anyone, because the
-- platform stored nothing about what it had published or when.
--
-- WHAT THESE THREE COLUMNS MAKE POSSIBLE.
--
--   published_body_hash      sha256 of the HTML we last sent. Lets a later push say
--                            "the body on the site is not the body we wrote" without
--                            keeping a second copy of every page.
--   published_remote_modified  the post's own `modified_gmt` as WordPress reported it at
--                            our push. The REST transport returns it; comparing it on the
--                            next push is an EXACT answer to "did anything change since
--                            we wrote this", where a content comparison would be a guess
--                            (themes, plugins and shortcodes all rewrite a body on
--                            render). Text, not timestamptz: it is WordPress's own string
--                            and is compared for equality, never arithmetic.
--   published_at             when WE last pushed. The anchor for both of the above, and
--                            the thing an operator actually asks for first.
--
-- WHAT THIS MIGRATION DOES NOT CLAIM. The AIOS Publisher plugin path cannot report a
-- remote modified time (its REST surface is `/publish` + `/ping`, nothing that reads a
-- post), so for a plugin-published page these columns record what WE did and cannot prove
-- what the client did. The guard is honest about that rather than inferring: the republish
-- endpoint requires an explicit confirmation whenever the remote state cannot be proven
-- unchanged, instead of silently assuming it is.
--
-- Additive, nullable, idempotent. Every existing row keeps NULL, which reads correctly as
-- "we did not record this", never as "nothing was published".

alter table public.content_jobs
  add column if not exists published_body_hash text;

alter table public.content_jobs
  add column if not exists published_remote_modified text;

alter table public.content_jobs
  add column if not exists published_at timestamptz;

comment on column public.content_jobs.published_body_hash is
  'sha256 of the HTML body the platform last pushed for this job. Used to tell a re-push '
  'that the live body is no longer the one we wrote, without storing a second copy.';

comment on column public.content_jobs.published_remote_modified is
  'The post''s own modified time as the transport reported it at our last push '
  '(WordPress ``modified_gmt``). Compared for EQUALITY on the next push: unequal means '
  'the page changed on the client''s side since we wrote it. NULL when the transport '
  'cannot report it (the AIOS Publisher plugin path), which is why the republish guard '
  'asks for a confirmation rather than inferring safety from a missing value.';

comment on column public.content_jobs.published_at is
  'When the platform last pushed this job to the client''s site. Distinct from '
  'updated_at, which moves on every stage write.';
