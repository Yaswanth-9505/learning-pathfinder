"""Course retrieval and skill-gap analysis.

Implements Okapi BM25 ranking over the local course catalog. Pure Python and
zero extra dependencies, which keeps the "no massive downloads" promise while
still giving the recommender a real information-retrieval stage instead of
asking the LLM to invent course names.
"""

import json
import math
import re
from collections import Counter
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# BM25 tuning. k1 controls term-frequency saturation, b controls how much
# document length is penalised.
K1 = 1.5
B = 0.75

STOPWORDS = {
    "a", "an", "and", "the", "to", "of", "for", "in", "on", "with", "is", "are",
    "be", "as", "at", "by", "from", "or", "that", "this", "it", "i", "my", "me",
    "want", "wants", "wanted", "would", "like", "learn", "learning", "become",
    "get", "getting", "how", "what", "some", "more", "can", "will", "should",
}

_TOKEN_RE = re.compile(r"[a-z0-9\+#\.]+")


def tokenize(text):
    """Lowercase, split on non-word chars, drop stopwords, split hyphens."""
    if not text:
        return []
    text = text.lower().replace("-", " ").replace("_", " ")
    return [t for t in _TOKEN_RE.findall(text) if t and t not in STOPWORDS]


def _load(name):
    with open(DATA_DIR / name, encoding="utf-8") as fh:
        return json.load(fh)


