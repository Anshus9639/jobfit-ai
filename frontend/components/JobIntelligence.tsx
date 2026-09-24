import { JobIntelligence as JobIntelligenceData } from "@/lib/types";

interface JobIntelligenceProps {
  data: JobIntelligenceData;
}

export default function JobIntelligence({ data }: JobIntelligenceProps) {
  return (
    <div className="card space-y-5">
      <div>
        <h2 className="font-semibold text-slate-800">Job Intelligence 🧠</h2>
        <p className="text-xs text-slate-400 mt-0.5">What we detected in the job description.</p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-400 mb-1">Role</p>
          <p className="text-sm text-slate-700">{data.role}</p>
        </div>
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-400 mb-1">
            Experience Level
          </p>
          <p className="text-sm text-slate-700">{data.experience_level}</p>
        </div>
      </div>

      {data.technical_skills.length > 0 && (
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-400 mb-2">
            Technical Skills
          </p>
          <div className="flex flex-wrap gap-2">
            {data.technical_skills.map((skill) => (
              <span
                key={skill}
                className="badge bg-brand-50 text-brand-700 border border-brand-100"
              >
                {skill}
              </span>
            ))}
          </div>
        </div>
      )}

      {data.important_keywords.length > 0 && (
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-400 mb-2">
            Important Keywords
          </p>
          <div className="flex flex-wrap gap-2">
            {data.important_keywords.map((kw) => (
              <span
                key={kw}
                className="badge bg-slate-100 text-slate-600 border border-slate-200"
              >
                {kw}
              </span>
            ))}
          </div>
        </div>
      )}

      {data.responsibilities.length > 0 && (
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-400 mb-2">
            Key Responsibilities
          </p>
          <ul className="space-y-1.5 list-disc list-inside marker:text-brand-400">
            {data.responsibilities.map((r, i) => (
              <li key={i} className="text-sm text-slate-600">
                {r}
              </li>
            ))}
          </ul>
        </div>
      )}

      {data.requirements.length > 0 && (
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-400 mb-2">
            Requirements
          </p>
          <ul className="space-y-1.5 list-disc list-inside marker:text-brand-400">
            {data.requirements.map((r, i) => (
              <li key={i} className="text-sm text-slate-600">
                {r}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}