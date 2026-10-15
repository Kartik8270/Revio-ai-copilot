"""Lexicon-based aspect extraction with clause-level aspect sentiment.

This is deliberately the cheap baseline: it runs in microseconds, needs no GPU or API, and is the
fallback when the LLM extractor is unavailable. docs/02 explains where it is expected to fail.
"""
import re

ASPECT_LEXICON: dict[str, list[str]] = {
    "food": [r"\bfood\b", r"\bdish\w*", r"\btast\w+", r"flavou?r\w*", r"biryani", r"paneer", r"\bnaan\b", r"thali",
             r"dosa", r"pasta", r"\bsoup\b", r"coffee", r"dessert", r"gulab jamun", r"chicken", r"\bmenu\b",
             r"portion\w*", r"fries", r"sizzler", r"\bdal\b", r"butter", r"chole", r"bhature", r"khana", r"khaane",
             r"\bstale\b", r"\bbland\b", r"\boily\b", r"greasy", r"sweet", r"delicious"],
    "service": [r"\bstaff\b", r"waiter\w*", r"\bserver\b", r"\bmanager\b", r"\bservice\b", r"\brude\b", r"polite",
                r"friendly", r"attentive", r"reception\w*", r"behaviou?r", r"\bsmile\w*", r"indifferent", r"helpful"],
    "price": [r"\bpric(?:e|es|ed|ey)\b", r"expensive", r"overpriced", r"\bcheap\b", r"\bvalue\b", r"\bbill\b",
              r"rupees", r"\bcost\w*", r"charged", r"paisa", r"worth", r"refund", r"overcharg\w*"],
    "cleanliness": [r"\bclean\w*", r"\bdirty\b", r"filth\w*", r"hygien\w*", r"spotless", r"sticky", r"washrooms?",
                    r"unwashed", r"\bgross\b", r"cockroach\w*", r"\brats?\b"],
    "wait_time": [r"\bwait\w*", r"\bslow\w*", r"\bquick\w*", r"\bminutes?\b", r"\bhour\b", r"\bdelay\w*", r"ghanta",
                  r"\bfast\b", r"\bpromptly\b"],
    "ambiance": [r"ambien?ce", r"\bmusic\b", r"\bdecor\b", r"seating", r"atmosphere", r"crowded", r"\bnois\w+",
                 r"\bloud\b", r"\bcozy\b", r"play area", r"\bAC\b", r"rooftop", r"\bparking\b"],
    "safety": [r"food poison\w*", r"poisoned", r"\bvomit\w*", r"\bdiarrh?o?ea\b", r"\bsick\b", r"\bhospital\w*",
               r"allerg\w*", r"cockroach\w*", r"\brats?\b", r"\bunsafe\b", r"\bulti\b", r"pet dard", r"\bfever\b",
               r"stomach (?:ache|cramps?|pain)"],
}
_COMPILED = {a: [re.compile(p, re.I) for p in ps] for a, ps in ASPECT_LEXICON.items()}
ASPECTS = list(ASPECT_LEXICON)
_CLAUSE_SPLIT = re.compile(r"[.!?;\n]+|\bbut\b|\bhowever\b|\bthough\b|\balthough\b|,", re.I)


def extract_aspects(text: str) -> list[str]:
    return [a for a, pats in _COMPILED.items() if any(p.search(text) for p in pats)]


def aspect_sentiment(text: str, clause_scorer) -> dict[str, float]:
    """Average clause polarity (-1..1) per aspect. `clause_scorer(str) -> float` e.g. VADER compound."""
    scores: dict[str, list[float]] = {}
    for clause in (c.strip() for c in _CLAUSE_SPLIT.split(text)):
        if len(clause) < 3:
            continue
        found = extract_aspects(clause)
        if not found:
            continue
        s = clause_scorer(clause)
        for a in found:
            scores.setdefault(a, []).append(s)
    return {a: round(sum(v) / len(v), 3) for a, v in scores.items()}
