"use client";

import { useState } from "react";
import UploadForm from "@/components/UploadForm";
import Results from "@/components/Results";
import { analyzeResume } from "@/lib/api";
import { AnalyzeResult } from "@/lib/types";

export default function Home() {
  const [result, setResult] = useState<AnalyzeResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(resumeFile: File, jobDescription: string) {
    setLoading(true);
    setError(null);
    try {
      const data = await analyzeResume(resumeFile, jobDescription);
      setResult(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong. Please try again.");
    } finally {
      setLoading(false);
    }
  }

  function handleReset() {
    setResult(null);
    setError(null);
  }

  return (
    <main className="min-h-screen">
      <div className="mx-auto max-w-5xl px-4 py-10 sm:px-6 sm:py-16">
        <header className="mx-auto mb-10 max-w-3xl text-center">
          <div className="mb-5 inline-flex items-center gap-2 rounded-full border border-brand-100 bg-white/75 px-3 py-1.5 text-xs font-medium text-slate-600 shadow-sm">
            <span className="h-1.5 w-1.5 rounded-full bg-cyan-400 shadow-[0_0_0_4px_rgba(34,211,238,0.12)]" />
            Resume intelligence, made simple
          </div>
          <h1 className="text-5xl font-bold tracking-tight text-slate-950 sm:text-6xl">
            JobFit{" "}
            <span className="bg-gradient-to-r from-brand-600 via-indigo-500 to-cyan-500 bg-clip-text text-transparent">
              AI
            </span>
          </h1>
          <p className="mt-4 text-lg leading-relaxed text-slate-500">
            See how closely your resume matches the job.
          </p>
        </header>

        {error && (
          <div className="mx-auto mb-6 max-w-3xl rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 shadow-sm">
            {error}
          </div>
        )}

        {!result ? (
          <UploadForm onSubmit={handleSubmit} loading={loading} />
        ) : (
          <Results result={result} onReset={handleReset} />
        )}

        <footer className="mt-12 text-center text-xs text-slate-400">
          ATS-style analysis for guidance only — not affiliated with any employer's actual ATS.
        </footer>
      </div>
    </main>
  );
}
