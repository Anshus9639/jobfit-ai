"use client";

import { FormEvent, useState } from "react";
import { createSupabaseBrowserClient } from "@/lib/supabase-browser";

export default function AuthPage() {
  const [mode, setMode] = useState<"sign-in" | "sign-up">("sign-in");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleEmailSubmit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError(null);
    setMessage(null);

    const supabase = createSupabaseBrowserClient();
    const redirectTo = `${window.location.origin}/auth/callback`;

    try {
      if (mode === "sign-up") {
        const { error: signUpError } = await supabase.auth.signUp({
          email,
          password,
          options: { emailRedirectTo: redirectTo },
        });
        if (signUpError) throw signUpError;
        setMessage("Check your email to confirm your account.");
      } else {
        const { error: signInError } = await supabase.auth.signInWithPassword({
          email,
          password,
        });
        if (signInError) throw signInError;
        window.location.assign("/");
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Authentication failed.");
    } finally {
      setLoading(false);
    }
  }

  async function handleGoogleSignIn() {
    setLoading(true);
    setError(null);
    const supabase = createSupabaseBrowserClient();
    const { error: googleError } = await supabase.auth.signInWithOAuth({
      provider: "google",
      options: {
        redirectTo: `${window.location.origin}/auth/callback`,
      },
    });
    if (googleError) setError(googleError.message);
    setLoading(false);
  }

  return (
    <main className="mx-auto min-h-[calc(100vh-8rem)] max-w-md px-5 py-16 sm:py-24">
      <a href="/" className="flex items-center gap-2.5 text-sm font-semibold text-white">
        <span className="flex h-7 w-7 items-center justify-center rounded-md border border-white/15 bg-white/[0.06] text-[10px]">
          JF
        </span>
        JobFit AI
      </a>

      <section className="mt-12">
        <p className="eyebrow">{mode === "sign-in" ? "Welcome back" : "Create account"}</p>
        <h1 className="mt-3 text-3xl font-semibold tracking-tight text-white">
          {mode === "sign-in" ? "Sign in" : "Start with JobFit"}
        </h1>

        <button
          type="button"
          onClick={handleGoogleSignIn}
          disabled={loading}
          className="secondary-button mt-8 w-full"
        >
          Continue with Google
        </button>

        <div className="my-6 flex items-center gap-3">
          <span className="h-px flex-1 bg-white/[0.08]" />
          <span className="text-xs text-neutral-600">or</span>
          <span className="h-px flex-1 bg-white/[0.08]" />
        </div>

        <form onSubmit={handleEmailSubmit} className="space-y-4">
          <div>
            <label htmlFor="email" className="mb-2 block text-xs text-neutral-500">Email</label>
            <input
              id="email"
              type="email"
              required
              autoComplete="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              className="field"
              placeholder="you@example.com"
            />
          </div>
          <div>
            <label htmlFor="password" className="mb-2 block text-xs text-neutral-500">Password</label>
            <input
              id="password"
              type="password"
              required
              minLength={8}
              autoComplete={mode === "sign-in" ? "current-password" : "new-password"}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              className="field"
              placeholder="At least 8 characters"
            />
          </div>
          {error && (
            <p role="alert" className="rounded-lg border border-neutral-600/50 bg-neutral-900 px-3 py-2.5 text-sm text-neutral-300">
              {error}
            </p>
          )}
          {message && (
            <p role="status" className="rounded-lg border border-white/[0.10] bg-white/[0.035] px-3 py-2.5 text-sm text-neutral-300">
              {message}
            </p>
          )}
          <button type="submit" disabled={loading} className="primary-button w-full">
            {loading ? "Please wait..." : mode === "sign-in" ? "Sign in" : "Create account"}
          </button>
        </form>

        <button
          type="button"
          onClick={() => {
            setMode((current) => current === "sign-in" ? "sign-up" : "sign-in");
            setError(null);
            setMessage(null);
          }}
          className="mt-6 w-full text-center text-xs text-neutral-500 transition hover:text-neutral-200"
        >
          {mode === "sign-in" ? "New to JobFit AI? Create an account" : "Already have an account? Sign in"}
        </button>
      </section>
    </main>
  );
}