class CourseIndex:
    """BM25 index over the course catalog."""

    def __init__(self, courses=None, roles=None):
        self.courses = courses if courses is not None else _load("courses.json")
        self.roles = roles if roles is not None else _load("roles.json")
        self.by_id = {c["id"]: c for c in self.courses}

        # Skill vocabulary across the whole catalog, used for gap analysis.
        self.all_skills = sorted({s for c in self.courses for s in c["skills"]})

        self._docs = [self._doc_tokens(c) for c in self.courses]
        self._lengths = [len(d) for d in self._docs]
        self._avg_len = (sum(self._lengths) / len(self._docs)) if self._docs else 0.0
        self._tf = [Counter(d) for d in self._docs]

        df = Counter()
        for d in self._docs:
            df.update(set(d))
        n = len(self._docs)
        # Standard BM25 idf with the +1 smoothing that keeps values positive.
        self._idf = {
            term: math.log(1 + (n - freq + 0.5) / (freq + 0.5))
            for term, freq in df.items()
        }

    def _doc_tokens(self, course):
        """Weighted field concatenation: title and skills matter most."""
        parts = []
        parts += tokenize(course["title"]) * 3
        parts += tokenize(" ".join(course["skills"])) * 3
        parts += tokenize(" ".join(course["domains"])) * 2
        parts += tokenize(course["description"])
        parts += tokenize(course["provider"])
        parts += tokenize(" ".join(course.get("format", [])))
        return parts

    def _score(self, idx, query_tokens):
        tf = self._tf[idx]
        dl = self._lengths[idx] or 1
        score = 0.0
        for term in query_tokens:
            f = tf.get(term)
            if not f:
                continue
            idf = self._idf.get(term, 0.0)
            denom = f + K1 * (1 - B + B * dl / self._avg_len)
            score += idf * (f * (K1 + 1)) / denom
        return score

    # -- public API ---------------------------------------------------------

    def search(self, query, top_k=20, level=None, exclude_ids=()):
        """Rank courses against a free-text query.

        `level` softly boosts courses matching the learner's experience level
        rather than filtering, so a beginner can still receive one stretch
        course when it is clearly the right next step.
        """
        tokens = tokenize(query)
        if not tokens:
            return []

        level_rank = {"beginner": 0, "intermediate": 1, "advanced": 2}
        target = level_rank.get(level)

        scored = []
        for i, course in enumerate(self.courses):
            if course["id"] in exclude_ids:
                continue
            base = self._score(i, tokens)
            if base <= 0:
                continue
            if target is not None:
                distance = abs(level_rank.get(course["level"], 1) - target)
                # 1.0 same level, 0.85 one step away, 0.72 two steps away.
                base *= 0.85 ** distance
            scored.append((base, course))

        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [
            dict(course, retrieval_score=round(score, 4))
            for score, course in scored[:top_k]
        ]

    def build_query(self, profile):
        """Turn a learner profile into a retrieval query.

        Goals are repeated because they are the strongest signal for what the
        learner is actually trying to reach. The learning style contributes the
        matching catalog `format` tokens once - enough to break ties toward the
        preferred delivery mode without letting format outrank subject matter.
        """
        goals = profile.get("goals", "")
        interests = profile.get("interests", "")
        target_skills = " ".join(self.role_skills(goals))
        formats = " ".join(self.style_formats(profile.get("learning_style", "")))
        return " ".join([goals, goals, interests, target_skills, formats]).strip()

    def style_formats(self, learning_style):
        """Map a stated learning style onto the catalog's `format` vocabulary.

        The catalog tags each course with how it is delivered; without this the
        learner's stated preference never reaches ranking at all.
        """
        if not learning_style:
            return []
        text = learning_style.lower()
        mapping = {
            "hands-on": ["hands", "on", "projects", "assignments"],
            "practical": ["hands", "on", "projects"],
            "project": ["projects", "hands", "on"],
            "video": ["video"],
            "visual": ["video"],
            "watching": ["video"],
            "reading": ["reading"],
            "text": ["reading"],
            "self-paced": ["reading", "hands", "on"],
        }
        for key, formats in mapping.items():
            if key in text:
                return formats
        return []

    def _best_role(self, goal_text):
        """Highest alias-overlap role for a goal.

        Ties are broken by alias specificity rather than catalog order: 'data
        analyst', 'data scientist' and 'data engineer' all share the token
        'data', so a bare max-overlap scan would bind to whichever happened to
        be listed first.
        """
        tokens = set(tokenize(goal_text))
        if not tokens:
            return None

        scored = []
        for role in self.roles:
            best_for_role = 0.0
            for alias in role["aliases"]:
                alias_tokens = set(tokenize(alias))
                if not alias_tokens:
                    continue
                overlap = len(tokens & alias_tokens)
                if not overlap:
                    continue
                # Reward matching a larger share of the alias, so a two-token
                # alias fully matched beats a longer alias matched on one token.
                best_for_role = max(best_for_role, overlap + overlap / len(alias_tokens))
            if best_for_role:
                scored.append((best_for_role, role))

        if not scored:
            return None
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return scored[0][1]

    def role_skills(self, goal_text):
        """Match a free-text goal to the skill set of a known target role."""
        role = self._best_role(goal_text)
        return role["skills"] if role else []

    def match_role(self, goal_text):
        """Return the matched role record, or None."""
        return self._best_role(goal_text)

    def normalize_skills(self, text):
        """Extract known catalog skills mentioned in free text.

        Used to turn 'I know basic python and some SQL' into concrete skill
        tags that can be subtracted from the target role's requirements.
        """
        if not text:
            return []
        tokens = tokenize(text)
        token_set = set(tokens)
        # Padded so multi-word skills match on whole-token boundaries only.
        # A naive substring test would read "c" out of "basic".
        joined = " %s " % " ".join(tokens)
        found = []
        for skill in self.all_skills:
            parts = tokenize(skill)
            if not parts:
                continue
            if len(parts) == 1:
                if parts[0] in token_set:
                    found.append(skill)
            elif " %s " % " ".join(parts) in joined:
                found.append(skill)
        return sorted(set(found))

    def skill_gap(self, profile, acquired_skills=()):
        """Compare what the learner has against what the goal role needs.

        Returns the target role, the skills already held, and the gap. This is
        what makes the recommendation explainable: every selected course can be
        traced back to a specific missing skill.
        """
        goals = profile.get("goals", "")
        role = self.match_role(goals)
        target = set(role["skills"]) if role else set()

        known = set(self.normalize_skills(profile.get("completed_learning", "")))
        known |= {s for s in acquired_skills if s in set(self.all_skills)}
        known |= {s.lower().strip() for s in acquired_skills}

        have = sorted(target & known)
        gap = sorted(target - known)
        coverage = (len(have) / len(target) * 100) if target else 0.0

        return {
            "role": role["name"] if role else None,
            "role_id": role["id"] if role else None,
            "target_skills": sorted(target),
            "known_skills": sorted(known),
            "covered_skills": have,
            "missing_skills": gap,
            "coverage_percent": round(coverage, 1),
        }
