"use client";

import { useState } from "react";
import { ImprovementSuggestion } from "@/lib/types";

interface ImproveResumeProps {
  suggestions: ImprovementSuggestion[];
}

export default function ImproveResume({ suggestions }: ImproveResumeProps) {
  const [open, setOpen] = useState(true);
  const [drafts, setDrafts] = useState<Record<number, string>>({});
  const [copied, setCopied] = useState<number | null>(null);

  async function copyDraft(index: number, text: string) {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(index);
      window.setTimeout(() => setCopied(null), 1500);
    } catch {
      setCopied(null);
    }
  }

  if (suggestions.length === 0) {
    return (
      <div className="card">
        <h2 className="font-medium text-neutral-100">Resume improvements</h2>
        <p className="mt-2 text-sm text-neutral-500">
          No generic or weak statements detected — nice work.
        </p>
      </div>
    );
  }

  return (
    <div className="card">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between text-left"
        aria-expanded={open}
      >
        <h2 className="font-medium text-neutral-100">Resume improvements</h2>
        <span
          className={`text-neutral-500 transition-transform duration-200 ${open ? "rotate-180" : ""}`}
        >
          ▾
        </span>
      </button>

      {open && (
        <div className="mt-4 space-y-4 animate-[fadeIn_0.2s_ease-out]">
          <p className="rounded-lg border border-white/[0.08] bg-white/[0.025] px-3 py-3 text-xs leading-5 text-neutral-500">
            Suggestions are based on information detected in your resume. Verify that every
            suggested statement accurately reflects your actual experience.
          </p>

          {suggestions.map((s, i) => (
            <div key={i} className="space-y-3 rounded-xl border border-white/[0.08] p-4">
              <div>
                <p className="eyebrow">
                  Original
                </p>
                <p className="mt-1.5 text-sm leading-6 text-neutral-400">{s.original}</p>
              </div>

              {s.type === "rewrite" && s.suggestion ? (
                <div>
                  <p className="eyebrow">
                    Rewrite workspace
                  </p>
                  <textarea
                    value={drafts[i] ?? s.suggestion}
                    onChange={(event) => setDrafts((current) => ({ ...current, [i]: event.target.value }))}
                    rows={4}
                    aria-label={`Edit rewrite for: ${s.original}`}
                    className="field mt-2 resize-y"
                  />
                  <div className="mt-2 flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => copyDraft(i, drafts[i] ?? s.suggestion ?? "")}
                      className="secondary-button px-3 py-2 text-xs"
                    >
                      {copied === i ? "Copied" : "Copy rewrite"}
                    </button>
                    {drafts[i] !== undefined && drafts[i] !== s.suggestion && (
                      <button
                        type="button"
                        onClick={() => setDrafts((current) => {
                          const next = { ...current };
                          delete next[i];
                          return next;
                        })}
                        className="px-2 py-2 text-xs text-neutral-600 transition hover:text-neutral-300"
                      >
                        Reset
                      </button>
                    )}
                  </div>
                </div>
              ) : (
                <div>
                  <span className="badge badge-missing">
                    Recommendation
                  </span>
                </div>
              )}

              <p className="text-xs leading-5 text-neutral-600">{s.why}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}