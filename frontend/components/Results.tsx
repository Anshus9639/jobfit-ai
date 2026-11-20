"use client";

import { AnalyzeResult } from "@/lib/types";
import WhyThisScore from "./WhyThisScore";
import JobIntelligence from "./JobIntelligence";
import ResumeXRay from "./ResumeXRay";
import ImproveResume from "./ImproveResume";

interface ResultsProps {
  result: AnalyzeResult;
  onReset: () => void;
}

function ScoreBar({ label, score }: { label: string; score: number }) {
  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <span className="text-sm text-neutral-400">{label}</span>
        <span className="text-sm font-semibold text-neutral-100">{score}%</span>
      </div>
      <div className="progress-track">
        <div
          className="progress-fill"
          style={{ width: `${score}%` }}
        />
      </div>
    </div>
  );
}

export default function Results({ result, onReset }: ResultsProps) {
  const matched = new Set(result.matched_skills.map((skill) => skill.toLowerCase()));
  const missingKeywords = result.job_intelligence.important_keywords.filter(
    (keyword) => !matched.has(keyword.toLowerCase())
  );

  return (
    <section className="mx-auto max-w-6xl px-5 py-10 sm:px-8 sm:py-14">
      <div className="mb-8 flex items-end justify-between border-b border-white/[0.08] pb-6">
        <div>
          <p className="eyebrow">Analysis complete</p>
          <h1 className="mt-3 text-3xl font-semibold tracking-tight text-white sm:text-4xl">
            Your match report
          </h1>
        </div>
      </div>

      <div className="grid gap-5 lg:grid-cols-[1.35fr_0.65fr]">
        <div className="card min-h-72">
          <p className="eyebrow">Resume to job match</p>
          <div className="mt-8 flex items-end gap-3">
            <span className="text-7xl font-semibold leading-none tracking-[-0.06em] text-white sm:text-8xl">
              {result.overall_score}
            </span>
            <span className="mb-2 text-xl text-neutral-500">%</span>
          </div>
          <p className="mt-7 max-w-2xl text-sm leading-6 text-neutral-400">
            {result.recruiter_summary}
          </p>
        </div>

        <div className="card">
          <p className="eyebrow">ATS compatibility</p>
          <div className="mt-8">
            <div className="flex items-end justify-between">
              <span className="text-5xl font-semibold tracking-tight text-neutral-100">{result.ats_score}</span>
              <span className="mb-1 text-sm text-neutral-500">/ 100</span>
            </div>
            <div className="progress-track mt-5">
              <div className="progress-fill" style={{ width: `${result.ats_score}%` }} />
            </div>
          </div>
        </div>
      </div>

      <div className="mt-5 grid gap-5 lg:grid-cols-3">
        <div className="card lg:col-span-2 space-y-5">
          <p className="eyebrow">Score breakdown</p>
          <ScoreBar label="Semantic similarity" score={result.semantic_similarity} />
          <ScoreBar label="Keyword match" score={result.keyword_match} />
          <ScoreBar label="ATS signals" score={result.ats_score} />
        </div>
        <div className="card">
          <p className="eyebrow">Role detected</p>
          <p className="mt-5 text-xl font-medium text-neutral-100">{result.job_intelligence.role}</p>
          <p className="mt-2 text-sm text-neutral-500">{result.job_intelligence.experience_level}</p>
        </div>
      </div>

      <div className="mt-5 grid gap-5 md:grid-cols-2">
        <div className="card">
          <div className="mb-5 flex items-center justify-between">
            <h2 className="font-medium text-neutral-100">Skills matched</h2>
            <span className="text-xs text-neutral-600">{result.matched_skills.length}</span>
          </div>
          {result.matched_skills.length > 0 ? (
            <div className="flex flex-wrap gap-2">
              {result.matched_skills.map((skill) => (
                <span key={skill} className="badge badge-matched">{skill}</span>
              ))}
            </div>
          ) : (
            <p className="text-sm text-neutral-500">No overlapping skills detected.</p>
          )}
        </div>
        <div className="card">
          <div className="mb-5 flex items-center justify-between">
            <h2 className="font-medium text-neutral-100">Missing skills</h2>
            <span className="text-xs text-neutral-600">{result.missing_skills.length}</span>
          </div>
          {result.missing_skills.length > 0 ? (
            <div className="flex flex-wrap gap-2">
              {result.missing_skills.map((skill) => (
                <span key={skill} className="badge badge-missing">{skill}</span>
              ))}
            </div>
          ) : (
            <p className="text-sm text-neutral-500">No missing skills detected.</p>
          )}
        </div>
      </div>

      <div className="mt-5 grid gap-5 lg:grid-cols-2">
        <WhyThisScore data={result.score_explanation} />
        <div className="card">
          <div className="mb-5 flex items-center justify-between">
            <h2 className="font-medium text-neutral-100">Missing keywords</h2>
            <span className="text-xs text-neutral-600">{missingKeywords.length}</span>
          </div>
          {missingKeywords.length > 0 ? (
            <div className="flex flex-wrap gap-2">
              {missingKeywords.map((keyword) => (
                <span key={keyword} className="badge badge-missing">{keyword}</span>
              ))}
            </div>
          ) : (
            <p className="text-sm text-neutral-500">No key keyword gaps detected.</p>
          )}
        </div>
      </div>

      <div className="mt-5 grid gap-5 lg:grid-cols-2">
        <JobIntelligence data={result.job_intelligence} />
        <ResumeXRay items={result.resume_xray} />
      </div>

      <div className="mt-5 grid gap-5 lg:grid-cols-2">
        <ImproveResume suggestions={result.improvement_suggestions} />
        <div className="card">
          <h2 className="font-medium text-neutral-100">Recommendations</h2>
          <div className="mt-5 space-y-4">
            {result.recommendations.length > 0 ? result.recommendations.map((rec, i) => (
              <div key={i} className="flex gap-3 border-t border-white/[0.07] pt-4 first:border-t-0 first:pt-0">
                <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-neutral-400" />
                <p className="text-sm leading-6 text-neutral-400">{rec}</p>
              </div>
            )) : (
              <p className="text-sm text-neutral-500">No recommendations detected.</p>
            )}
          </div>
          {result.ats_issues.length > 0 && (
            <div className="mt-6 border-t border-white/[0.08] pt-5">
              <p className="eyebrow mb-4">ATS issues</p>
              <div className="space-y-3">
                {result.ats_issues.map((issue, i) => (
                  <p key={i} className="text-sm leading-6 text-neutral-500">{issue}</p>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="mt-8 flex justify-center">
        <button type="button" onClick={onReset} className="secondary-button">
          Analyze another resume
        </button>
      </div>
    </section>
  );
}
