create or replace function public.reserve_analysis()
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  current_user_id uuid := auth.uid();
  current_plan text;
  current_status text;
  current_month date := date_trunc('month', now())::date;
  current_count integer := 0;
begin
  if current_user_id is null then
    raise exception 'Authentication required';
  end if;

  select plan, subscription_status
  into current_plan, current_status
  from public.profiles
  where id = current_user_id;

  if current_plan is not null
     and current_plan <> 'free'
     and current_status in ('active', 'trialing') then
    return jsonb_build_object('allowed', true, 'unlimited', true);
  end if;

  insert into public.analysis_usage (user_id, month_start, count)
  values (current_user_id, current_month, 0)
  on conflict (user_id, month_start) do nothing;

  select count
  into current_count
  from public.analysis_usage
  where user_id = current_user_id
    and month_start = current_month
  for update;

  if current_count >= 3 then
    return jsonb_build_object('allowed', false, 'remaining', 0, 'limit', 3);
  end if;

  update public.analysis_usage
  set count = current_count + 1,
      updated_at = now()
  where user_id = current_user_id
    and month_start = current_month;

  return jsonb_build_object(
    'allowed', true,
    'remaining', 2 - current_count,
    'limit', 3
  );
end;
$$;

revoke all on function public.reserve_analysis() from public;
grant execute on function public.reserve_analysis() to authenticated;
