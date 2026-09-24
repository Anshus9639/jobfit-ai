export interface ScoreExplanation {
  strengths: string[];
  gaps: string[];
  explanation: string;
}

export type XRayStatus = "detected" | "warning" | "missing";

export interface ResumeXRayItem {
  label: string;
  status: XRayStatus;
  note?: string | null;
}

export interface JobIntelligence {
  role: string;
  technical_skills: string[];
  responsibilities: string[];
  requirements: string[];
  experience_level: string;
  important_keywords: string[];
}

export interface ImprovementSuggestion {
  original: string;
  suggestion?: string | null;
  why: string;
  type: "rewrite" | "recommendation";
}

export interface AnalyzeResult {
  overall_score: number;
  semantic_similarity: number;
  keyword_match: number;
  ats_score: number;
  matched_skills: string[];
  missing_skills: string[];
  ats_issues: string[];
  recommendations: string[];
  recruiter_summary: string;
  score_explanation: ScoreExplanation;
  resume_xray: ResumeXRayItem[];
  job_intelligence: JobIntelligence;
  improvement_suggestions: ImprovementSuggestion[];
}

export interface ApiError {
  detail: string;
}