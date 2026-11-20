import { NextResponse } from "next/server";
import { createSupabaseServerClient } from "@/lib/supabase-server";

export const runtime = "nodejs";

export async function GET() {
  const supabase = await createSupabaseServerClient();
  const { data: { user }, error: authError } = await supabase.auth.getUser();
  if (authError || !user) {
    return NextResponse.json({ plan: "free", authenticated: false }, { status: 401 });
  }

  const { data: profile, error: profileError } = await supabase
    .from("profiles")
    .select("plan, subscription_status")
    .eq("id", user.id)
    .maybeSingle();

  if (profileError) {
    return NextResponse.json(
      { detail: "Unable to read billing status.", plan: "free", authenticated: true },
      { status: 500 }
    );
  }

  const isPro =
    profile?.plan === "pro"
    && (profile.subscription_status === "active" || profile.subscription_status === "trialing");

  return NextResponse.json({
    plan: isPro ? "pro" : "free",
    authenticated: true,
  });
}
