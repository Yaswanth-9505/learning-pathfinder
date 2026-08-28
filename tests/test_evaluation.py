"""Recommendation-quality regression guards.

The rest of the suite proves the pipeline runs. This file proves it still
recommends *well*: if a change to tokenizing, field weights or the BM25
parameters quietly degrades ranking, these fail rather than the damage
surfacing only in a demo.

Thresholds sit below current measured performance, so they catch regressions
without failing on ordinary noise.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "eval"))

from engine.retrieval import CourseIndex  # noqa: E402
from eval.evaluate import (  # noqa: E402
    evaluate,
    rank_alphabetical,
    rank_bm25,
    rank_random,
    rank_title_match,
)

GOLDENS = Path(__file__).resolve().parent.parent / "eval" / "goldens.json"


@pytest.fixture(scope="module")
def index():
    return CourseIndex()


@pytest.fixture(scope="module")
def cases():
    return json.loads(GOLDENS.read_text(encoding="utf-8"))["queries"]


@pytest.fixture(scope="module")
def bm25(index, cases):
    summary, rows = evaluate(index, cases, rank_bm25, "bm25")
    return summary, rows


def test_golden_ids_all_exist_in_catalog(index, cases):
    known = set(index.by_id)
    for case in cases:
        unknown = set(case["relevant"]) - known
        assert not unknown, "%s references unknown ids %s" % (case["goal"], unknown)


def test_recall_at_shortlist_size_is_high(bm25):
    """16 is the shortlist the LLM sees; it caps what any path can contain."""
    summary, _ = bm25
    assert summary["R@16"] >= 0.85, "Recall@16 dropped to %.3f" % summary["R@16"]


def test_first_result_is_always_relevant(bm25):
    summary, _ = bm25
    assert summary["MRR"] >= 0.95, "MRR dropped to %.3f" % summary["MRR"]


def test_shortlist_covers_the_target_role_skills(bm25):
    """The product metric: a path cannot close a gap the shortlist misses."""
    summary, _ = bm25
    assert summary["SkillCov@16"] >= 0.90, \
        "skill coverage dropped to %.3f" % summary["SkillCov@16"]


def test_ranking_quality_beats_naive_baselines(index, cases, bm25):
    summary, _ = bm25
    title, _ = evaluate(index, cases, rank_title_match, "title")
    alpha, _ = evaluate(index, cases, rank_alphabetical, "alpha")

    assert summary["R@16"] > title["R@16"] * 1.5
    assert summary["nDCG@10"] > title["nDCG@10"] * 1.5
    assert summary["R@16"] > alpha["R@16"] * 2


def test_ranking_clears_the_random_floor(index, cases, bm25):
    summary, _ = bm25
    floors = [
        evaluate(index, cases, lambda i, c, s=s: rank_random(i, c, s), "rand")[0]
        for s in (0, 1, 2)
    ]
    mean_floor = sum(f["R@16"] for f in floors) / len(floors)
    assert summary["R@16"] > mean_floor * 2.5


def test_no_single_goal_is_badly_served(bm25):
    """An average can hide one catastrophic query."""
    _, rows = bm25
    worst = min(rows, key=lambda r: r["R@16"])
    assert worst["R@16"] >= 0.6, \
        "'%s' only reached Recall@16 %.3f" % (worst["goal"], worst["R@16"])


def test_learning_style_changes_the_ranking(index):
    """Regression: style used to be captured but never reach retrieval."""
    base = {"goals": "become a backend engineer", "interests": ""}
    hands_on = index.search(
        index.build_query(dict(base, learning_style="hands-on")), top_k=16
    )
    video = index.search(
        index.build_query(dict(base, learning_style="video")), top_k=16
    )
    assert [c["id"] for c in hands_on] != [c["id"] for c in video]


def test_role_matching_disambiguates_the_data_roles(index):
    """'data' is shared by three roles; matching must not bind by list order."""
    assert index.match_role("data analyst job")["id"] == "data-analyst"
    assert index.match_role("become a data scientist")["id"] == "data-scientist"
    assert index.match_role("data engineer role")["id"] == "data-engineer"
