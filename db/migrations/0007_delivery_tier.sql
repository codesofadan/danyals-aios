-- 0007_delivery_tier.sql - the per-client DELIVERY tier (free/semi/fully).
--
-- Kept SEPARATE from the subscription/billing tier (clients.tier =
-- Starter/Growth/Scale, added in 0003). Delivery tier is a preset over the cost
-- dial; the two are distinct concepts and never conflated.

do $$ begin
  if not exists (select 1 from pg_type where typname = 'delivery_tier') then
    create type public.delivery_tier as enum ('free', 'semi', 'fully');
  end if;
end $$;

alter table public.clients
  add column if not exists delivery_tier public.delivery_tier not null default 'free';
