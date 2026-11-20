"use client";

import { useEffect, useState } from "react";
import UploadForm from "@/components/UploadForm";
import Results from "@/components/Results";
import { analyzeResume } from "@/lib/api";
import { AnalyzeResult } from "@/lib/types";

interface SavedAnalysis {
  id: string;
  createdAt: string;
  role: string;
  overallScore: number;
  atsScore: number;
  result: AnalyzeResult;
}

const HISTORY_KEY = "jobfit-ai-analysis-history";
const MAX_HISTORY_ITEMS = 10;

export default function Home() {
  const [result, setResult] = useState<AnalyzeResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [history, setHistory] = useState<SavedAnalysis[]>([]);
  const [historyOpen, setHistoryOpen] = useState(false);

  useEffect(() => {
    try {
      const saved = window.localStorage.getItem(HISTORY_KEY);
      if (saved) setHistory(JSON.parse(saved) as SavedAnalysis[]);
    } catch {
      window.localStorage.removeItem(HISTORY_KEY);
    }
  }, []);

  function saveAnalysis(data: AnalyzeResult) {
    const item: SavedAnalysis = {
      id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      createdAt: new Date().toISOString(),
      role: data.job_intelligence.role,
      overallScore: data.overall_score,
      atsScore: data.ats_score,
      result: data,
    };
    const next = [item, ...history].slice(0, MAX_HISTORY_ITEMS);
    setHistory(next);
    window.localStorage.setItem(HISTORY_KEY, JSON.stringify(next));
  }

  async function handleSubmit(resumeFile: File, jobDescription: string) {
    setLoading(true);
    setError(null);
    try {
      const data = await analyzeResume(resumeFile, jobDescription);
      setResult(data);
      saveAnalysis(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong. Please try again.");
    } finally {
      setLoading(false);
    }
  }

  function handleReset() {
    setResult(null);
    setError(null);
    setHistoryOpen(false);
  }

  function deleteHistoryItem(id: string) {
    const next = history.filter((item) => item.id !== id);
    setHistory(next);
    window.localStorage.setItem(HISTORY_KEY, JSON.stringify(next));
  }

  return (
    <main className="min-h-screen bg-[#080808]">
      <nav className="mx-auto flex h-16 max-w-6xl items-center justify-between px-5 sm:px-8">
        <button
          type="button"
          onClick={handleReset}
          className="flex items-center gap-2.5 text-sm font-semibold tracking-tight text-white"
          aria-label="JobFit AI home"
        >
          <span className="flex h-7 w-7 items-center justify-center rounded-md border border-white/15 bg-white/[0.06] text-[10px]">
            JF
          </span>
          JobFit AI
        </button>
        {result ? (
          <div className="flex items-center gap-2">
            <button type="button" onClick={() => window.print()} className="secondary-button px-3.5 py-2">
              Export
            </button>
            <button type="button" onClick={handleReset} className="secondary-button px-3.5 py-2">
              New analysis
            </button>
          </div>
        ) : (
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setHistoryOpen(true)}
              className="secondary-button px-3.5 py-2"
            >
              History
            </button>
            <a href="#analyze" className="secondary-button hidden px-3.5 py-2 sm:inline-flex">
              Analyze resume
            </a>
          </div>
        )}
      </nav>

      {historyOpen && (
        <div className="fixed inset-0 z-50 flex justify-end bg-black/70" role="dialog" aria-modal="true" aria-label="Analysis history">
          <div className="h-full w-full max-w-md border-l border-white/[0.08] bg-[#0d0d0d] p-5 sm:p-7">
            <div className="flex items-center justify-between border-b border-white/[0.08] pb-5">
              <div>
                <p className="eyebrow">Saved locally</p>
                <h2 className="mt-2 text-xl font-semibold text-white">Analysis history</h2>
              </div>
              <button type="button" onClick={() => setHistoryOpen(false)} className="secondary-button px-3 py-2" aria-label="Close history">
                Close
              </button>
            </div>
            <div className="mt-5 space-y-3">
              {history.length === 0 ? (
                <p className="rounded-xl border border-white/[0.08] p-5 text-sm leading-6 text-neutral-500">
                  Completed analyses will appear here on this device.
                </p>
              ) : history.map((item) => (
                <article key={item.id} className="rounded-xl border border-white/[0.08] bg-[#111111] p-4">
                  <button
                    type="button"
                    onClick={() => {
                      setResult(item.result);
                      setHistoryOpen(false);
                    }}
                    className="w-full text-left"
                  >
                    <div className="flex items-start justify-between gap-4">
                      <div>
                        <p className="text-sm font-medium text-neutral-100">{item.role}</p>
                        <p className="mt-1 text-xs text-neutral-600">
                          {new Date(item.createdAt).toLocaleDateString()}
                        </p>
                      </div>
                      <span className="text-lg font-semibold text-neutral-100">{item.overallScore}%</span>
                    </div>
                  </button>
                  <button
                    type="button"
                    onClick={() => deleteHistoryItem(item.id)}
                    className="mt-4 text-xs text-neutral-600 transition hover:text-neutral-300"
                  >
                    Remove
                  </button>
                </article>
              ))}
            </div>
          </div>
        </div>
      )}

      {!result ? (
        <>
          <section className="mx-auto max-w-6xl px-5 pb-12 pt-16 sm:px-8 sm:pb-16 sm:pt-24">
            <div className="max-w-4xl">
              <p className="eyebrow mb-5">Resume intelligence</p>
              <h1 className="max-w-3xl text-[3.25rem] font-semibold leading-[0.98] tracking-[-0.055em] text-white sm:text-[5.5rem]">
                Find your fit.
                <br />
                <span className="text-neutral-500">Know your worth.</span>
              </h1>
              <p className="mt-7 max-w-xl text-base leading-7 text-neutral-400 sm:text-lg">
                Understand how your resume aligns with a specific role, from skills and keywords
                to ATS structure and opportunities to improve.
              </p>
              <div className="mt-9 flex flex-col gap-3 sm:flex-row">
                <a href="#analyze" className="primary-button">
                  Analyze my resume
                  <span className="ml-2 text-neutral-500" aria-hidden="true">↓</span>
                </a>
                <a href="#how-it-works" className="secondary-button">
                  How it works
                </a>
              </div>
            </div>
          </section>

          <section id="analyze" className="border-y border-white/[0.07] bg-[#0d0d0d]">
            <div className="mx-auto max-w-6xl px-5 py-14 sm:px-8 sm:py-20">
              {error && (
                <div
                  role="alert"
                  className="mb-5 rounded-xl border border-neutral-600/50 bg-neutral-900 px-4 py-3 text-sm text-neutral-200"
                >
                  {error}
                </div>
              )}
              <UploadForm onSubmit={handleSubmit} loading={loading} />
            </div>
          </section>

          <section id="how-it-works" className="mx-auto max-w-6xl px-5 py-16 sm:px-8 sm:py-24">
            <p className="eyebrow mb-8">How it works</p>
            <div className="grid border-t border-white/[0.08] md:grid-cols-3">
              {[
                ["01", "Upload", "Add a PDF version of your current resume."],
                ["02", "Compare", "Paste the full description for the role you want."],
                ["03", "Improve", "Review your match, gaps and actionable rewrites."],
              ].map(([number, title, copy]) => (
                <div key={number} className="border-b border-white/[0.08] py-7 md:border-b-0 md:border-r md:px-7 md:first:pl-0 md:last:border-r-0 md:last:pr-0">
                  <span className="text-xs text-neutral-600">{number}</span>
                  <h2 className="mt-8 text-lg font-medium text-neutral-100">{title}</h2>
                  <p className="mt-2 max-w-xs text-sm leading-6 text-neutral-500">{copy}</p>
                </div>
              ))}
            </div>
          </section>
        </>
      ) : (
        <Results result={result} onReset={handleReset} />
      )}

      <footer className="mx-auto flex max-w-6xl flex-col gap-3 border-t border-white/[0.07] px-5 py-8 text-xs text-neutral-600 sm:flex-row sm:items-center sm:justify-between sm:px-8">
        <span>JobFit AI</span>
        <span>ATS-style guidance only — not an employer or real ATS prediction.</span>
      </footer>
    </main>
  );
}
