"""
schemas.py
Pydantic models for request/response validation.
"""

from typing import List
from pydantic import BaseModel


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


class ErrorResponse(BaseModel):
    detail: str