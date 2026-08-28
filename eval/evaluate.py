"""Offline evaluation of the retrieval stage.

Answers the question the architecture write-up cannot: does BM25 retrieval
actually surface the right courses, and does it beat the obvious alternatives?

Runs with no API key and no network - it evaluates the deterministic half of
the pipeline, which is the half that decides what the LLM is even allowed to
choose from. If recall here is poor, no amount of prompt quality recovers it.

Metrics
    Recall@k     share of relevant courses present in the top k
    Precision@k  share of the top k that are relevant
    MRR          1 / rank of the first relevant result
    nDCG@k       rank-weighted gain, so being right at rank 1 beats rank 10
    SkillCov@k   share of the target role's required skills the shortlist
                 covers - the product metric, since a path can only close a
                 gap the shortlist contains

Baselines
    random       mean over several seeds, the floor any method must clear
    alpha        catalog order, ignoring the query entirely
    title-match  counts query tokens appearing in the title only

Usage
    python eval/evaluate.py            # summary table
    python eval/evaluate.py --detail   # adds per-query rows
"""

import argparse
import json
import math
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.retrieval import CourseIndex, tokenize  # noqa: E402

GOLDENS = Path(__file__).resolve().parent / "goldens.json"
CUTOFFS = (5, 10, 16)          # 16 = MAX_CANDIDATES, the real shortlist size
RANDOM_SEEDS = (0, 1, 2, 3, 4)


# -- metrics ----------------------------------------------------------------

def recall_at_k(ranked, relevant, k):
    if not relevant:
        return None
    return len(set(ranked[:k]) & relevant) / len(relevant)


def precision_at_k(ranked, relevant, k):
    if not k:
        return None
    return len(set(ranked[:k]) & relevant) / k


def mrr(ranked, relevant):
    for i, cid in enumerate(ranked, start=1):
        if cid in relevant:
            return 1.0 / i
    return 0.0


def ndcg_at_k(ranked, relevant, k):
    """Binary-gain nDCG: log-discounted, normalised by the ideal ordering."""
    if not relevant:
        return None
    dcg = sum(
        1.0 / math.log2(i + 1)
        for i, cid in enumerate(ranked[:k], start=1)
        if cid in relevant
    )
    ideal = sum(1.0 / math.log2(i + 1)
                for i in range(1, min(len(relevant), k) + 1))
    return dcg / ideal if ideal else None


def skill_coverage(index, ranked, target_skills, k):
    """Share of the role's required skills taught by the top k courses."""
    if not target_skills:
        return None
    taught = set()
    for cid in ranked[:k]:
        course = index.by_id.get(cid)
        if course:
            taught.update(course["skills"])
    return len(set(target_skills) & taught) / len(target_skills)


# -- ranking strategies -----------------------------------------------------

def rank_bm25(index, query_case):
    profile = {
        "goals": query_case["goal"],
        "interests": "",
        "learning_style": query_case.get("learning_style", ""),
    }
    query = index.build_query(profile)
    results = index.search(query, top_k=len(index.courses),
                           level=query_case.get("level"))
    return [c["id"] for c in results]


def rank_random(index, query_case, seed=0):
    ids = [c["id"] for c in index.courses]
    random.Random(seed).shuffle(ids)
    return ids


def rank_alphabetical(index, query_case):
    return [c["id"] for c in index.courses]


def rank_title_match(index, query_case):
    """Naive lexical baseline: count query tokens appearing in the title."""
    q = set(tokenize(query_case["goal"]))
    scored = []
    for c in index.courses:
        hits = len(q & set(tokenize(c["title"])))
        scored.append((hits, c["id"]))
    scored.sort(key=lambda p: p[0], reverse=True)
    return [cid for _, cid in scored]


# -- harness ----------------------------------------------------------------

def evaluate(index, cases, ranker, label):
    rows = []
    for case in cases:
        relevant = set(case["relevant"])
        missing = [cid for cid in relevant if cid not in index.by_id]
        if missing:
            raise SystemExit(
                "goldens.json references unknown course ids: %s" % missing
            )

        ranked = ranker(index, case)
        role = index.match_role(case["goal"])
        target_skills = role["skills"] if role else []

        row = {"goal": case["goal"], "n_relevant": len(relevant)}
        for k in CUTOFFS:
            row["R@%d" % k] = recall_at_k(ranked, relevant, k)
            row["P@%d" % k] = precision_at_k(ranked, relevant, k)
            row["nDCG@%d" % k] = ndcg_at_k(ranked, relevant, k)
        row["MRR"] = mrr(ranked, relevant)
        row["SkillCov@16"] = skill_coverage(index, ranked, target_skills, 16)
        rows.append(row)

    summary = {"method": label}
    for metric in rows[0]:
        if metric in ("goal", "n_relevant"):
            continue
        values = [r[metric] for r in rows if r[metric] is not None]
        summary[metric] = sum(values) / len(values) if values else None
    return summary, rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--detail", action="store_true",
                    help="print per-query rows for the BM25 ranker")
    args = ap.parse_args()

    index = CourseIndex()
    cases = json.loads(GOLDENS.read_text(encoding="utf-8"))["queries"]

    print("Retrieval evaluation")
    print("  catalog : %d courses" % len(index.courses))
    print("  queries : %d labelled goals" % len(cases))
    print("  relevant: %d judgements"
          % sum(len(c["relevant"]) for c in cases))
    print()

    bm25_summary, bm25_rows = evaluate(index, cases, rank_bm25, "BM25 (ours)")
    title_summary, _ = evaluate(index, cases, rank_title_match, "title-match")
    alpha_summary, _ = evaluate(index, cases, rank_alphabetical, "catalog order")

    # Average random over several seeds so the floor is not a lucky draw.
    random_runs = [
        evaluate(index, cases, lambda i, c, s=s: rank_random(i, c, s), "random")[0]
        for s in RANDOM_SEEDS
    ]
    random_summary = {"method": "random (%d seeds)" % len(RANDOM_SEEDS)}
    for metric in random_runs[0]:
        if metric == "method":
            continue
        vals = [r[metric] for r in random_runs if r[metric] is not None]
        random_summary[metric] = sum(vals) / len(vals) if vals else None

    cols = ["R@5", "R@10", "R@16", "P@10", "nDCG@10", "MRR", "SkillCov@16"]
    header = "  %-18s" % "method" + "".join("%12s" % c for c in cols)
    print(header)
    print("  " + "-" * (len(header) - 2))
    for s in (bm25_summary, title_summary, alpha_summary, random_summary):
        line = "  %-18s" % s["method"]
        for c in cols:
            v = s.get(c)
            line += "%12s" % ("%.3f" % v if v is not None else "-")
        print(line)

    lift = (bm25_summary["R@16"] / random_summary["R@16"]
            if random_summary["R@16"] else float("inf"))
    print()
    print("  BM25 Recall@16 is %.1fx the random floor." % lift)
    print("  Recall@16 matters most: 16 is the shortlist size the LLM sees, so")
    print("  it caps what any generated path can possibly contain.")

    if args.detail:
        print()
        print("  Per-query (BM25)")
        print("  %-40s %6s %7s %7s %8s" % ("goal", "rel", "R@16", "MRR", "SkillCov"))
        for r in bm25_rows:
            print("  %-40s %6d %7.3f %7.3f %8s"
                  % (r["goal"][:40], r["n_relevant"], r["R@16"], r["MRR"],
                     "%.3f" % r["SkillCov@16"] if r["SkillCov@16"] is not None else "-"))


if __name__ == "__main__":
    main()
