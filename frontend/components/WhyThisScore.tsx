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
        <h2 className="font-medium text-neutral-100">Why this score</h2>
        <span
          className={`text-neutral-500 transition-transform duration-200 ${open ? "rotate-180" : ""}`}
        >
          ▾
        </span>
      </button>

      {open && (
        <div className="mt-4 space-y-5 animate-[fadeIn_0.2s_ease-out]">
          <p className="text-sm leading-6 text-neutral-400">{data.explanation}</p>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
            <div>
              <p className="eyebrow mb-3">
                Strengths
              </p>
              <ul className="space-y-1.5">
                {data.strengths.map((s, i) => (
                  <li key={i} className="flex items-start gap-2.5 text-sm leading-6 text-neutral-400">
                    <span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-neutral-200" />
                    {s}
                  </li>
                ))}
              </ul>
            </div>

            <div>
              <p className="eyebrow mb-3">
                Areas to improve
              </p>
              <ul className="space-y-1.5">
                {data.gaps.map((g, i) => (
                  <li key={i} className="flex items-start gap-2.5 text-sm leading-6 text-neutral-400">
                    <span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-neutral-600" />
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