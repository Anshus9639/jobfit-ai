"use client";

import { useState } from "react";
import { ImprovementSuggestion } from "@/lib/types";

interface ImproveResumeProps {
  suggestions: ImprovementSuggestion[];
}

export default function ImproveResume({ suggestions }: ImproveResumeProps) {
  const [open, setOpen] = useState(true);

  if (suggestions.length === 0) {
    return (
      <div className="card">
        <h2 className="font-semibold text-slate-800 mb-1">Improve Your Resume ✍️</h2>
        <p className="text-sm text-slate-400">
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
        <h2 className="font-semibold text-slate-800">Improve Your Resume ✍️</h2>
        <span
          className={`text-slate-400 transition-transform duration-300 ${open ? "rotate-180" : ""}`}
        >
          ▾
        </span>
      </button>

      {open && (
        <div className="mt-4 space-y-4 animate-[fadeIn_0.2s_ease-out]">
          <p className="text-xs text-slate-500 bg-slate-50 border border-slate-200 rounded-lg px-3 py-2.5 leading-relaxed">
            Suggestions are based on information detected in your resume. Verify that every
            suggested statement accurately reflects your actual experience.
          </p>

          {suggestions.map((s, i) => (
            <div key={i} className="rounded-xl border border-slate-200 p-4 space-y-2.5">
              <div>
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">
                  Original
                </p>
                <p className="text-sm text-slate-600 mt-0.5">{s.original}</p>
              </div>

              {s.type === "rewrite" && s.suggestion ? (
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wide text-emerald-600">
                    Suggested
                  </p>
                  <p className="text-sm text-slate-800 mt-0.5">{s.suggestion}</p>
                </div>
              ) : (
                <div>
                  <span className="badge bg-amber-50 text-amber-700 border border-amber-200 text-xs">
                    Recommendation
                  </span>
                </div>
              )}

              <p className="text-xs text-slate-400 italic">{s.why}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}