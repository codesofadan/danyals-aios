-- 0005_activity_log.sql - the central, append-only activity feed.
--
-- Actor identity is SNAPSHOTTED (name/init/color) so an entry survives the user
-- being deleted. The table is append-only from the app's view: staff may read,
-- but there are NO insert/update/delete policies, so a user-JWT client can never
-- write or tamper. The server appends via the service_role client (which bypasses
-- RLS), giving a trustworthy audit trail.

create table public.activity_log (
  id          uuid primary key default gen_random_uuid(),
  actor_id    uuid references public.users (id) on delete set null,
  actor_name  text not null default '',
  actor_init  text not null default '',
  actor_color text not null default '#7B69EE',
  kind        text not null,
  action      text not null,
  target      text not null default '',
  meta        text,
  created_at  timestamptz not null default now()
);

create index activity_log_created_at_idx on public.activity_log (created_at desc);

alter table public.activity_log enable row level security;
alter table public.activity_log force row level security;

-- Read-only for staff; writes happen only via the service_role server client.
create policy activity_log_select on public.activity_log
  for select using (public.is_staff());
