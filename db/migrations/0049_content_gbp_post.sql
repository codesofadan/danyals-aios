-- 0049_content_gbp_post.sql
-- Add 'gbp_post' (GMB Post) to the content_page_type enum.
--
-- The frontend has always offered gbp_post (frontend/lib/content.ts PageType +
-- PAGE_TYPES) and the content service fully handles it (auto_framework -> "4 U's",
-- schema_for -> "" i.e. no JSON-LD, content_qa special-cases it), but 0017's enum
-- shipped with only ('service','blog','local'). So creating a GMB-post content job
-- inserted an out-of-enum value and the write 500'd. ADD VALUE IF NOT EXISTS is
-- idempotent and safe to re-run.

alter type public.content_page_type add value if not exists 'gbp_post';
