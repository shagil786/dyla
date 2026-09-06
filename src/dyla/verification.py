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
  paraphrased reversals. It is deliberately conservative in the other
  direction too: a sentence may contradict only when no better-matching
  sentence stays silent (scope gate), and negation parity is judged per
  shared word, so a sub-clause negation both sides share ("…without input
  tax credit…") cancels instead of manufacturing or masking a reversal.
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


def _negation_scope(text: str) -> frozenset[str]:
    """Content words a negation token reaches, i.e. its local scope.

    Returns the content words that follow each negation token, up to three of
    them (a negator binds its nearest words: "not taxed at 5% GST without input
    tax credit" binds "taxed" first, and the second negator "without" opens its
    own scope over "input tax credit"). Words from a scope are the propositions
    that side asserts *negatively*.

    Scope is bounded at three content words on purpose. A longer reach would
    let an incidental negated clause colour words far outside it — a claim
    quoting "…without input tax credit for standalone restaurants" would put
    "standalone" in the negation scope even though nothing about standalone is
    negated. The price is missing a negation separated from its verb by more
    than two content words; that is the rarer failure and it fails toward
    "no signal", never toward a false contradiction.
    """
    negated: set[str] = set()
    remaining = 0
    for token in _WORD.findall(text.casefold()):
        if token in _NEGATIONS:
            remaining = 3  # a negator opens a fresh scope over three words
            continue
        if remaining <= 0:
            continue
        if token in _STOPWORDS or _is_numeric_token(token):
            continue  # transparent to scope: articles and figures bind nothing
        negated.add(token)
        remaining -= 1
    return frozenset(negated)


def _polarity_conflict(claim: str, sentence: str) -> str | None:
    """Detect an asserted reversal between claim and sentence.

    Returns a human-readable reason, or None. Fires on an explicit antonym
    pair, or when a shared proposition word is negated on exactly one side.

    Negation parity is judged per word, not per sentence. A negation shared by
    both sides is a shared fact — "…without input tax credit" appears in both a
    claim and its verbatim source — and must not make the claim look negated.
    What counts is whether the *same word* is asserted on one side and negated
    on the other: the seeded mutation "…are not taxed at 5% GST without input
    tax credit…" and its source "…are taxed at 5% GST without input tax
    credit…" share the "without" clause, but "taxed" is negated only on the
    claim side. Judging parity by mere presence anywhere would count "without"
    on both sides as parity and wave that mutation through as supported.
    """
    claim_words = {word.casefold() for word in _WORD.findall(claim)}
    sentence_words = {word.casefold() for word in _WORD.findall(sentence)}
    for left, right in _ANTONYMS:
        if left in claim_words and right in sentence_words and left not in sentence_words:
            return f"the claim asserts '{left}' where the source states '{right}'"
        if right in claim_words and left in sentence_words and right not in sentence_words:
            return f"the claim asserts '{right}' where the source states '{left}'"

    claim_negated = _negation_scope(claim)
    sentence_negated = _negation_scope(sentence)
    shared = content_words(claim) & content_words(sentence)
    claim_only = (claim_negated - sentence_negated) & shared
    sentence_only = (sentence_negated - claim_negated) & shared
    # Each side negating words of its own is a mixed signal only when the
    # negated words are different propositions; this can still be a genuine
    # conflict (claim "not A" against a source asserting A while negating B),
    # so whichever shared word is flipped on exactly one side decides.
    if claim_only or sentence_only:
        return (
            "the source states the opposite polarity of the claim "
            f"({'source negates' if sentence_only else 'claim negates'})"
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

    matched: list[str] = []
    missing: list[str] = []
    conflicting: list[str] = []

    # --- numeric/date facts are evaluated BEFORE polarity is consulted ---
    # Numbers are the claim's most trustworthy content: a sentence that
    # restates the figure settles the claim more reliably than a polarity word
    # in a weaker sentence can unsettle it. So the fact comparison runs first
    # and polarity (below) is only allowed to override its conclusion when the
    # polarity conflict itself survives the scope check.
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

    # --- polarity contradiction (catches claims carrying no numbers) ---
    # Scope check: a sentence may contradict the claim only when no
    # *better-matching* sentence stays silent. Sentences are examined in
    # descending order of how much of the claim they restate; a weaker sentence
    # that flips a sub-clause (a claim quoting "…without input tax credit",
    # contradicted by a sentence about a different customer class that pays
    # "with input tax credit") must not override a stronger sentence that
    # restates the claim and stays silent. Contradiction by polarity is only
    # legitimate when the conflicting sentence is the best available statement
    # about the claim — or every better statement conflicts too.
    for url, detail in per_document.items():
        ranked = detail["context"][:5]
        for index, sentence in enumerate(ranked):
            reason = _polarity_conflict(claim_text, sentence)
            if reason is None:
                continue
            if any(
                _polarity_conflict(claim_text, better) is None
                for better in ranked[:index]
            ):
                continue
            return VerificationResult(
                "contradicted",
                f"{url} contradicts the claim: {reason}. Source text: \"{_clip(sentence)}\"",
                conflicting_facts=[_clip(sentence)],
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


def on_topic(claim_text: str, source_text: str) -> bool:
    """Whether ``source_text`` addresses the claim's subject at all.

    Word overlap alone is brittle for short claims; entity overlap rescues the
    case where a source is squarely about the right company yet shares little
    wording. Same signal verify_claim uses for its ``uncited`` decision, kept
    here as the cheap relevance gate for corroboration candidates.
    """
    claim_words = content_words(claim_text)
    if not claim_words:
        return False
    word_topicality = len(claim_words & content_words(source_text)) / len(claim_words)
    claim_entities = proper_nouns(claim_text)
    entity_topicality = (
        len(claim_entities & proper_nouns(source_text)) / len(claim_entities)
        if claim_entities
        else 0.0
    )
    # A claim about a named subject is not addressed by a page that never names
    # it, however similar the wording. Financial sentences are near-identical
    # boilerplate once the company name is removed -- "X reported a net profit
    # of N crore rupees for the financial year 2025" -- so Infosys's filing
    # scored 0.88 word overlap against a *Zerodha* claim with zero entity
    # overlap, was accepted as on-topic, found not to state Zerodha's figure,
    # and used as grounds to reject a true and correctly cited claim. That is
    # how Q8 lost every profitability claim it had. When the claim names
    # entities, sharing one is necessary; word overlap can then only add
    # topicality, never manufacture it.
    if claim_entities and entity_topicality == 0.0:
        return False
    return max(word_topicality, entity_topicality) >= TOPICALITY_FLOOR


def corroborates(
    claim_text: str, source_text: str, known_entities: frozenset[str] | set[str] = frozenset()
) -> bool:
    """Whether ``source_text`` independently states the claim's material facts.

    This is the cross-check question, and it is deliberately weaker than
    ``verify_claim(...) == supported``. Corroboration asks only "is there
    independent evidence for the headline fact(s) of this claim?" — not whether
    the source fully verifies the claim. The differences matter:

    * A multi-figure claim (a comparison of two companies' revenues) is
      corroborated by a source stating *either* figure; requiring every figure
      would demand one page cover the whole claim, which real sources rarely
      do.
    * Misattribution and polarity are not re-litigated here. The auditor
      already checks the *cited* sources for those, and a cross-check page that
      discusses the same figure in passing is enough to break a single-source
      monopoly on the number.
    * ``verify_claim`` returns ``unsupported`` when a source is on topic but
      omits the figure — exactly the "relevant but not corroborating" state a
      cross-check must distinguish from "off topic, no information", and the
      reason this function answers yes/no rather than a verdict.

    A source that does not address the claim's subject never corroborates,
    whatever numbers it contains: a market report quoting the same index level
    is not independent evidence for a revenue figure.
    """
    if not on_topic(claim_text, source_text):
        return False
    numbers = extract_numbers(claim_text)
    years = extract_years(claim_text)
    if numbers:
        return any(
            fact.matches(candidate)
            for fact in numbers
            for candidate in extract_numbers(source_text)
        )
    if years:
        return bool(years & extract_years(source_text))
    # No facts to cross-check: an independent restatement of the assertion is
    # the only corroboration available. Require a sentence that substantially
    # restates the claim, as the lexical branch of verify_claim does.
    claim_words = content_words(claim_text)
    best = max(
        (_overlap(claim_words, sentence) for sentence in sentences(source_text)),
        default=0.0,
    )
    return best >= LEXICAL_SUPPORT_FLOOR


# Words naming *what is being measured*. Two numbers are only in disagreement
# if they measure the same thing about the same subject; a company's profit and
# another company's revenue are both large rupee figures and are not in
# conflict. Grouped by measure so the comparison is between groups, not words.
_MEASURE_TERMS: tuple[tuple[str, ...], ...] = (
    ("revenue", "revenues", "turnover", "sales", "topline"),
    ("profit", "profits", "earnings", "pat", "bottomline"),
    ("loss", "losses", "lossmaking"),
    ("valuation", "valued", "worth"),
    # "round" and "investment" are deliberately absent: they co-occur with both
    # valuations and raise amounts ("the round valued Zepto at..."), so
    # including them put a valuation claim and a funding sentence in the same
    # group and produced a false conflict between $5bn and $100m.
    ("raised", "raising", "funding"),
    ("rate", "tax", "gst", "levy"),
    ("stores", "outlets", "branches"),
    ("employees", "headcount", "staff"),
)


# Corporate and generic suffixes that are capitalised but name nobody. Without
# this, "Infosys Limited reported..." yielded the subject {"limited"}, which
# "Wipro Limited reported..." satisfies -- so a Wipro figure was ruled to
# contradict an Infosys claim.
_SUBJECT_SUFFIXES = frozenset({
    "limited", "ltd", "inc", "incorporated", "corp", "corporation", "plc",
    "llp", "llc", "pvt", "private", "group", "holdings", "technologies",
    "services", "solutions", "industries", "enterprises", "systems",
})


def claim_subjects(text: str) -> set[str]:
    """Who a claim is about, for the purpose of matching disagreeing sources.

    Deliberately not :func:`named_entities`, which drops sentence-initial
    capitals unless they are already known entities. That rule is right for
    misattribution checking -- it avoids flagging "Restaurant services..." --
    but here it is actively harmful: claims overwhelmingly *begin* with their
    subject, so it discarded the one token that identifies who the figure
    belongs to and left only a corporate suffix shared by every other company.

    Uses :func:`proper_nouns` (every capitalised token) minus suffixes that
    name nobody. Over-inclusive by design: a spurious extra subject makes a
    disagreement harder to establish, which fails towards not adjudicating.
    """
    return {
        token for token in proper_nouns(text)
        if token not in _SUBJECT_SUFFIXES
        and not any(character.isdigit() for character in token)
        and token not in _ATTRIBUTION_IGNORED
    }


def _measures(text: str) -> frozenset[int]:
    """Indices of the measure groups mentioned in ``text``."""
    words = content_words(text)
    return frozenset(
        index for index, group in enumerate(_MEASURE_TERMS)
        if words & set(group)
    )


def rival_figure(claim_text: str, source_text: str) -> NumericFact | None:
    """A number in ``source_text`` that clearly contradicts a figure in ``claim_text``.

    The public form of the disagreement test, used by the analyst's cross-check
    to tell "this source disagrees with me" apart from "this source is silent".
    Those two need different handling -- silence is weak evidence, disagreement
    is a conflict to resolve on provenance -- and before this existed the
    cross-check treated them identically.

    A rival sentence must clear three gates, and all three were added because
    the loose version produced false conflicts on the project's own fixtures:

    1. **Context.** It restates ``CONFLICT_CONTEXT_FLOOR`` of the claim's
       content words, so an unrelated figure elsewhere on the page cannot
       manufacture a disagreement.
    2. **Subject.** The claim must name a subject, and the sentence must name
       all of them. Without this, "Wipro reported 13,135 crore" was ruled to be
       in conflict with a *Zerodha* filing stating 4,700 crore.

       A claim naming no subject at all ("The company reported a net profit of
       13,135 crore") returns ``None`` rather than being adjudicated against
       anything. This is the co-reference limit stated in WRITEUP 4.6, and the
       safe direction to fail: without knowing who "the company" is, no source
       can be shown to be talking about the same subject, and a disagreement
       that cannot be attributed is not a disagreement that can be resolved.
    3. **Measure.** It talks about the same measured quantity. Without this,
       one company's profit contradicted another's revenue purely by being a
       different large number.

    The first draft of this function applied only gate 1 and reported six
    disagreements on the eight-question suite, of which exactly one was real.
    """
    claim_facts = extract_numbers(claim_text)
    if not claim_facts:
        return None
    claim_words = content_words(claim_text)
    subjects = claim_subjects(claim_text)
    if not subjects:
        return None
    claim_measures = _measures(claim_text)

    context: list[str] = []
    for sentence in sentences(source_text):
        if _overlap(claim_words, sentence) < CONFLICT_CONTEXT_FLOOR:
            continue
        if not subjects <= claim_subjects(sentence):
            continue
        if claim_measures and not (claim_measures & _measures(sentence)):
            continue
        context.append(sentence)
    if not context:
        return None
    for fact in claim_facts:
        rival = _find_conflicting_value(fact, context)
        if rival is not None:
            return rival
    return None


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
