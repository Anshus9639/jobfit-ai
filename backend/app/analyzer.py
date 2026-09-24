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
# Feature 1: "Why did I get this score?" explanation
# ---------------------------------------------------------------------------

_CLOUD_SKILLS = {"AWS", "Azure", "GCP"}


def generate_score_explanation(
    matched_skills: List[str],
    missing_skills: List[str],
    ats_issues: List[str],
    semantic_similarity: int,
    keyword_match: int,
    ats_score: int,
) -> Dict:
    """
    Build a plain-language explanation of the score, derived entirely from
    the actual analysis results (no hardcoded examples).
    """
    strengths: List[str] = []
    gaps: List[str] = []

    for skill in matched_skills[:4]:
        strengths.append(f"Strong {skill} alignment")

    if keyword_match >= 60:
        strengths.append("Good keyword coverage with the job description")
    if semantic_similarity >= 70:
        strengths.append("Strong overall alignment with the job description")
    if not any("projects section" in i.lower() for i in ats_issues):
        strengths.append("Relevant project experience detected")
    if not any("experience section" in i.lower() for i in ats_issues):
        strengths.append("Relevant work experience detected")
    if not strengths:
        strengths.append("Some baseline alignment with the job description")

    if any(skill in _CLOUD_SKILLS for skill in missing_skills):
        gaps.append("Limited cloud experience detected")
    for skill in missing_skills[:4]:
        gaps.append(f"{skill} not detected in resume")

    for issue in ats_issues:
        lower = issue.lower()
        if "measurable achievements" in lower:
            gaps.append("Resume lacks measurable achievements")
        elif "too short" in lower or "too long" in lower or "missing or unclear" in lower:
            gaps.append(issue)

    strengths = list(dict.fromkeys(strengths))[:6]
    gaps = list(dict.fromkeys(gaps))[:6]
    if not gaps:
        gaps.append("No major gaps detected")

    explanation = (
        f"This score combines three signals: semantic similarity ({semantic_similarity}%, "
        f"40% weight) measures how closely your resume's overall content matches the job "
        f"description's meaning; keyword match ({keyword_match}%, 40% weight) measures direct "
        f"overlap of technical skills; and ATS signals ({ats_score}%, 20% weight) measure resume "
        f"structure and formatting quality."
    )

    return {"strengths": strengths, "gaps": gaps, "explanation": explanation}


# ---------------------------------------------------------------------------
# Feature 2: Resume X-Ray
# ---------------------------------------------------------------------------

_CERTIFICATION_PATTERN = re.compile(r"\bcertifi(?:cation|ed|cate)s?\b", re.IGNORECASE)

_ACTION_VERBS = {
    "developed", "built", "designed", "implemented", "led", "managed", "created",
    "improved", "optimized", "engineered", "architected", "launched", "delivered",
    "automated", "streamlined", "reduced", "increased", "deployed", "maintained",
    "collaborated", "mentored", "resolved", "analyzed",
}

_WEAK_PHRASES = [
    "responsible for", "worked on", "helped with", "participated in",
    "involved in", "assisted with", "tasked with", "duties included",
]


