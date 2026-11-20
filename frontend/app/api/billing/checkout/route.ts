import Stripe from "stripe";
import { NextResponse } from "next/server";
import { createSupabaseServerClient } from "@/lib/supabase-server";

export const runtime = "nodejs";

export async function POST() {
  const secretKey = process.env.STRIPE_SECRET_KEY;
  const priceId = process.env.STRIPE_PRO_PRICE_ID;
  if (!secretKey || !priceId) {
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

  const stripe = new Stripe(secretKey);
  const appUrl = process.env.NEXT_PUBLIC_APP_URL || "http://localhost:3000";
  const checkout = await stripe.checkout.sessions.create({
    mode: "subscription",
    line_items: [{ price: priceId, quantity: 1 }],
    customer_email: user.email,
    metadata: { supabase_user_id: user.id },
    subscription_data: {
      metadata: { supabase_user_id: user.id },
    },
    success_url: `${appUrl}/?billing=success`,
    cancel_url: `${appUrl}/?billing=cancelled`,
  });

  if (!checkout.url) {
    return NextResponse.json({ detail: "Unable to start checkout." }, { status: 500 });
  }

  return NextResponse.json({ url: checkout.url });
}
