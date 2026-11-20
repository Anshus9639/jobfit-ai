import Stripe from "stripe";
import { NextRequest, NextResponse } from "next/server";

export const runtime = "nodejs";

async function updateProfileById(
  userId: string,
  update: Record<string, string | null>
) {
  const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const serviceRoleKey = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!supabaseUrl || !serviceRoleKey) {
    throw new Error("SUPABASE_SERVICE_ROLE_KEY is not configured.");
  }

  const response = await fetch(`${supabaseUrl}/rest/v1/profiles?id=eq.${encodeURIComponent(userId)}`, {
    method: "PATCH",
    headers: {
      apikey: serviceRoleKey,
      Authorization: `Bearer ${serviceRoleKey}`,
      "Content-Type": "application/json",
      Prefer: "return=minimal",
    },
    body: JSON.stringify(update),
  });
  if (!response.ok) {
    throw new Error(`Supabase profile update failed: ${await response.text()}`);
  }
}

async function updateProfileByCustomer(
  customerId: string,
  update: Record<string, string | null>
) {
  const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const serviceRoleKey = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!supabaseUrl || !serviceRoleKey) {
    throw new Error("SUPABASE_SERVICE_ROLE_KEY is not configured.");
  }

  const response = await fetch(`${supabaseUrl}/rest/v1/profiles?stripe_customer_id=eq.${encodeURIComponent(customerId)}`, {
    method: "PATCH",
    headers: {
      apikey: serviceRoleKey,
      Authorization: `Bearer ${serviceRoleKey}`,
      "Content-Type": "application/json",
      Prefer: "return=minimal",
    },
    body: JSON.stringify(update),
  });
  if (!response.ok) {
    throw new Error(`Supabase profile update failed: ${await response.text()}`);
  }
}

export async function POST(request: NextRequest) {
  const secretKey = process.env.STRIPE_SECRET_KEY;
  const webhookSecret = process.env.STRIPE_WEBHOOK_SECRET;
  if (!secretKey || !webhookSecret) {
    return NextResponse.json({ detail: "Stripe webhook is not configured." }, { status: 503 });
  }

  const signature = request.headers.get("stripe-signature");
  if (!signature) {
    return NextResponse.json({ detail: "Missing Stripe signature." }, { status: 400 });
  }

  const stripe = new Stripe(secretKey);
  let event: Stripe.Event;
  try {
    event = stripe.webhooks.constructEvent(
      await request.text(),
      signature,
      webhookSecret
    );
  } catch (error) {
    return NextResponse.json(
      { detail: error instanceof Error ? error.message : "Invalid webhook signature." },
      { status: 400 }
    );
  }

  if (event.type === "checkout.session.completed") {
    const session = event.data.object as Stripe.Checkout.Session;
    const userId =
      session.metadata?.supabase_user_id ||
      (session.subscription && typeof session.subscription !== "string"
        ? session.subscription.metadata?.supabase_user_id
        : null);
    const customerId =
      typeof session.customer === "string" ? session.customer : session.customer?.id;
    const subscriptionId =
      typeof session.subscription === "string"
        ? session.subscription
        : session.subscription?.id;

    if (userId) {
      await updateProfileById(userId, {
        stripe_customer_id: customerId ?? null,
        stripe_subscription_id: subscriptionId ?? null,
        plan: "pro",
        subscription_status: "active",
      });
    }
  }

  if (
    event.type === "customer.subscription.updated" ||
    event.type === "customer.subscription.deleted"
  ) {
    const subscription = event.data.object as Stripe.Subscription;
    const customerId =
      typeof subscription.customer === "string"
        ? subscription.customer
        : subscription.customer.id;
    const active = event.type === "customer.subscription.updated"
      && ["active", "trialing"].includes(subscription.status);

    await updateProfileByCustomer(customerId, {
      stripe_subscription_id: subscription.id,
      plan: active ? "pro" : "free",
      subscription_status: subscription.status,
    });
  }

  if (event.type === "invoice.payment_failed") {
    const invoice = event.data.object as Stripe.Invoice;
    const customerId =
      typeof invoice.customer === "string" ? invoice.customer : invoice.customer?.id;
    if (customerId) {
      await updateProfileByCustomer(customerId, {
        subscription_status: "past_due",
      });
    }
  }

  return NextResponse.json({ received: true });
}
