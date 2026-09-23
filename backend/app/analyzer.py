"""
analyzer.py
Core resume-vs-job-description analysis engine.

Scoring formula:
    overall_score = 0.4 * semantic_similarity
                  + 0.4 * keyword_match
                  + 0.2 * ats_score

The sentence-transformer model is loaded once at module import time
(via get_model()) and reused across requests.
"""

import re
from functools import lru_cache
from typing import Dict, List, Tuple

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity as sk_cosine_similarity

from .skills import extract_skills

MODEL_NAME = "all-MiniLM-L6-v2"

_model = None


def get_model():
    """Lazily load and cache the SentenceTransformer model (singleton)."""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(MODEL_NAME)
    return _model


def compute_semantic_similarity(resume_text: str, jd_text: str) -> float:
    """
    Cosine similarity between sentence-transformer embeddings of the
    resume and job description. Returns a 0-100 score.
    """
    model = get_model()
    embeddings = model.encode([resume_text, jd_text])
    sim = sk_cosine_similarity([embeddings[0]], [embeddings[1]])[0][0]
    # Clamp and scale to 0-100
    sim = max(0.0, min(1.0, float(sim)))
    return round(sim * 100, 1)


def compute_tfidf_similarity(resume_text: str, jd_text: str) -> float:
    """
    Fallback / supplementary TF-IDF cosine similarity, 0-100 score.
    Not used in the final weighted score by default, but exposed for
    diagnostics or future use.
    """
    try:
        vectorizer = TfidfVectorizer(stop_words="english")
        tfidf = vectorizer.fit_transform([resume_text, jd_text])
        sim = sk_cosine_similarity(tfidf[0:1], tfidf[1:2])[0][0]
        return round(max(0.0, min(1.0, float(sim))) * 100, 1)
    except ValueError:
        return 0.0


def compute_keyword_match(resume_text: str, jd_text: str) -> Tuple[float, List[str], List[str]]:
    """
    Extract canonical skills from both texts and compute overlap.
    Returns (score_0_100, matched_skills, missing_skills).
    """
    resume_skills = extract_skills(resume_text)
    jd_skills = extract_skills(jd_text)

    if not jd_skills:
        # No recognizable skills in JD -> can't meaningfully score keyword match
        return 0.0, sorted(resume_skills), []

    matched = jd_skills & resume_skills
    missing = jd_skills - resume_skills

    score = round((len(matched) / len(jd_skills)) * 100, 1)
    return score, sorted(matched), sorted(missing)


# ---------------------------------------------------------------------------
# ATS-style analysis (heuristic, not a real ATS)
# ---------------------------------------------------------------------------

_SECTION_PATTERNS = {
    "contact information": re.compile(
        r"(\+?\d[\d\-\s]{7,}\d)|([\w.\-]+@[\w\-]+\.[a-zA-Z]{2,})", re.IGNORECASE
    ),
    "skills section": re.compile(r"\bskills\b", re.IGNORECASE),
    "experience section": re.compile(
        r"\b(experience|work history|employment)\b", re.IGNORECASE
    ),
    "education section": re.compile(r"\beducation\b", re.IGNORECASE),
    "projects section": re.compile(r"\bprojects?\b", re.IGNORECASE),
}

_MEASURABLE_PATTERN = re.compile(
    r"(\d+%|\$\d+|\b\d+[kK]\b|\bincreased\b|\breduced\b|\bimproved\b|\bgrew\b|\bsaved\b)",
    re.IGNORECASE,
)


