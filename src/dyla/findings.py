"""Report what the auditor actually caught -- including on defects we planted.

Two things live here, and the second exists because of an uncomfortable fact
about the first.

`summarise_verdicts` reports the auditor's real verdicts over a run. On the
offline fixture harness that summary is almost all "supported", and it would be
dishonest to present it as evidence that the auditor works. The offline model is
extractive: it quotes source sentences verbatim, so it is structurally incapable
of the misattribution, drift and invention the auditor exists to catch. A high
support rate there measures the model's inability to lie, not the auditor's
ability to detect lying.

So `run_seeded_defect_audit` does the opposite of hoping for bugs: it injects
known-bad claims into real answers -- one defect class at a time -- and measures
whether the auditor catches each. This is mutation testing pointed at a verifier
instead of a test suite. The detection rate is a property of the auditor and is
meaningful even though the run that produced the answers is a replay.

The defect classes are the failure modes the brief cares about:

  inflated_figure   a number changed enough that the source contradicts it
  swapped_entity    a true statement attached to the wrong company
  dropped_citation  a claim with its sources stripped off
  negated_claim     a claim whose polarity is reversed
  fabricated_claim  a plausible sentence supported by nothing in the source

A defect class the auditor cannot catch is reported as a miss, not omitted.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Sequence

from .domain import AnalystAnswer, Claim

# Verdicts that mean "the auditor objected". "unsupported" counts: the auditor
# declining to vouch for a planted defect is a catch, not a failure -- it is the
# honest answer when the evidence does not settle the matter.
OBJECTION_STATUSES = frozenset({"contradicted", "unsupported", "uncited"})

_NUMBER = re.compile(r"\d[\d,]*\.?\d*")


@dataclass(frozen=True)
class SeededDefect:
    """One planted defect and what the auditor made of it."""

    defect_class: str
    original: str
    mutated: str
    status: str
    caught: bool
    explanation: str


@dataclass
class DefectAuditResult:
    defects: list[SeededDefect] = field(default_factory=list)

    @property
    def caught(self) -> int:
        return sum(1 for defect in self.defects if defect.caught)

    @property
    def total(self) -> int:
        return len(self.defects)

    def by_class(self) -> dict[str, tuple[int, int]]:
        """defect_class -> (caught, total), in a stable order."""
        tally: dict[str, tuple[int, int]] = {}
        for defect in self.defects:
            caught, total = tally.get(defect.defect_class, (0, 0))
            tally[defect.defect_class] = (caught + int(defect.caught), total + 1)
        return tally


def _inflate_number(text: str) -> str | None:
    """Multiply the first number by ten, which no rounding tolerance forgives."""
    match = _NUMBER.search(text)
    if match is None:
        return None
    raw = match.group(0)
    try:
        value = float(raw.replace(",", ""))
    except ValueError:
        return None
    if value == 0:
        return None
    inflated = value * 10
    rendered = f"{inflated:,.0f}" if inflated.is_integer() else f"{inflated:,.2f}"
    return text[: match.start()] + rendered + text[match.end() :]


def _swap_entity(text: str, others: Sequence[str]) -> str | None:
    """Reattach the statement to a different company mentioned in the suite."""
    for name in others:
        if re.search(rf"\b{re.escape(name)}\b", text):
            replacement = next((o for o in others if o != name), None)
            if replacement is None:
                return None
            return re.sub(rf"\b{re.escape(name)}\b", replacement, text, count=1)
    return None


_NEGATIONS = (
    (r"\bis\b", "is not"),
    (r"\bwas\b", "was not"),
    (r"\bare\b", "are not"),
    (r"\bhas\b", "has not"),
    (r"\braised\b", "did not raise"),
    (r"\bprofitable\b", "unprofitable"),
)


def _negate(text: str) -> str | None:
    for pattern, replacement in _NEGATIONS:
        if re.search(pattern, text):
            return re.sub(pattern, replacement, text, count=1)
    return None


_FABRICATION = (
    "The company announced a secondary listing on the Singapore Exchange "
    "in the same quarter."
)


def _mutations(
    claim: Claim, entity_names: Sequence[str]
) -> Iterable[tuple[str, Claim]]:
    """Yield (defect_class, mutated_claim) for every mutation that applies."""
    inflated = _inflate_number(claim.text)
    if inflated is not None:
        yield "inflated_figure", claim.model_copy(update={"text": inflated})

    swapped = _swap_entity(claim.text, entity_names)
    if swapped is not None:
        yield "swapped_entity", claim.model_copy(update={"text": swapped})

    if claim.citations:
        yield "dropped_citation", claim.model_copy(update={"citations": []})

    negated = _negate(claim.text)
    if negated is not None:
        yield "negated_claim", claim.model_copy(update={"text": negated})

    if claim.citations:
        yield "fabricated_claim", claim.model_copy(update={"text": _FABRICATION})


def run_seeded_defect_audit(
    *,
    answers: Sequence[AnalystAnswer],
    audit: Callable[[AnalystAnswer, str], Sequence[Any]],
    entity_names: Sequence[str] = ("Zerodha", "Infosys", "Wipro", "Zepto"),
    per_class_limit: int = 4,
) -> DefectAuditResult:
    """Plant defects in real answers and record what the auditor says.

    Each mutated claim is audited *alone*, in a one-claim answer. Auditing a
    batch would let a neighbouring healthy claim's sources vouch for the
    defective one -- the same cross-source masking that made the auditor useless
    before, and exactly the mistake this function must not repeat.
    """
    result = DefectAuditResult()
    seen: Counter[str] = Counter()

    for answer_index, answer in enumerate(answers):
        for claim in answer.claims:
            for defect_class, mutated in _mutations(claim, entity_names):
                if seen[defect_class] >= per_class_limit:
                    continue
                seen[defect_class] += 1
                probe = AnalystAnswer(
                    answer=mutated.text, claims=[mutated], limitations=[]
                )
                run_id = f"seeded-{defect_class}-{answer_index}-{seen[defect_class]}"
                verdicts = audit(probe, run_id)
                verdict = verdicts[0] if verdicts else None
                status = getattr(verdict, "status", "no-verdict")
                result.defects.append(
                    SeededDefect(
                        defect_class=defect_class,
                        original=claim.text,
                        mutated=mutated.text,
                        status=status,
                        caught=status in OBJECTION_STATUSES,
                        explanation=getattr(verdict, "explanation", ""),
                    )
                )
    return result


def summarise_verdicts(results: Sequence[dict]) -> dict:
    """Tally the auditor's real verdicts over an evaluation report."""
    counts: Counter[str] = Counter()
    per_question = []
    for index, row in enumerate(results, start=1):
        verdicts = row.get("verdicts", [])
        question_counts = Counter(v["status"] for v in verdicts)
        counts.update(question_counts)
        per_question.append(
            {
                "number": index,
                "question": row.get("question", ""),
                "status": row.get("status", ""),
                "claims": len(verdicts),
                "counts": dict(question_counts),
                "objections": [
                    v for v in verdicts if v["status"] in OBJECTION_STATUSES
                ],
            }
        )
    return {"totals": dict(counts), "questions": per_question}


