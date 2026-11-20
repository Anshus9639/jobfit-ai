-- Required for server-side Stripe webhook updates using SUPABASE_SERVICE_ROLE_KEY.
grant usage on schema public to service_role;
grant select, insert, update, delete on public.profiles to service_role;
grant select, insert, update, delete on public.analysis_usage to service_role;
grant select, insert, update, delete on public.saved_analyses to service_role;

-- Authenticated users may read their own profile and analyses.
grant select on public.profiles to authenticated;
grant select on public.analysis_usage to authenticated;
grant select, insert, update, delete on public.saved_analyses to authenticated;

drop policy if exists "Users can read their own profile" on public.profiles;
create policy "Users can read their own profile"
  on public.profiles for select
  to authenticated
  using (auth.uid() = id);
