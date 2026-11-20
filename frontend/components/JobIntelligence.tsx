import { JobIntelligence as JobIntelligenceData } from "@/lib/types";

interface JobIntelligenceProps {
  data: JobIntelligenceData;
}

export default function JobIntelligence({ data }: JobIntelligenceProps) {
  return (
    <div className="card space-y-6">
      <div>
        <h2 className="font-medium text-neutral-100">Job intelligence</h2>
        <p className="mt-1 text-xs text-neutral-500">Detected from the job description.</p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div>
          <p className="eyebrow mb-2">Role</p>
          <p className="text-sm text-neutral-300">{data.role}</p>
        </div>
        <div>
          <p className="eyebrow mb-2">
            Experience Level
          </p>
          <p className="text-sm text-neutral-300">{data.experience_level}</p>
        </div>
      </div>

      {data.technical_skills.length > 0 && (
        <div>
          <p className="eyebrow mb-3">
            Technical Skills
          </p>
          <div className="flex flex-wrap gap-2">
            {data.technical_skills.map((skill) => (
              <span
                key={skill}
                className="badge"
              >
                {skill}
              </span>
            ))}
          </div>
        </div>
      )}

      {data.important_keywords.length > 0 && (
        <div>
          <p className="eyebrow mb-3">
            Important Keywords
          </p>
          <div className="flex flex-wrap gap-2">
            {data.important_keywords.map((kw) => (
              <span key={kw} className="badge badge-missing">
                {kw}
              </span>
            ))}
          </div>
        </div>
      )}

      {data.responsibilities.length > 0 && (
        <div>
          <p className="eyebrow mb-3">
            Key Responsibilities
          </p>
          <ul className="space-y-2">
            {data.responsibilities.map((r, i) => (
              <li key={i} className="border-t border-white/[0.07] pt-2 text-sm leading-6 text-neutral-400 first:border-t-0 first:pt-0">
                {r}
              </li>
            ))}
          </ul>
        </div>
      )}

      {data.requirements.length > 0 && (
        <div>
          <p className="eyebrow mb-3">
            Requirements
          </p>
          <ul className="space-y-2">
            {data.requirements.map((r, i) => (
              <li key={i} className="border-t border-white/[0.07] pt-2 text-sm leading-6 text-neutral-400 first:border-t-0 first:pt-0">
                {r}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}