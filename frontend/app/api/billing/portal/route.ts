import Stripe from "stripe";
import { NextResponse } from "next/server";
import { createSupabaseServerClient } from "@/lib/supabase-server";

export const runtime = "nodejs";

export async function POST() {
  const secretKey = process.env.STRIPE_SECRET_KEY;
  if (!secretKey) {
    return NextResponse.json(
      { detail: "Stripe billing is not configured." },
      { status: 503 }
    );
  }

  const supabase = await createSupabaseServerClient();
  const { data: { user }, error: authError } = await supabase.auth.getUser();
  if (authError || !user) {
    return NextResponse.json({ detail: "Sign in to manage billing." }, { status: 401 });
  }

  const { data: profile } = await supabase
    .from("profiles")
    .select("stripe_customer_id")
    .eq("id", user.id)
    .single();

  if (!profile?.stripe_customer_id) {
    return NextResponse.json({ detail: "No billing account found." }, { status: 404 });
  }

  const stripe = new Stripe(secretKey);
  const appUrl = process.env.NEXT_PUBLIC_APP_URL || "http://localhost:3000";
  const portal = await stripe.billingPortal.sessions.create({
    customer: profile.stripe_customer_id,
    return_url: appUrl,
  });

  return NextResponse.json({ url: portal.url });
}