def _truncate(text: str, limit: int = 110) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def build_findings_markdown(
    *, summary: dict, defects: DefectAuditResult, mode: str
) -> str:
    """Render Part B's deliverable: what the auditor caught, and what it missed."""
    totals = summary["totals"]
    total_claims = sum(totals.values())
    objections = sum(totals.get(s, 0) for s in OBJECTION_STATUSES)

    lines = [
        "# What the auditor caught",
        "",
        f"Run mode: **{mode}**.",
        "",
        "## 1. Verdicts on the analyst's own answers",
        "",
        f"- Claims audited: **{total_claims}** across "
        f"{len(summary['questions'])} questions",
        f"- Auditor objected to: **{objections}**",
        "",
        "| Verdict | Claims |",
        "| --- | --- |",
    ]
    for status in ("supported", "unsupported", "contradicted", "uncited"):
        lines.append(f"| {status} | {totals.get(status, 0)} |")

    lines += ["", "| # | Question | Result | Claims | Objections |", "| --- | --- | --- | --- | --- |"]
    for row in summary["questions"]:
        lines.append(
            f"| {row['number']} | {_truncate(row['question'], 70)} | {row['status']} "
            f"| {row['claims']} | {len(row['objections'])} |"
        )

    lines += ["", "### Every objection, in full", ""]
    any_objection = False
    for row in summary["questions"]:
        for verdict in row["objections"]:
            any_objection = True
            lines += [
                f"**Q{row['number']} · {verdict['status']}** — {verdict['text']}",
                "",
                f"> {_truncate(verdict['explanation'], 600)}",
                "",
            ]
    if not any_objection:
        lines += ["_The auditor raised no objections on this run._", ""]

    lines += [
        "## 2. Seeded defects",
        "",
        "A support rate near 100% is not evidence that the auditor works. On the",
        "offline harness the analyst model is extractive -- it quotes source",
        "sentences verbatim -- so it *cannot* misattribute, drift or invent. The",
        "section above therefore measures the model's inability to lie, not the",
        "auditor's ability to detect lying.",
        "",
        "To measure the auditor itself, known-bad claims are planted in the real",
        "answers, one defect class at a time, and each is audited alone. Auditing",
        "them in a batch would let a healthy neighbour's sources vouch for the",
        "defective claim -- the cross-source masking bug that made this auditor",
        "useless in the first place.",
        "",
        f"**Detection rate: {defects.caught}/{defects.total} "
        f"({(100 * defects.caught / defects.total) if defects.total else 0:.0f}%)**",
        "",
        "| Defect class | Caught | Planted | Detection |",
        "| --- | --- | --- | --- |",
    ]
    for defect_class, (caught, total) in defects.by_class().items():
        rate = f"{100 * caught / total:.0f}%" if total else "n/a"
        lines.append(f"| `{defect_class}` | {caught} | {total} | {rate} |")

    misses = [d for d in defects.defects if not d.caught]
    lines += ["", "### Misses", ""]
    if misses:
        lines += [
            "These are the planted defects the auditor waved through. They are the",
            "honest limit of what it can do today.",
            "",
            "| Defect class | Verdict | Planted claim |",
            "| --- | --- | --- |",
        ]
        for defect in misses:
            lines.append(
                f"| `{defect.defect_class}` | {defect.status} | {_truncate(defect.mutated, 90)} |"
            )
    else:
        lines.append("_Every planted defect was caught._")

    lines += [
        "",
        "### Examples of catches",
        "",
    ]
    shown: set[str] = set()
    for defect in defects.defects:
        if defect.caught and defect.defect_class not in shown:
            shown.add(defect.defect_class)
            lines += [
                f"**`{defect.defect_class}` → {defect.status}**",
                "",
                f"- Original: {_truncate(defect.original, 140)}",
                f"- Planted: {_truncate(defect.mutated, 140)}",
                f"- Auditor: {_truncate(defect.explanation, 400)}",
                "",
            ]
    return "\n".join(lines).rstrip() + "\n"
