"""
skills.py
Skills dictionary + normalization + extraction utilities.
"""

import re
from typing import List, Set

# Canonical skill list (the "display" names we standardize to)
SKILLS_CANONICAL = [
    "Python", "Java", "JavaScript", "TypeScript", "SQL", "C++", "C#", "Go",
    "React", "Next.js", "Node.js", "Express.js", "FastAPI", "Flask", "Django",
    "REST", "GraphQL", "Docker", "Kubernetes", "AWS", "Azure", "GCP",
    "PostgreSQL", "MySQL", "MongoDB", "Redis", "Git", "GitHub", "GitLab",
    "CI/CD", "Machine Learning", "Deep Learning", "NLP", "Computer Vision",
    "TensorFlow", "PyTorch", "Pandas", "NumPy", "Scikit-learn", "HTML",
    "CSS", "Tailwind CSS", "Bootstrap", "Redux", "Vue.js", "Angular",
    "Linux", "Agile", "Scrum", "Microservices", "Jenkins", "Terraform",
    "Data Structures", "Algorithms", "OOP", "System Design", "Testing",
    "Jest", "Pytest", "GraphAPI", "Firebase", "Supabase",
]

# Map of common variants/aliases -> canonical name.
# Keys are lowercase, punctuation/space-stripped for matching robustness.
_ALIASES = {
    "reactjs": "React",
    "react.js": "React",
    "nextjs": "Next.js",
    "next js": "Next.js",
    "nodejs": "Node.js",
    "node js": "Node.js",
    "expressjs": "Express.js",
    "express js": "Express.js",
    "postgres": "PostgreSQL",
    "postgressql": "PostgreSQL",
    "ml": "Machine Learning",
    "dl": "Deep Learning",
    "nlp": "NLP",
    "js": "JavaScript",
    "ts": "TypeScript",
    "cpp": "C++",
    "c plus plus": "C++",
    "csharp": "C#",
    "c sharp": "C#",
    "tailwind": "Tailwind CSS",
    "tailwindcss": "Tailwind CSS",
    "vuejs": "Vue.js",
    "vue js": "Vue.js",
    "k8s": "Kubernetes",
    "gcp": "GCP",
    "google cloud": "GCP",
    "amazon web services": "AWS",
    "microsoft azure": "Azure",
    "mongo": "MongoDB",
    "mongodb": "MongoDB",
    "mysql": "MySQL",
    "sklearn": "Scikit-learn",
    "scikit learn": "Scikit-learn",
    "tensorflow": "TensorFlow",
    "pytorch": "PyTorch",
    "numpy": "NumPy",
    "pandas": "Pandas",
    "restapi": "REST",
    "rest api": "REST",
    "rest apis": "REST",
    "graphql": "GraphQL",
    "cicd": "CI/CD",
    "ci cd": "CI/CD",
    "html5": "HTML",
    "css3": "CSS",
    "oop": "OOP",
    "object oriented programming": "OOP",
}


def _normalize_key(text: str) -> str:
    """Lowercase and strip non-alphanumeric characters for alias matching."""
    return re.sub(r"[^a-z0-9+#. ]", "", text.lower()).strip()


def normalize_skill(raw: str) -> str:
    """Return the canonical form of a raw skill string, if recognized."""
    key = _normalize_key(raw)
    key_compact = key.replace(" ", "")

    if key in _ALIASES:
        return _ALIASES[key]
    if key_compact in {_normalize_key(k).replace(" ", "") for k in _ALIASES}:
        for alias_key, canon in _ALIASES.items():
            if _normalize_key(alias_key).replace(" ", "") == key_compact:
                return canon

    for canon in SKILLS_CANONICAL:
        if _normalize_key(canon) == key or _normalize_key(canon).replace(" ", "") == key_compact:
            return canon

    return raw.strip()


def _build_search_patterns():
    """
    Build a list of (pattern, canonical_name) tuples for skill extraction.
    Longer / more specific terms are ordered first to avoid partial-match issues.
    """
    terms = {}
    for canon in SKILLS_CANONICAL:
        terms[canon.lower()] = canon
    for alias, canon in _ALIASES.items():
        terms[alias.lower()] = canon

    # Sort by length descending so multi-word terms match before short ones
    sorted_terms = sorted(terms.items(), key=lambda x: -len(x[0]))

    patterns = []
    for term, canon in sorted_terms:
        escaped = re.escape(term)
        # Allow flexible whitespace/punctuation in multi-word terms
        escaped = escaped.replace(r"\ ", r"[\s\-]+")
        pattern = re.compile(r"(?<![a-zA-Z0-9])" + escaped + r"(?![a-zA-Z0-9])", re.IGNORECASE)
        patterns.append((pattern, canon))
    return patterns


_SEARCH_PATTERNS = _build_search_patterns()


def extract_skills(text: str) -> Set[str]:
    """Extract a set of canonical skill names found in the given text."""
    found: Set[str] = set()
    if not text:
        return found

    for pattern, canon in _SEARCH_PATTERNS:
        if pattern.search(text):
            found.add(canon)

    return found


def extract_skills_list(text: str) -> List[str]:
    return sorted(extract_skills(text))