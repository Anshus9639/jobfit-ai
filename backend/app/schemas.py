"""
schemas.py
Pydantic models for request/response validation.
"""

from typing import List, Optional
from pydantic import BaseModel


class ScoreExplanation(BaseModel):
    strengths: List[str]
    gaps: List[str]
    explanation: str


class ResumeXRayItem(BaseModel):
    label: str
    status: str  # "detected" | "warning" | "missing"
    note: Optional[str] = None


class JobIntelligence(BaseModel):
    role: str
    technical_skills: List[str]
    responsibilities: List[str]
    requirements: List[str]
    experience_level: str
    important_keywords: List[str]


class ImprovementSuggestion(BaseModel):
    original: str
    suggestion: Optional[str] = None
    why: str
    type: str  # "rewrite" | "recommendation"


class AnalyzeResponse(BaseModel):
    overall_score: int
    semantic_similarity: int
    keyword_match: int
    ats_score: int
    matched_skills: List[str]
    missing_skills: List[str]
    ats_issues: List[str]
    recommendations: List[str]
    recruiter_summary: str
    score_explanation: ScoreExplanation
    resume_xray: List[ResumeXRayItem]
    job_intelligence: JobIntelligence
    improvement_suggestions: List[ImprovementSuggestion]


class ErrorResponse(BaseModel):
    detail: str