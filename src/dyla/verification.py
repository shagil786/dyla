"""Deterministic claim verification against source text.

Why this module exists
----------------------
The previous deterministic auditor decided support by asking whether the entire
normalised claim string appeared as a substring of the source document::

    claim_present_in_all = all(claim_text in text for text in normalized_texts)

Real sources paraphrase. A page reading "Infosys Limited reported consolidated
revenue of Rs 1,53,670 crore for the financial year 2024" does not contain the
claim "Infosys reported revenue of 1,53,670 crore rupees in FY2024" as a
substring, so a plainly supporting source was marked ``unsupported``. Every
claim failed, which makes the verdicts carry no information at all — the exact
mirror of an auditor that approves everything.

The approach here is slot-based rather than string-based. A claim is decomposed
into *material facts* (numbers with magnitude and unit, and years) plus its
content words. Verification asks whether the source asserts those same facts,
and — importantly — whether it asserts a *different* value for one of them,
which is the only way a deterministic auditor can ever return ``contradicted``.

Three-zone numeric comparison
-----------------------------
Matching and conflicting are deliberately asymmetric:

* within ``MATCH_TOLERANCE`` (1%)      -> the fact is confirmed. Loose enough to
  absorb rounding, so "1.54 lakh crore" confirms "1,53,670 crore" (0.21% apart).
* beyond ``CONFLICT_TOLERANCE`` (5%)   -> the fact is contradicted.
* in the 1-5% band                     -> neither. Reported as unverified.

The gap between the two thresholds is the point. A single tolerance would force
every rounding difference to be called a contradiction, and an auditor that
cries contradiction over rounding is as useless as one that approves
everything. Claims landing in the band are honestly reported as unverified
rather than being pushed to whichever verdict is convenient.

Known limits (stated here because the auditor's blind spots matter):

* Sentence segmentation is regex-based and will mis-split on abbreviations.
* Co-reference is not resolved: "the company reported X" is matched by topical
  word overlap, not by knowing which company "the company" is.
* Polarity detection uses a fixed antonym/negation table and will miss
  paraphrased reversals.
* A source that discusses two entities in one sentence can produce a false
  contradiction when the number belongs to the other entity.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

VerificationStatus = Literal["supported", "unsupported", "contradicted", "uncited"]

# A fact is confirmed within 1%, contradicted beyond 5%, and reported as
# unverified in between. See the module docstring for why these differ.
MATCH_TOLERANCE = 0.01
CONFLICT_TOLERANCE = 0.05

# Below this share of claim content words appearing anywhere in the sources, the
# documents are judged not to address the claim at all -> "uncited".
TOPICALITY_FLOOR = 0.20
# A sentence must share this share of the claim's content words before a numeric
# disagreement inside it is treated as a contradiction rather than a coincidence.
CONFLICT_CONTEXT_FLOOR = 0.34
# For claims carrying no numbers or years, lexical entailment needs this much of
# the claim present in a single sentence before it counts as supported.
LEXICAL_SUPPORT_FLOOR = 0.70

_SCALES: dict[str, float] = {
    "hundred": 1e2,
    "thousand": 1e3,
    "k": 1e3,
    "lakh": 1e5,
    "lakhs": 1e5,
    "lac": 1e5,
    "million": 1e6,
    "mn": 1e6,
    "m": 1e6,
    "crore": 1e7,
    "crores": 1e7,
    "cr": 1e7,
    "billion": 1e9,
    "bn": 1e9,
    "b": 1e9,
    "trillion": 1e12,
    "tn": 1e12,
}

_CURRENCY_MARKERS = ("₹", "$", "rs", "inr", "usd", "rupee", "rupees", "dollar", "dollars")

_STOPWORDS = frozenset({
    "a", "about", "above", "after", "all", "also", "an", "and", "any", "are", "as", "at",
    "be", "been", "being", "between", "both", "but", "by", "can", "did", "do", "does",
    "during", "each", "for", "from", "had", "has", "have", "he", "her", "him", "his",
    "how", "in", "into", "is", "it", "its", "more", "most", "no", "nor", "not", "of",
    "on", "one", "only", "or", "other", "our", "out", "over", "own", "per", "same",
    "she", "should", "since", "so", "some", "such", "than", "that", "the", "their",
    "them", "then", "there", "these", "they", "this", "those", "through", "to", "under",
    "up", "was", "we", "were", "what", "when", "where", "which", "while", "who", "whom",
    "why", "will", "with", "would", "you", "your",
})

_NEGATIONS = frozenset({
    "not", "no", "never", "without", "neither", "nor", "cannot", "cant", "isnt",
    "wasnt", "arent", "werent", "doesnt", "didnt", "dont", "hasnt", "havent", "wont",
    "failed", "denied", "rejected", "declined",
})

# Ordered antonym pairs used for polarity conflict on non-numeric claims.
_ANTONYMS: tuple[tuple[str, str], ...] = (
    ("profit", "loss"),
    ("profitable", "unprofitable"),
    ("profitable", "lossmaking"),
    ("rose", "fell"),
    ("increased", "decreased"),
    ("gained", "lost"),
    ("grew", "shrank"),
    ("up", "down"),
    ("acquired", "divested"),
    ("opened", "closed"),
    ("expanded", "contracted"),
    ("appointed", "resigned"),
    ("joined", "left"),
    ("approved", "rejected"),
)

_NUMBER_PATTERN = re.compile(
    r"(?P<currency>[₹$]|\b(?:rs|inr|usd)\b\.?\s*)?\s*"
    # The comma-grouped alternative requires at least one comma group. With `*`
    # it also matched plain runs of digits, and being first in the alternation it
    # won greedily at three digits: "2024" parsed as 202 and 4, so the bare-year
    # guard below never fired and years were compared against monetary amounts.
    r"(?P<value>\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"\s*(?P<scale>hundred|thousand|lakhs?|lac|crores?|million|billion|trillion|cr\b|mn\b|bn\b|tn\b|k\b|m\b|b\b)?"
    r"\s*(?P<scale2>crores?|cr\b)?"
    r"\s*(?P<percent>%|per\s*cent|percent)?",
    re.IGNORECASE,
)

_YEAR_PATTERN = re.compile(r"\b(?:fy\s*)?((?:19|20)\d{2})\b", re.IGNORECASE)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")
_WORD = re.compile(r"[\w']+")


@dataclass(frozen=True)
class NumericFact:
    """A number lifted out of text, normalised to a comparable magnitude."""

    value: float
    kind: Literal["currency", "percent", "count"]
    raw: str

    def matches(self, other: "NumericFact", tolerance: float = MATCH_TOLERANCE) -> bool:
        if self.kind != other.kind:
            return False
        return _relative_difference(self.value, other.value) <= tolerance

    def conflicts(self, other: "NumericFact", tolerance: float = CONFLICT_TOLERANCE) -> bool:
        if self.kind != other.kind:
            return False
        return _relative_difference(self.value, other.value) > tolerance


@dataclass
class VerificationResult:
    status: VerificationStatus
    explanation: str
    matched_facts: list[str] = field(default_factory=list)
    missing_facts: list[str] = field(default_factory=list)
    conflicting_facts: list[str] = field(default_factory=list)
    topicality: float = 0.0


def _relative_difference(left: float, right: float) -> float:
    if left == right:
        return 0.0
    scale = max(abs(left), abs(right))
    if scale == 0:
        return 0.0
    return abs(left - right) / scale


def content_words(text: str) -> set[str]:
    """Lowercased, stopword-stripped word set used for topical overlap.

    Pure-digit tokens are excluded. They are verified separately as numeric
    facts, and leaving them in double-counted them: a claim like "revenue of
    1,53,670 crore" contributed "53" and "670" as topic words, so a source that
    discussed the right subject but quoted no figure scored as off-topic and was
    wrongly called "uncited" instead of "unsupported".
    """
    words = (word.strip("'").casefold() for word in _WORD.findall(text))
    return {
        word
        for word in words
        if len(word) > 1 and word not in _STOPWORDS and not _is_numeric_token(word)
    }


def _is_numeric_token(word: str) -> bool:
    return word.isdigit() or bool(re.fullmatch(r"fy\s*(?:19|20)\d{2}", word))


def proper_nouns(text: str) -> set[str]:
    """Capitalised tokens, used as a topicality signal independent of wording.

    Word overlap alone is brittle for short claims: a source can be squarely
    about the right company and period yet share few words with the claim's
    phrasing. Entity overlap catches that case.
    """
    found = {
        token.casefold()
        for token in re.findall(r"\b[A-Z][\w&.'-]*", text or "")
    }
    return {token for token in found if token not in _STOPWORDS and len(token) > 1}


# Capitalised tokens that are common sentence openers or generic, and so carry
# no attribution signal. Kept small on purpose: a big list here starts silently
# excusing real misattributions.
_ATTRIBUTION_IGNORED = frozenset({
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december", "monday", "tuesday",
    "wednesday", "thursday", "friday", "saturday", "sunday", "the", "this",
    "that", "these", "those", "its", "their", "company", "companies",
})


def named_entities(text: str, known: frozenset[str] | set[str] = frozenset()) -> set[str]:
    """Capitalised tokens that are not merely sentence-initial.

    Distinct from :func:`proper_nouns`, which takes every capitalised token and
    is right for a loose topicality signal. Attribution checking needs the
    stricter set: "Restaurant services in India are taxed at 5%" opens with a
    capitalised ordinary word, and treating "Restaurant" as a named entity would
    manufacture attribution failures on perfectly good claims.
    """
    known = {name.casefold() for name in known}
    found: set[str] = set()
    for sentence in sentences(text):
        tokens = re.findall(r"[A-Za-z][\w&.'-]*", sentence)
        for index, token in enumerate(tokens):
            if not token[:1].isupper():
                continue
            # Position is the only cheap signal for "capitalised because it is a
            # name" versus "capitalised because the sentence starts here", and
            # it is wrong for the common case "Wipro reported revenue of ...".
            # `known` -- the entities the system has actually researched --
            # rescues that case without a dictionary.
            if index == 0 and token.casefold().strip(".'-") not in known:
                continue
            folded = token.casefold().strip(".'-")
            # Tokens carrying digits are period labels ("FY2024", "Q3"), not
            # entities. The first version of this check flagged FY2024 as an
            # unmentioned entity against a source reading "financial year 2024"
            # and turned five correct verdicts wrong. Periods are already
            # checked by the year extractor; checking them here as well only
            # adds a spelling requirement the sources never agreed to.
            if any(character.isdigit() for character in folded):
                continue
            if len(folded) > 1 and folded not in _STOPWORDS and folded not in _ATTRIBUTION_IGNORED:
                found.add(folded)
    return found


def unmentioned_entities(
    claim_text: str, source_text: str, known: frozenset[str] | set[str] = frozenset()
) -> set[str]:
    """Named entities the claim asserts something about that no source mentions.

    This is the misattribution check. A true statement bolted onto the wrong
    company -- "Nithin Kamath is the chief executive officer of Infosys" cited
    to a page about Zerodha -- shares almost all of its wording with the source
    and sails through both lexical entailment and numeric agreement. The only
    thing wrong with it is the name, so the name is what has to be checked.

    Absence is deliberately treated as *unsupported*, never *contradicted*. The
    source not mentioning Infosys is not the source denying the sentence.
    """
    haystack = (source_text or "").casefold()
    return {
        entity for entity in named_entities(claim_text, known)
        if not re.search(rf"(?<![\w]){re.escape(entity)}(?![\w])", haystack)
    }


def sentences(text: str) -> list[str]:
    return [part.strip() for part in _SENTENCE_SPLIT.split(text or "") if part.strip()]


def extract_years(text: str) -> set[int]:
    return {int(match.group(1)) for match in _YEAR_PATTERN.finditer(text or "")}


def extract_numbers(text: str) -> list[NumericFact]:
    """Pull comparable numeric facts out of text.

    Handles Indian (lakh/crore, and the 1,23,456 grouping) and Western
    (million/billion) magnitudes, currency markers, and percentages. Bare
    four-digit years are skipped; they are handled by ``extract_years`` so that
    "2024" is never compared against a monetary amount.
    """
    facts: list[NumericFact] = []
    if not text:
        return facts
    for match in _NUMBER_PATTERN.finditer(text):
        raw_value = match.group("value")
        if not raw_value:
            continue
        scale_token = (match.group("scale") or "").strip().casefold().rstrip(".")
        scale2_token = (match.group("scale2") or "").strip().casefold().rstrip(".")
        percent = bool(match.group("percent"))
        currency_marker = (match.group("currency") or "").strip().casefold().rstrip(".")

        # A bare 4-digit year with no scale/percent/currency context is a date.
        if (
            not scale_token
            and not scale2_token
            and not percent
            and not currency_marker
            and re.fullmatch(r"(?:19|20)\d{2}", raw_value)
        ):
            continue

        try:
            value = float(raw_value.replace(",", ""))
        except ValueError:
            continue

        multiplier = _SCALES.get(scale_token, 1.0) if scale_token else 1.0
        # "1.5 lakh crore" — a second scale word compounds the first.
        if scale2_token:
            multiplier *= _SCALES.get(scale2_token, 1.0)
        value *= multiplier

        if percent:
            kind: Literal["currency", "percent", "count"] = "percent"
        elif currency_marker or _has_currency_context(text, match.start(), match.end()):
            kind = "currency"
        else:
            kind = "count"

        facts.append(NumericFact(value=value, kind=kind, raw=match.group(0).strip()))
    return facts


def _has_currency_context(text: str, start: int, end: int) -> bool:
    window = text[max(0, start - 18) : min(len(text), end + 18)].casefold()
    return any(marker in window for marker in _CURRENCY_MARKERS)


def _overlap(claim_words: set[str], other: str) -> float:
    if not claim_words:
        return 0.0
    return len(claim_words & content_words(other)) / len(claim_words)


def _polarity_conflict(claim: str, sentence: str) -> str | None:
    """Detect an asserted reversal between claim and sentence.

    Returns a human-readable reason, or None. Only fires on an explicit antonym
    pair or a negation present on exactly one side, both of which are narrow
    enough to keep false contradictions rare.
    """
    claim_words = {word.casefold() for word in _WORD.findall(claim)}
    sentence_words = {word.casefold() for word in _WORD.findall(sentence)}
    for left, right in _ANTONYMS:
        if left in claim_words and right in sentence_words and left not in sentence_words:
            return f"the claim asserts '{left}' where the source states '{right}'"
        if right in claim_words and left in sentence_words and right not in sentence_words:
            return f"the claim asserts '{right}' where the source states '{left}'"
    claim_negated = bool(claim_words & _NEGATIONS)
    sentence_negated = bool(sentence_words & _NEGATIONS)
    if claim_negated != sentence_negated:
        shared = len(claim_words & sentence_words) / max(1, len(claim_words))
        if shared >= 0.5:
            return (
                "the source states the opposite polarity of the claim "
                f"({'source negates' if sentence_negated else 'claim negates'})"
            )
    return None


def verify_claim(
    claim_text: str,
    documents: dict[str, str],
    known_entities: frozenset[str] | set[str] = frozenset(),
) -> VerificationResult:
    """Judge ``claim_text`` against ``{url: document_text}`` without a model.

    Each document is examined separately. That matters for disagreement: if one
    source confirms a figure and another asserts a different one, checking the
    concatenation of all sources would find the matching value and silently
    return "supported", hiding the conflict. Per-source checking surfaces it.
    """
    claim_text = (claim_text or "").strip()
    if not claim_text:
        return VerificationResult("unsupported", "The claim is empty.")
    live = {url: text for url, text in documents.items() if (text or "").strip()}
    if not live:
        return VerificationResult("unsupported", "No source text was available to verify the claim.")

    claim_words = content_words(claim_text)
    claim_entities = proper_nouns(claim_text)
    claim_numbers = extract_numbers(claim_text)
    claim_years = extract_years(claim_text)

    per_document: dict[str, dict] = {}
    for url, text in live.items():
        ranked = sorted(
            ((sentence, _overlap(claim_words, sentence)) for sentence in sentences(text)),
            key=lambda item: -item[1],
        )
        per_document[url] = {
            "numbers": extract_numbers(text),
            "years": extract_years(text),
            "context": [sentence for sentence, score in ranked if score >= CONFLICT_CONTEXT_FLOOR],
            "best": ranked[0] if ranked else ("", 0.0),
        }

    combined = " ".join(live.values())
    word_topicality = _overlap(claim_words, combined)
    entity_topicality = (
        len(claim_entities & proper_nouns(combined)) / len(claim_entities)
        if claim_entities
        else 0.0
    )
    topicality = max(word_topicality, entity_topicality)
    if topicality < TOPICALITY_FLOOR:
        return VerificationResult(
            "uncited",
            "The fetched sources do not address the claim "
            f"(only {topicality:.0%} of its key terms or entities appear).",
            topicality=topicality,
        )

    # --- misattribution: the claim names something no source ever mentions ---
    # Placed before every other check because it invalidates them. If the
    # sources never mention the subject, matching numbers and matching wording
    # are evidence about some other subject, and letting them return
    # "supported" is precisely how a swapped entity slips through.
    unmentioned = unmentioned_entities(claim_text, combined, known_entities)
    if unmentioned:
        names = ", ".join(sorted(unmentioned))
        return VerificationResult(
            "unsupported",
            f"The claim is attributed to {names}, which none of the fetched sources "
            "mention. Whatever else the sources confirm is about something else.",
            missing_facts=sorted(unmentioned),
            topicality=topicality,
        )

    # --- polarity contradiction (catches claims carrying no numbers) ---
    for url, detail in per_document.items():
        for sentence in detail["context"][:5]:
            reason = _polarity_conflict(claim_text, sentence)
            if reason is not None:
                return VerificationResult(
                    "contradicted",
                    f"{url} contradicts the claim: {reason}. Source text: \"{_clip(sentence)}\"",
                    conflicting_facts=[_clip(sentence)],
                    topicality=topicality,
                )

    matched: list[str] = []
    missing: list[str] = []
    conflicting: list[str] = []

    for fact in claim_numbers:
        agreeing = [
            url for url, detail in per_document.items()
            if any(fact.matches(candidate) for candidate in detail["numbers"])
        ]
        disagreeing: list[tuple[str, NumericFact]] = []
        for url, detail in per_document.items():
            if url in agreeing:
                continue
            rival = _find_conflicting_value(fact, detail["context"])
            if rival is not None:
                disagreeing.append((url, rival))

        if disagreeing and agreeing:
            detail_text = "; ".join(f"{url} says {rival.raw}" for url, rival in disagreeing)
            conflicting.append(
                f"sources disagree on {fact.raw}: {', '.join(agreeing)} "
                f"confirms it while {detail_text}"
            )
        elif disagreeing:
            detail_text = "; ".join(f"{url} says {rival.raw}" for url, rival in disagreeing)
            conflicting.append(f"claim says {fact.raw} but {detail_text}")
        elif agreeing:
            matched.append(fact.raw)
        else:
            missing.append(fact.raw)

    for year in sorted(claim_years):
        if any(year in detail["years"] for detail in per_document.values()):
            matched.append(str(year))
        else:
            missing.append(str(year))

    if conflicting:
        return VerificationResult(
            "contradicted",
            "The sources conflict with the claim: " + "; ".join(conflicting) + ".",
            matched_facts=matched,
            missing_facts=missing,
            conflicting_facts=conflicting,
            topicality=topicality,
        )

    if claim_numbers or claim_years:
        if not missing:
            return VerificationResult(
                "supported",
                "Every checkable fact in the claim appears in the fetched sources: "
                + ", ".join(matched) + ".",
                matched_facts=matched,
                topicality=topicality,
            )
        return VerificationResult(
            "unsupported",
            "The fetched sources are on topic but do not state: " + ", ".join(missing)
            + (f" (they do confirm {', '.join(matched)})" if matched else "") + ".",
            matched_facts=matched,
            missing_facts=missing,
            topicality=topicality,
        )

    # No numbers or years to check: fall back to lexical entailment.
    best_sentence, best_overlap = max(
        (detail["best"] for detail in per_document.values()), key=lambda item: item[1]
    )
    if best_overlap >= LEXICAL_SUPPORT_FLOOR:
        return VerificationResult(
            "supported",
            f"The source restates the claim ({best_overlap:.0%} of its key terms in one "
            f"sentence): \"{_clip(best_sentence)}\"",
            matched_facts=[_clip(best_sentence)],
            topicality=topicality,
        )
    return VerificationResult(
        "unsupported",
        "The sources are on topic but no single passage states the claim "
        f"(best passage covers {best_overlap:.0%} of its key terms).",
        topicality=topicality,
    )


def _find_conflicting_value(fact: NumericFact, context: list[str]) -> NumericFact | None:
    """Find a same-kind number in on-topic text that clearly differs from ``fact``.

    Restricted to sentences that already restate a third of the claim, so an
    unrelated figure elsewhere on the page cannot manufacture a contradiction.
    Values inside the 1-5% band return None: not confirmation, but not a
    contradiction either.
    """
    for sentence in context[:5]:
        for candidate in extract_numbers(sentence):
            if candidate.kind != fact.kind:
                continue
            if fact.matches(candidate):
                return None
            if fact.conflicts(candidate):
                return candidate
    return None


def _clip(text: str, limit: int = 180) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"
