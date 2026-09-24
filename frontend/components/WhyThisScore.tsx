"use client";

import { useState } from "react";
import { ScoreExplanation } from "@/lib/types";

interface WhyThisScoreProps {
  data: ScoreExplanation;
}

export default function WhyThisScore({ data }: WhyThisScoreProps) {
  const [open, setOpen] = useState(true);

  return (
    <div className="card">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between text-left"
        aria-expanded={open}
      >
        <h2 className="font-semibold text-slate-800">Why did I get this score?</h2>
        <span
          className={`text-slate-400 transition-transform duration-300 ${open ? "rotate-180" : ""}`}
        >
          ▾
        </span>
      </button>

      {open && (
        <div className="mt-4 space-y-5 animate-[fadeIn_0.2s_ease-out]">
          <p className="text-sm text-slate-600 leading-relaxed">{data.explanation}</p>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-emerald-600 mb-2">
                Strengths
              </p>
              <ul className="space-y-1.5">
                {data.strengths.map((s, i) => (
                  <li key={i} className="flex items-start gap-2 text-sm text-slate-600">
                    <span className="text-emerald-500 font-semibold mt-0.5 shrink-0">✓</span>
                    {s}
                  </li>
                ))}
              </ul>
            </div>

            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-amber-600 mb-2">
                Potential gaps
              </p>
              <ul className="space-y-1.5">
                {data.gaps.map((g, i) => (
                  <li key={i} className="flex items-start gap-2 text-sm text-slate-600">
                    <span className="text-amber-500 font-semibold mt-0.5 shrink-0">⚠</span>
                    {g}
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}