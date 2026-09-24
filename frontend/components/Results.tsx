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

function scoreColor(score: number) {
  if (score >= 75) return "text-emerald-600";
  if (score >= 50) return "text-amber-600";
  return "text-red-600";
}

function fillColor(score: number) {
  if (score >= 75) return "bg-emerald-500";
  if (score >= 50) return "bg-amber-500";
  return "bg-red-500";
}

function ScoreBar({ label, score }: { label: string; score: number }) {
  return (
    <div>
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-sm font-medium text-slate-600">{label}</span>
        <span className={`text-sm font-semibold ${scoreColor(score)}`}>{score}%</span>
      </div>
      <div className="progress-track">
        <div
          className={`progress-fill ${fillColor(score)}`}
          style={{ width: `${score}%` }}
        />
      </div>
    </div>
  );
}

export default function Results({ result, onReset }: ResultsProps) {
  return (
    <div className="space-y-6">
      {/* Overall Match */}
      <div className="card text-center">
        <p className="text-sm font-medium text-slate-500 uppercase tracking-wide">
          Overall Match
        </p>
        <p className={`text-6xl font-bold mt-2 ${scoreColor(result.overall_score)}`}>
          {result.overall_score}%
        </p>
        <p className="text-slate-600 mt-4 max-w-2xl mx-auto">{result.recruiter_summary}</p>
      </div>

      {/* Why did I get this score? */}
      <WhyThisScore data={result.score_explanation} />

      {/* Score Breakdown */}
      <div className="card space-y-5">
        <h2 className="font-semibold text-slate-800">Score Breakdown</h2>
        <ScoreBar label="Semantic Similarity" score={result.semantic_similarity} />
        <ScoreBar label="Keyword Match" score={result.keyword_match} />
        <ScoreBar label="ATS Signals" score={result.ats_score} />
      </div>

      {/* Job Intelligence */}
      <JobIntelligence data={result.job_intelligence} />

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Matched Skills */}
        <div className="card">
          <h2 className="font-semibold text-slate-800 mb-4">
            Matched Skills{" "}
            <span className="text-slate-400 font-normal">
              ({result.matched_skills.length})
            </span>
          </h2>
          {result.matched_skills.length > 0 ? (
            <div className="flex flex-wrap gap-2">
              {result.matched_skills.map((skill) => (
                <span key={skill} className="badge badge-matched">
                  {skill}
                </span>
              ))}
            </div>
          ) : (
            <p className="text-sm text-slate-400">No overlapping skills detected.</p>
          )}
        </div>

        {/* Missing Skills */}
        <div className="card">
          <h2 className="font-semibold text-slate-800 mb-4">
            Missing Skills{" "}
            <span className="text-slate-400 font-normal">
              ({result.missing_skills.length})
            </span>
          </h2>
          {result.missing_skills.length > 0 ? (
            <div className="flex flex-wrap gap-2">
              {result.missing_skills.map((skill) => (
                <span key={skill} className="badge badge-missing">
                  {skill}
                </span>
              ))}
            </div>
          ) : (
            <p className="text-sm text-slate-400">No missing skills detected. Nice work.</p>
          )}
        </div>
      </div>

      {/* Resume X-Ray */}
      <ResumeXRay items={result.resume_xray} />

      {/* Improve Your Resume */}
      <ImproveResume suggestions={result.improvement_suggestions} />

      {/* ATS Issues */}
      <div className="card">
        <h2 className="font-semibold text-slate-800 mb-4">ATS Issues</h2>
        {result.ats_issues.length > 0 ? (
          <ul className="space-y-2">
            {result.ats_issues.map((issue, i) => (
              <li key={i} className="flex items-start gap-2 text-sm text-slate-600">
                <span className="mt-1.5 h-1.5 w-1.5 rounded-full bg-amber-500 shrink-0" />
                {issue}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-slate-400">No ATS-style issues detected.</p>
        )}
      </div>

      {/* Recommendations */}
      <div className="card">
        <h2 className="font-semibold text-slate-800 mb-4">Recommendations</h2>
        <ul className="space-y-2">
          {result.recommendations.map((rec, i) => (
            <li key={i} className="flex items-start gap-2 text-sm text-slate-600">
              <span className="mt-1.5 h-1.5 w-1.5 rounded-full bg-brand-500 shrink-0" />
              {rec}
            </li>
          ))}
        </ul>
      </div>

      <div className="text-center">
        <button
          onClick={onReset}
          className="text-sm font-medium text-brand-600 hover:text-brand-700 underline underline-offset-4"
        >
          Analyze another resume
        </button>
      </div>
    </div>
  );
}