def analyze_ats(resume_text: str, jd_text: str, missing_skills: List[str]) -> Tuple[float, List[str]]:
    """
    Heuristic ATS-style checks. Returns (score_0_100, list_of_issues).
    Deducts points for missing structural sections, poor length, no
    measurable achievements, and uncovered JD keywords.
    """
    issues: List[str] = []
    checks_passed = 0
    total_checks = 0

    for label, pattern in _SECTION_PATTERNS.items():
        total_checks += 1
        if pattern.search(resume_text):
            checks_passed += 1
        else:
            issues.append(f"Missing or unclear {label}")

    # Resume length check (rough heuristic: word count)
    total_checks += 1
    word_count = len(resume_text.split())
    if 250 <= word_count <= 1200:
        checks_passed += 1
    elif word_count < 250:
        issues.append("Resume appears too short — add more detail on experience and projects")
    else:
        issues.append("Resume appears too long — consider tightening to 1-2 pages")

    # Measurable achievements check
    total_checks += 1
    if _MEASURABLE_PATTERN.search(resume_text):
        checks_passed += 1
    else:
        issues.append("Missing measurable achievements (numbers, %, impact)")

    # Keyword coverage relative to JD
    total_checks += 1
    if len(missing_skills) == 0:
        checks_passed += 1
    elif len(missing_skills) <= 3:
        checks_passed += 0.5
        issues.append(f"Some important JD terms are missing: {', '.join(missing_skills[:3])}")
    else:
        issues.append(
            f"Several important JD terms are missing: {', '.join(missing_skills[:5])}"
            + (" and more" if len(missing_skills) > 5 else "")
        )

    score = round((checks_passed / total_checks) * 100, 1)
    return score, issues


# ---------------------------------------------------------------------------
# Recommendations + recruiter summary
# ---------------------------------------------------------------------------

def generate_recommendations(
    missing_skills: List[str], ats_issues: List[str], keyword_match: float, semantic_similarity: float
) -> List[str]:
    recs: List[str] = []

    if missing_skills:
        top_missing = ", ".join(missing_skills[:5])
        recs.append(f"Add or highlight experience with: {top_missing}")

    if any("measurable achievements" in issue for issue in ats_issues):
        recs.append("Quantify achievements with numbers, percentages, or measurable outcomes")

    if any("skills section" in issue for issue in ats_issues):
        recs.append("Add a dedicated Skills section listing your key technologies")

    if any("too short" in issue for issue in ats_issues):
        recs.append("Expand on project details, responsibilities, and outcomes")

    if any("too long" in issue for issue in ats_issues):
        recs.append("Trim the resume to focus on the most relevant, recent experience")

    if keyword_match < 50:
        recs.append("Mirror more of the job description's terminology in your resume")

    if semantic_similarity < 50:
        recs.append("Reframe your summary/experience to more closely match the role's focus")

    if not recs:
        recs.append("Resume is well-aligned with this job description — minor polish only")

    return recs


def generate_recruiter_summary(overall_score: float, matched: List[str], missing: List[str]) -> str:
    if overall_score >= 80:
        tone = "a strong match"
    elif overall_score >= 60:
        tone = "a reasonable match with some gaps"
    elif overall_score >= 40:
        tone = "a partial match with notable gaps"
    else:
        tone = "a weak match for this role"

    matched_str = ", ".join(matched[:5]) if matched else "few overlapping skills"
    missing_str = ", ".join(missing[:5]) if missing else "no major gaps"

    return (
        f"This resume shows {tone} for the job description, scoring {overall_score}/100 overall. "
        f"Strong overlap in: {matched_str}. Key gaps to address: {missing_str}."
    )


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def run_analysis(resume_text: str, jd_text: str) -> Dict:
    semantic_similarity = compute_semantic_similarity(resume_text, jd_text)
    keyword_match, matched_skills, missing_skills = compute_keyword_match(resume_text, jd_text)
    ats_score, ats_issues = analyze_ats(resume_text, jd_text, missing_skills)

    overall_score = round(
        0.4 * semantic_similarity + 0.4 * keyword_match + 0.2 * ats_score
    )

    recommendations = generate_recommendations(
        missing_skills, ats_issues, keyword_match, semantic_similarity
    )
    recruiter_summary = generate_recruiter_summary(overall_score, matched_skills, missing_skills)

    return {
        "overall_score": int(overall_score),
        "semantic_similarity": int(round(semantic_similarity)),
        "keyword_match": int(round(keyword_match)),
        "ats_score": int(round(ats_score)),
        "matched_skills": matched_skills,
        "missing_skills": missing_skills,
        "ats_issues": ats_issues,
        "recommendations": recommendations,
        "recruiter_summary": recruiter_summary,
    }