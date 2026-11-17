import pytest

from app import config
from app.analyzer import (
    analyze_ats,
    build_analysis,
    combine_scores,
    compute_keyword_match,
    compute_semantic_similarity,
    cosine_similarity,
)
from app.embeddings import EmbeddingProviderError
from tests.conftest import JD_TEXT, RESUME_TEXT


def test_weights_are_exactly_40_40_20():
    assert combine_scores(100, 0, 0) == 40
    assert combine_scores(0, 100, 0) == 40
    assert combine_scores(0, 0, 100) == 20
    assert combine_scores(50, 50, 50) == 50
    assert combine_scores(66.7, 33.3, 50.0) == int(round(0.4 * 66.7 + 0.4 * 33.3 + 0.2 * 50.0))


def test_cosine_similarity_basics():
    assert cosine_similarity([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == pytest.approx(1.0)
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    assert cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0
    with pytest.raises(ValueError):
        cosine_similarity([1.0], [1.0, 2.0])


def test_overall_score_matches_formula_from_raw_components():
    semantic = 66.7
    keyword, _matched, missing = compute_keyword_match(RESUME_TEXT, JD_TEXT)
    ats, _issues = analyze_ats(RESUME_TEXT, JD_TEXT, missing)

    result = build_analysis(RESUME_TEXT, JD_TEXT, semantic)

    assert result["semantic_similarity"] == 67
    assert result["overall_score"] == combine_scores(semantic, keyword, ats)
    assert result["overall_score"] == int(round(0.4 * semantic + 0.4 * keyword + 0.2 * ats))


def test_analysis_is_deterministic():
    first = build_analysis(RESUME_TEXT, JD_TEXT, 71.3)
    second = build_analysis(RESUME_TEXT, JD_TEXT, 71.3)
    assert first == second


def test_existing_features_are_preserved():
    result = build_analysis(RESUME_TEXT, JD_TEXT, 80.0)

    assert "Python" in result["matched_skills"]
    assert "Docker" in result["matched_skills"]
    assert "AWS" in result["missing_skills"]
    assert result["keyword_match"] == 75
    assert result["ats_issues"]

    labels = {item["label"] for item in result["resume_xray"]}
    assert {"Contact Information", "Technical Skills", "Action Verbs"} <= labels
    assert {"detected", "warning", "missing"} >= {item["status"] for item in result["resume_xray"]}

    intelligence = result["job_intelligence"]
    assert set(intelligence) == {
        "role",
        "technical_skills",
        "responsibilities",
        "requirements",
        "experience_level",
        "important_keywords",
    }
    assert intelligence["role"] == "Software Engineer"
    assert "AWS" in intelligence["technical_skills"]
    assert result["recommendations"]
    assert result["recruiter_summary"]
    assert result["score_explanation"]["explanation"]
    assert isinstance(result["improvement_suggestions"], list)


@pytest.mark.anyio
async def test_semantic_score_is_clamped_to_zero_100():
    class Provider:
        name = "test"

        def __init__(self, vectors):
            self.vectors = vectors

        async def embed(self, texts):
            return self.vectors

        async def aclose(self):
            return None

    identical = await compute_semantic_similarity("a", "b", Provider([[1.0, 0.0], [2.0, 0.0]]))
    opposite = await compute_semantic_similarity("a", "b", Provider([[1.0, 0.0], [-1.0, 0.0]]))
    orthogonal = await compute_semantic_similarity("a", "b", Provider([[1.0, 0.0], [0.0, 1.0]]))

    assert identical == 100.0
    assert opposite == 0.0
    assert orthogonal == 0.0


@pytest.mark.anyio
async def test_semantic_failure_is_not_replaced_with_a_score():
    class FailingProvider:
        name = "test"

        async def embed(self, texts):
            raise EmbeddingProviderError("provider down")

        async def aclose(self):
            return None

    with pytest.raises(EmbeddingProviderError):
        await compute_semantic_similarity("a", "b", FailingProvider())


@pytest.mark.anyio
async def test_embedding_inputs_are_bounded(monkeypatch):
    recorded = {}

    class RecordingProvider:
        name = "test"

        async def embed(self, texts):
            recorded["texts"] = list(texts)
            return [[1.0, 0.0], [1.0, 0.0]]

        async def aclose(self):
            return None

    monkeypatch.setattr(config.settings, "max_embedding_input_chars", 50)
    await compute_semantic_similarity("r" * 500, "j" * 500, RecordingProvider())

    assert [len(text) for text in recorded["texts"]] == [50, 50]