def analyze_resume_xray(resume_text: str) -> List[Dict]:
    """
    Detect structural and quality signals in the resume text.
    Status is one of: 'detected', 'warning', 'missing'.
    """
    text_lower = resume_text.lower()
    items: List[Dict] = []

    def add(label: str, status: str, note: str = None):
        items.append({"label": label, "status": status, "note": note})

    add(
        "Contact Information",
        "detected" if _SECTION_PATTERNS["contact information"].search(resume_text) else "missing",
    )
    add("Skills Section", "detected" if _SECTION_PATTERNS["skills section"].search(resume_text) else "missing")
    add(
        "Experience Section",
        "detected" if _SECTION_PATTERNS["experience section"].search(resume_text) else "missing",
    )
    add("Projects Section", "detected" if _SECTION_PATTERNS["projects section"].search(resume_text) else "missing")
    add("Education Section", "detected" if _SECTION_PATTERNS["education section"].search(resume_text) else "missing")
    add(
        "Certifications",
        "detected" if _CERTIFICATION_PATTERN.search(resume_text) else "missing",
        note="Optional — not all roles require certifications" if not _CERTIFICATION_PATTERN.search(resume_text) else None,
    )

    tech_skills = extract_skills(resume_text)
    add(
        "Technical Skills",
        "detected" if tech_skills else "missing",
        note=f"{len(tech_skills)} detected" if tech_skills else None,
    )

    action_verb_count = sum(1 for verb in _ACTION_VERBS if re.search(rf"\b{verb}\b", text_lower))
    if action_verb_count >= 3:
        add("Action Verbs", "detected", note=f"{action_verb_count} strong action verbs found")
    elif action_verb_count > 0:
        add("Action Verbs", "warning", note="Only a few strong action verbs found")
    else:
        add("Action Verbs", "missing", note="Consider starting bullet points with strong action verbs")

    has_measurable = bool(_MEASURABLE_PATTERN.search(resume_text))
    add(
        "Measurable Achievements",
        "detected" if has_measurable else "warning",
        note=None if has_measurable else "Add numbers, percentages, or measurable outcomes",
    )

    weak_count = sum(1 for phrase in _WEAK_PHRASES if phrase in text_lower)
    add(
        "Achievement Statement Strength",
        "warning" if weak_count > 0 else "detected",
        note=f"{weak_count} generic phrase(s) detected (e.g. 'responsible for')" if weak_count > 0 else "Statements appear specific",
    )

    return items


# ---------------------------------------------------------------------------
# Feature 3: Job Description Intelligence
# ---------------------------------------------------------------------------

_ROLE_TITLES = [
    "Senior Software Engineer", "Software Engineer", "Full Stack Developer",
    "Full Stack Engineer", "Backend Developer", "Backend Engineer",
    "Frontend Developer", "Frontend Engineer", "Data Scientist", "Data Analyst",
    "Data Engineer", "Machine Learning Engineer", "ML Engineer", "DevOps Engineer",
    "Product Manager", "Mobile Developer", "QA Engineer", "Site Reliability Engineer",
    "Cloud Engineer", "Security Engineer",
]

_SECTION_HEADING_STOP = re.compile(r"^[A-Z][A-Za-z /]{2,40}:?$")
_EXPERIENCE_PATTERN = re.compile(r"(\d+)\s*\+?\s*(?:-|to)?\s*(\d+)?\s*\+?\s*years?", re.IGNORECASE)


def detect_role(jd_text: str) -> str:
    first_line = next((l.strip() for l in jd_text.splitlines() if l.strip()), "")
    for title in _ROLE_TITLES:
        if title.lower() in first_line.lower():
            return title
    for title in _ROLE_TITLES:
        if title.lower() in jd_text.lower():
            return title
    return "Not specified"


def _extract_section(jd_text: str, headings: List[str]) -> List[str]:
    """Extract bullet/line items following any of the given section headings."""
    lines = jd_text.splitlines()
    collecting = False
    items: List[str] = []
    heading_pattern = re.compile(
        r"^\s*(" + "|".join(re.escape(h) for h in headings) + r")\s*[:\-]?\s*$", re.IGNORECASE
    )

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if heading_pattern.match(stripped):
            collecting = True
            continue
        if collecting:
            if not stripped.startswith(("-", "*", "•")) and _SECTION_HEADING_STOP.match(stripped) and len(stripped.split()) <= 6:
                break
            cleaned = re.sub(r"^[-*•]\s*", "", stripped)
            items.append(cleaned)

    return items[:8]


def extract_responsibilities(jd_text: str) -> List[str]:
    return _extract_section(
        jd_text, ["responsibilities", "what you'll do", "key responsibilities", "role responsibilities"]
    )


def extract_requirements(jd_text: str) -> List[str]:
    return _extract_section(
        jd_text, ["requirements", "qualifications", "what we're looking for", "must have"]
    )


def detect_experience_level(jd_text: str) -> str:
    lower = jd_text.lower()
    match = _EXPERIENCE_PATTERN.search(jd_text)
    if match:
        low, high = match.group(1), match.group(2)
        return f"{low}-{high} years" if high else f"{low}+ years"
    if "entry level" in lower or "entry-level" in lower:
        return "Entry Level"
    if "junior" in lower:
        return "Junior"
    if "senior" in lower:
        return "Senior"
    return "Not specified"


