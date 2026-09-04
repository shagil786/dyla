"""Deterministic offline providers for running the question suite without keys.

What this is, and what it is not
--------------------------------
This is a **recorded-fixture harness**, not a live run. It serves a fixed corpus
of pages through the real ``SearchProvider`` interface and answers with a
deterministic extractive model. Every other component in the pipeline is the
real one: the real planner, the real entity resolver, the real memory store, the
real vector index, the real auditor and verification engine, the real quality
gate, the real orchestrator with its wall-clock budget.

It exists for three reasons:

1. The suite is reproducible and free, so the pipeline can be exercised end to
   end in CI and by a reviewer with no API keys.
2. The corpus is fixed, so cost changes across the eight questions are
   attributable to the agent's behaviour rather than to the web moving.
3. Adversarial cases can be planted deliberately -- two credible sources that
   disagree on a number, and a page that contradicts a plausible claim -- which
   is not something a live run can be relied upon to produce on demand.

Results from this harness must never be presented as live-web results. The
report generator labels them, and so should any write-up.

The extractive model is deliberately simple: it selects evidence and quotes it
rather than reasoning over it. That means answer *quality* here says nothing
about a real LLM's quality. What it does exercise honestly is the plumbing:
citation mapping, corroboration gating, audit verdicts, feedback suppression,
memory reuse, and cost accounting.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .domain import AnalystAnswer, Citation, Claim, Document, SearchHit


@dataclass
class Page:
    url: str
    title: str
    text: str
    published: datetime | None = None


def _d(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Corpus
#
# Entities are shared across questions on purpose, mirroring the suite's reuse
# map: Zerodha (Q2, Q5, Q8), Infosys/Wipro (Q3, Q6, Q8), Zepto (Q4, Q7, Q8).
# ---------------------------------------------------------------------------

CORPUS: tuple[Page, ...] = (
    # -- Q1: GST on restaurant services -------------------------------------
    Page(
        "https://example.gov.in/cbic/gst-restaurant-rates",
        "CBIC — GST rates for restaurant services",
        "Restaurant services in India are taxed at 5% GST without input tax credit for "
        "standalone restaurants. Restaurants located within hotels where the declared "
        "room tariff exceeds 7,500 rupees per night are taxed at 18% GST with input tax "
        "credit. The 5% rate has applied to standalone restaurant services since 2017.",
        _d(2026, 1, 12),
    ),
    Page(
        "https://example.com/tax-journal/gst-restaurants-explainer",
        "GST on restaurants: an explainer",
        "Standalone restaurants continue to charge 5% GST and cannot claim input tax "
        "credit. Restaurants inside premium hotels charge 18% GST. Cloud kitchens are "
        "treated as restaurant services and are taxed at 5%.",
        _d(2026, 2, 3),
    ),
    # -- Q2 / Q5 / Q8: Zerodha ----------------------------------------------
    Page(
        "https://example.com/business-daily/zerodha-leadership",
        "Zerodha leadership profile",
        "Nithin Kamath is the chief executive officer of Zerodha. He co-founded the "
        "brokerage in 2010 and has served as chief executive officer since 2010. "
        "Nikhil Kamath co-founded the firm alongside him.",
        _d(2025, 11, 4),
    ),
    Page(
        "https://example.com/markets-wire/zerodha-profile",
        "Zerodha: the bootstrapped broker",
        "Zerodha was founded in 2010 by Nithin Kamath, who remains chief executive "
        "officer. The company is headquartered in Bengaluru. Kailash Nadh is the chief "
        "technology officer of Zerodha and holds a PhD in computer science and artificial "
        "intelligence. He joined Zerodha in 2013.",
        _d(2026, 3, 18),
    ),
    Page(
        "https://example.com/filings/zerodha-fy25-results",
        "Zerodha FY2025 results summary",
        "Zerodha reported a net profit of 4,700 crore rupees for the financial year 2025. "
        "The brokerage remains profitable and has not raised external capital.",
        _d(2026, 6, 2),
    ),
    # -- Q3 / Q6 / Q8: Infosys and Wipro ------------------------------------
    Page(
        "https://example.com/exchange/infosys-annual-report-fy25",
        "Infosys annual report FY2025",
        "Infosys Limited reported consolidated revenue of 1,62,990 crore rupees for the "
        "financial year 2025. Infosys is headquartered in Bengaluru and is among the "
        "largest software services exporters in India. The company reported a net profit "
        "of 26,713 crore rupees and remains profitable.",
        _d(2025, 4, 17),
    ),
    Page(
        "https://example.com/exchange/wipro-annual-report-fy25",
        "Wipro annual report FY2025",
        "Wipro Limited reported consolidated revenue of 89,088 crore rupees for the "
        "financial year 2025. Wipro is headquartered in Bengaluru. The company reported "
        "a net profit of 13,135 crore rupees and remains profitable.",
        _d(2025, 4, 21),
    ),
    Page(
        "https://example.com/tech-press/bengaluru-it-exporters",
        "Bengaluru's largest IT exporters",
        "The largest software services exporters headquartered in Bengaluru are Infosys, "
        "Wipro and Mphasis by revenue. Infosys reported revenue of 1,62,990 crore rupees "
        "in FY2025 while Wipro reported 89,088 crore rupees.",
        _d(2025, 8, 9),
    ),
    # -- Planted disagreement: a second source with a different Infosys figure.
    #    Older, and a secondary outlet rather than the filing.
    Page(
        "https://example.com/quick-summaries/infosys-revenue-note",
        "Infosys revenue note",
        "Infosys Limited reported consolidated revenue of 1,53,670 crore rupees for the "
        "financial year 2025 according to a preliminary summary.",
        _d(2024, 12, 30),
    ),
    # -- Q4 / Q7 / Q8: quick commerce ---------------------------------------
    Page(
        "https://example.com/funding-wire/zepto-round-2025",
        "Zepto raises fresh capital",
        "Zepto raised 350 million dollars in 2025 in a round led by General Catalyst. "
        "The round valued Zepto at 5 billion dollars. Zepto had previously been valued "
        "at 1.4 billion dollars in 2023 and at 3.6 billion dollars in 2024.",
        _d(2025, 7, 22),
    ),
    Page(
        "https://example.com/funding-wire/quick-commerce-2025-rounds",
        "Indian quick commerce funding in 2025",
        "Indian quick commerce startups raising above 100 million dollars in 2025 were "
        "Zepto, which raised 350 million dollars led by General Catalyst, and "
        "Swiggy Instamart's parent, which raised 200 million dollars led by Prosus. "
        "Blinkit did not raise a separate round as it is owned by Eternal.",
        _d(2025, 12, 15),
    ),
    Page(
        "https://example.com/filings/zepto-fy25-financials",
        "Zepto FY2025 financials",
        "Zepto reported a net loss of 1,248 crore rupees for the financial year 2025. "
        "The company is not profitable and has said it aims to reach profitability in "
        "the coming years.",
        _d(2026, 1, 30),
    ),
    # -- Distractors, so retrieval has to discriminate -----------------------
    Page(
        "https://example.com/city-news/bengaluru-metro",
        "Bengaluru metro Purple Line extension",
        "The Bengaluru metro Purple Line extension opened to passengers on Saturday, "
        "cutting travel time across the city.",
        _d(2026, 2, 14),
    ),
    Page(
        "https://example.com/markets/nifty-close",
        "Markets close higher",
        "The Nifty index closed at 24,500 points while gold traded near 72,000 rupees "
        "per ten grams.",
        _d(2026, 3, 1),
    ),
)

_STOP = frozenset({
    "a", "an", "and", "are", "as", "at", "by", "did", "do", "does", "for", "from",
    "how", "in", "is", "it", "its", "of", "on", "or", "the", "their", "to", "was",
    "were", "what", "which", "who", "with", "state", "list", "compare", "according",
})


def _tokens(text: str) -> set[str]:
    return {
        word for word in re.findall(r"[\w']+", (text or "").casefold())
        if len(word) > 1 and word not in _STOP
    }


def _source_id(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:16]


@dataclass
class OfflineResearchProvider:
    """A SearchProvider backed by a fixed corpus, with call accounting.

    Implements both halves of the protocol (``search`` and ``fetch``) exactly as
    the You.com adapter does, so the analyst and auditor exercise their real
    code paths.
    """

    pages: tuple[Page, ...] = CORPUS
    searches: list[str] = field(default_factory=list)
    fetches: list[str] = field(default_factory=list)

    def search(self, query: str, limit: int = 5) -> list[SearchHit]:
        self.searches.append(query)
        wanted = _tokens(query)
        scored = []
        for page in self.pages:
            score = len(wanted & _tokens(f"{page.title} {page.text}"))
            if score:
                scored.append((score, page))
        scored.sort(key=lambda item: (-item[0], item[1].url))
        return [
            SearchHit(url=page.url, title=page.title, snippet=page.text[:200],
                      published_at=page.published)
            for _, page in scored[:limit]
        ]

    def fetch(self, url: str) -> Document:
        self.fetches.append(url)
        for page in self.pages:
            if page.url == url:
                return Document(source_id=_source_id(url), url=url, title=page.title,
                                text=page.text, published_at=page.published)
        raise ValueError(f"offline corpus has no page for {url}")

    def close(self) -> None:  # parity with the live provider
        return None


class OfflineEmbedder:
    """Deterministic hashed bag-of-words embedding. No network, no keys."""

    def __init__(self, dimensions: int = 64) -> None:
        self.dimensions = dimensions

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            vector = [0.0] * self.dimensions
            for token in _tokens(text):
                index = int(hashlib.sha256(token.encode()).hexdigest(), 16) % self.dimensions
                vector[index] += 1.0
            norm = sum(value * value for value in vector) ** 0.5 or 1.0
            vectors.append([value / norm for value in vector])
        return vectors


class OfflineModel:
    """Extractive stand-in for a chat model.

    Builds an ``AnalystAnswer`` by selecting the evidence sentences that best
    answer the question and quoting them verbatim, citing the chunk they came
    from. It never paraphrases, so it cannot hallucinate a citation -- which
    also means this harness cannot demonstrate the analyst resisting temptation.
    That limitation is the price of running without an API key, and it is why
    the auditor findings from this harness are reported as a plumbing check
    rather than as evidence about model honesty.
    """

    def __init__(self, max_claims: int = 4) -> None:
        self.max_claims = max_claims
        self.calls = 0
        self.input_tokens = 0
        self.output_tokens = 0

    def complete(self, request: Any) -> Any:
        self.calls += 1
        prompt = "\n".join(str(message.get("content", "")) for message in request.messages)
        question, evidence = _parse_prompt(prompt)
        claims = self._claims(question, evidence)
        answer_text = " ".join(claim.text for claim in claims) or "Insufficient evidence."
        parsed = AnalystAnswer(
            answer=answer_text,
            claims=claims,
            limitations=[] if claims else ["No supplied evidence answered the question."],
        )
        input_tokens = max(1, len(prompt) // 4)
        output_tokens = max(1, len(answer_text) // 4)
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        return _Response(parsed, input_tokens, output_tokens)

    def _claims(self, question: str, evidence: list[dict[str, str]]) -> list[Claim]:
        wanted = _tokens(question)
        ranked = []
        for item in evidence:
            for sentence in re.split(r"(?<=[.!?])\s+", item["text"]):
                sentence = sentence.strip()
                if len(sentence) < 25:
                    continue
                overlap = len(wanted & _tokens(sentence))
                if overlap:
                    ranked.append((overlap, sentence, item))
        ranked.sort(key=lambda row: (-row[0], row[1]))

        claims: list[Claim] = []
        seen: set[str] = set()
        for _, sentence, item in ranked:
            if sentence in seen:
                continue
            seen.add(sentence)
            claims.append(Claim(
                id=f"c{len(claims) + 1}",
                text=sentence,
                citations=[Citation(url=item["url"], title=item["title"],
                                    source_id=item["source_id"], chunk_id=item["chunk_id"])],
                confidence="high",
            ))
            if len(claims) == self.max_claims:
                break
        return claims


@dataclass
class _Response:
    parsed: Any
    input_tokens: int
    output_tokens: int
    estimated_cost: float = 0.0
    text: str = ""
    latency_ms: int = 0


def _parse_prompt(prompt: str) -> tuple[str, list[dict[str, str]]]:
    """Recover the question and evidence blocks the analyst formatted."""
    question = ""
    match = re.search(r"^Question:\s*(.+)$", prompt, re.MULTILINE)
    if match:
        question = match.group(1).strip()

    evidence: list[dict[str, str]] = []
    for block in re.split(r"\n\s*\n", prompt):
        if "source_id:" not in block or "url:" not in block:
            continue
        fields = {}
        for key in ("source_id", "chunk_id", "url", "title"):
            found = re.search(rf"^{key}:\s*(.*)$", block, re.MULTILINE)
            fields[key] = (found.group(1).strip() if found else "")
        body = re.search(r"^text:\s*(.*)$", block, re.MULTILINE | re.DOTALL)
        fields["text"] = body.group(1).strip() if body else ""
        if fields["url"]:
            if fields["chunk_id"] in {"", "None"}:
                fields["chunk_id"] = None  # type: ignore[assignment]
            if fields["title"] in {"", "None"}:
                fields["title"] = None  # type: ignore[assignment]
            evidence.append(fields)  # type: ignore[arg-type]
    return question, evidence
