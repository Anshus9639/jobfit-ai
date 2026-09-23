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
}

export interface ApiError {
  detail: string;
}