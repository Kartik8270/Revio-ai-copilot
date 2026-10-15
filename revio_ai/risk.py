"""Rule-based risk detector for reviews that need a human, not a bot.

Why rules and not only an ML model: crisis events are rare (a handful per year), so there is
no training data, and the cost of a miss is asymmetric. High-recall, auditable rules are the
right first layer; an LLM/classifier second opinion can be layered on top (see docs).
"""
import re
from dataclasses import dataclass, field

CATEGORIES: dict[str, list[str]] = {
    "health_safety": [
        r"food poison\w*", r"poisoned", r"\bvomit\w*", r"\bdiarrh?o?ea\b",
        r"stomach (?:ache|cramps?|pain|infection)", r"(?:got|fell|felt|was|were|am) (?:very |really )?(?:sick|ill)\b",
        r"\bhospital\w*", r"allergic reaction", r"anaphyla\w*", r"cockroach\w*", r"\brats?\b",
        r"\brodents?\b", r"\bworms?\b", r"\blizards?\b", r"glass (?:piece|shard|in)\w*",
        r"\bulti\b", r"pet dard", r"\bfever\b",
    ],
    "legal_regulatory": [
        r"\blawyer\w*", r"\bsue\b", r"\bsuing\b", r"legal action", r"consumer (?:court|forum)",
        r"\bpolice\b", r"food safety", r"\bfssai\b", r"report(?:ing)? (?:this|it) to",
    ],
    "discrimination_harassment": [
        r"discriminat\w*", r"\bracis[mt]\w*", r"\bharass\w*", r"\bmolest\w*", r"\bthreaten\w*",
    ],
    "fraud_billing": [
        r"\bscam\w*", r"\bfraud\w*", r"charged (?:my card |me |us )?twice", r"double[- ]charged", r"\bcheated\b",
    ],
    "virality_threat": [
        r"tell everyone", r"tag (?:the )?(?:media|zomato|swiggy)", r"go(?:ing)? viral",
        r"post (?:this )?everywhere", r"news channel",
    ],
}
HIGH_CATEGORIES = {"health_safety", "legal_regulatory", "discrimination_harassment", "fraud_billing"}
_COMPILED = {c: [re.compile(p, re.I) for p in ps] for c, ps in CATEGORIES.items()}
_NEGATION = re.compile(r"\b(?:no|not|never|without|zero|nahi|didn'?t|wasn'?t|isn'?t|aren'?t)\b|n't", re.I)


@dataclass
class RiskResult:
    level: str = "none"  # none | medium | high
    categories: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


def _negated(text: str, start: int) -> bool:
    """True if a negation cue appears within ~3 words before the match."""
    prefix = text[max(0, start - 22):start]
    words = prefix.split()[-3:]
    return bool(_NEGATION.search(" ".join(words)))


def assess_risk(text: str) -> RiskResult:
    cats, reasons = [], []
    for cat, patterns in _COMPILED.items():
        for pat in patterns:
            for m in pat.finditer(text):
                if _negated(text, m.start()):
                    continue
                if cat not in cats:
                    cats.append(cat)
                reasons.append(f"{cat}: '{m.group(0)}'")
                break
    if any(c in HIGH_CATEGORIES for c in cats):
        level = "high"
    elif cats:
        level = "medium"
    else:
        level = "none"
    return RiskResult(level, cats, reasons)
