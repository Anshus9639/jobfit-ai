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
      <div className="max-w-3xl mx-auto px-4 py-12 sm:py-16">
        <header className="text-center mb-10">
          <h1 className="text-4xl sm:text-5xl font-bold tracking-tight text-slate-900">
            JobFit <span className="text-brand-600">AI</span>
          </h1>
          <p className="text-slate-500 mt-3 text-lg">
            See how closely your resume matches the job.
          </p>
        </header>

        {error && (
          <div className="mb-6 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}

        {!result ? (
          <UploadForm onSubmit={handleSubmit} loading={loading} />
        ) : (
          <Results result={result} onReset={handleReset} />
        )}

        <footer className="text-center text-xs text-slate-400 mt-12">
          ATS-style analysis for guidance only — not affiliated with any employer's actual ATS.
        </footer>
      </div>
    </main>
  );
}