def extract_important_keywords(jd_text: str, top_n: int = 10) -> List[str]:
    skills = extract_skills(jd_text)
    freq = [(skill, len(re.findall(re.escape(skill), jd_text, re.IGNORECASE))) for skill in skills]
    freq.sort(key=lambda x: -x[1])
    return [s for s, _ in freq[:top_n]]


def analyze_job_intelligence(jd_text: str) -> Dict:
    return {
        "role": detect_role(jd_text),
        "technical_skills": sorted(extract_skills(jd_text)),
        "responsibilities": extract_responsibilities(jd_text),
        "requirements": extract_requirements(jd_text),
        "experience_level": detect_experience_level(jd_text),
        "important_keywords": extract_important_keywords(jd_text),
    }


# ---------------------------------------------------------------------------
# Feature 4: Resume improvement / smart rewrite
# ---------------------------------------------------------------------------

_WEAK_VERB_MAP = {
    "responsible for": "Led",
    "worked on": "Contributed to",
    "helped with": "Supported",
    "participated in": "Collaborated on",
    "involved in": "Took part in",
    "assisted with": "Assisted in",
    "tasked with": "Owned",
    "duties included": "Delivered",
}


def _looks_like_bullet(line: str) -> bool:
    stripped = line.strip()
    return bool(stripped) and len(stripped.split()) >= 3


def find_weak_statements(resume_text: str) -> List[str]:
    lines = [l.strip() for l in resume_text.splitlines() if _looks_like_bullet(l)]
    weak = []
    for line in lines:
        lower = line.lower()
        # strip leading bullet punctuation only for the prefix check, keep `line` intact for display
        bare = re.sub(r"^[-*•]\s*", "", lower)
        if any(phrase in lower for phrase in _WEAK_VERB_MAP):
            weak.append(line)
        elif (
            len(line.split()) <= 8
            and not _MEASURABLE_PATTERN.search(line)
            and any(bare.startswith(v) for v in ("developed", "built", "created", "made", "did"))
        ):
            weak.append(line)
    return weak[:6]


def suggest_rewrite(line: str) -> Dict:
    """
    Rewrite using ONLY the resume's own wording (verb-phrase swap), or —
    when there isn't enough information to safely rewrite — return a
    recommendation instead of inventing content.
    """
    lower = line.lower()
    for phrase, replacement in _WEAK_VERB_MAP.items():
        if phrase in lower:
            idx = lower.find(phrase)
            rewritten = line[:idx] + replacement + " " + line[idx + len(phrase):].lstrip()
            return {
                "original": line,
                "suggestion": rewritten,
                "why": "Replaces generic/passive phrasing with a more active, ownership-focused verb, using only your original wording.",
                "type": "rewrite",
            }

    return {
        "original": line,
        "suggestion": None,
        "why": "Consider adding a measurable outcome (a number, percentage, or timeframe) if one applies, and briefly note the tools or approach you used.",
        "type": "recommendation",
    }


def generate_improvement_suggestions(resume_text: str) -> List[Dict]:
    return [suggest_rewrite(line) for line in find_weak_statements(resume_text)]


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
    semantic_similarity_int = int(round(semantic_similarity))
    keyword_match_int = int(round(keyword_match))
    ats_score_int = int(round(ats_score))

    recommendations = generate_recommendations(
        missing_skills, ats_issues, keyword_match, semantic_similarity
    )
    recruiter_summary = generate_recruiter_summary(overall_score, matched_skills, missing_skills)

    score_explanation = generate_score_explanation(
        matched_skills, missing_skills, ats_issues,
        semantic_similarity_int, keyword_match_int, ats_score_int,
    )
    resume_xray = analyze_resume_xray(resume_text)
    job_intelligence = analyze_job_intelligence(jd_text)
    improvement_suggestions = generate_improvement_suggestions(resume_text)

    return {
        "overall_score": int(overall_score),
        "semantic_similarity": semantic_similarity_int,
        "keyword_match": keyword_match_int,
        "ats_score": ats_score_int,
        "matched_skills": matched_skills,
        "missing_skills": missing_skills,
        "ats_issues": ats_issues,
        "recommendations": recommendations,
        "recruiter_summary": recruiter_summary,
        "score_explanation": score_explanation,
        "resume_xray": resume_xray,
        "job_intelligence": job_intelligence,
        "improvement_suggestions": improvement_suggestions,
    }