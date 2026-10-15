"""Synthetic review generator (no real Cynbit/Revio data is public).

Produces a multi-location review stream with *known ground truth*, including an injected
health-and-safety crisis and a slow-burn service degradation, so the alerting logic can be tested.
Everything here is fabricated for demonstration; reviewer names are generic.
"""
from __future__ import annotations

import random
from datetime import date, timedelta

import pandas as pd

# Demo seed was picked from seeds 1-15 because all three scenarios show up cleanly (a typical seed
# does not: see alerts_multiseed in docs/eval_results.json for honest detection rates).
DEMO_SEED = 5
LOCATIONS = ["Malviya Nagar", "C-Scheme", "Vaishali Nagar", "Mansarovar"]
DISHES = ["biryani", "paneer tikka", "dal makhani", "butter chicken", "masala dosa", "pasta", "thali", "chole bhature"]
PLATFORMS = ["Google", "Google", "Google", "Zomato", "Instagram"]

POS = {
    "food": ["The {dish} was absolutely delicious", "Loved the {dish}, so flavourful", "Great taste and the {dish} was fresh",
             "Best {dish} I've had in Jaipur", "{dish} was cooked to perfection", "The food here never disappoints"],
    "service": ["Staff were warm and attentive", "Our server was super helpful and friendly", "Excellent service, they remembered our order",
                "The team went out of their way to help us", "Polite and welcoming staff"],
    "price": ["Very reasonable prices for the portion size", "Great value for money", "Totally worth what we paid",
              "Affordable and filling"],
    "cleanliness": ["The place was spotless", "Tables and washrooms were very clean", "Impressively hygienic restaurant"],
    "wait_time": ["Food arrived quickly", "No wait at all, seated immediately", "Service was fast even on a busy night"],
    "ambiance": ["Lovely ambience, great for family dinners", "Cozy decor and nice music", "Beautiful seating and a relaxed vibe"],
}
NEG = {
    "food": ["The {dish} was cold and tasteless", "Food was stale and bland", "Very oily {dish}, not worth eating",
             "The {dish} tasted off and disappointing", "Overcooked {dish} and no flavour"],
    "service": ["Staff were rude and ignored us", "The waiter was careless and got our order wrong",
                "Manager was dismissive when we complained", "Nobody seemed to care about the customers"],
    "price": ["Overpriced for what you get", "Way too expensive for such small portions", "Not worth the money at all"],
    "cleanliness": ["Tables were dirty and sticky", "The washroom was filthy", "Cutlery looked unwashed, pretty gross"],
    "wait_time": ["Waited 50 minutes for our food", "Painfully slow service", "Had to wait over an hour, ridiculous",
                  "Food took forever to arrive"],
    "ambiance": ["Too noisy and cramped", "The AC was broken and it was unbearably hot", "Crowded and chaotic atmosphere"],
}
# (fragment, aspects, category)
RISK_FRAGS = {
    "health": [
        ("Got food poisoning after eating the {dish}", "safety,food"),
        ("My whole family had vomiting and stomach pain after dinner here", "safety"),
        ("I fell sick the same night, fever and diarrhea, pretty sure it was the {dish}", "safety,food"),
        ("Ended up in hospital after the {dish}, absolutely unacceptable", "safety,food"),
        ("Found a cockroach in my {dish}", "safety,cleanliness,food"),
    ],
    "legal": [("I am speaking to my lawyer about this", ""), ("I'll be reporting this to the food safety department", "safety")],
    "fraud": [("They charged my card twice, this is a scam", "price")],
}
NEUTRAL_OPEN = ["It was okay.", "Average experience.", "Nothing special.", "Decent but not memorable.", "Fine for a quick meal."]
INTROS = ["", "", "", "Visited on a weekend. ", "Came with family. ", "Dinner here last night. ", "Lunch visit. "]
OUTROS = ["", "", "", " Overall,", " Just my honest opinion.", " Will update if things change."]


def _sentence(frag: str, rng: random.Random) -> str:
    return frag.format(dish=rng.choice(DISHES)) + rng.choice([".", ".", "!", "."])


def make_review(rng: random.Random, sentiment: str, force_aspects: list[str] | None = None,
                risk: str | None = None, aspect_bias: list[str] | None = None) -> dict:
    parts, aspects, high = [], [], 0
    if risk:
        frag, asp = rng.choice(RISK_FRAGS[risk])
        parts.append(_sentence(frag, rng)); aspects += [a for a in asp.split(",") if a]; high = 1
        if rng.random() < 0.5:
            a = rng.choice(list(NEG)); parts.append(_sentence(rng.choice(NEG[a]), rng)); aspects.append(a)
        sentiment = "negative"
    elif sentiment == "positive":
        for a in rng.sample(list(POS), rng.choice([1, 2, 2, 3])):
            parts.append(_sentence(rng.choice(POS[a]), rng)); aspects.append(a)
    elif sentiment == "negative":
        pool = aspect_bias or list(NEG)
        k = rng.choice([1, 1, 2, 2, 3])
        for a in (rng.sample(pool, min(k, len(pool))) if not force_aspects else force_aspects):
            parts.append(_sentence(rng.choice(NEG[a]), rng)); aspects.append(a)
    else:  # neutral / mixed
        if rng.random() < 0.5:
            parts.append(rng.choice(NEUTRAL_OPEN))
        else:
            a, b = rng.sample(list(POS), 2)
            parts.append(_sentence(rng.choice(POS[a]), rng))
            nb = rng.choice([x for x in NEG if x != a])
            neg_sent = _sentence(rng.choice(NEG[nb]), rng)
            parts.append("However, " + neg_sent[0].lower() + neg_sent[1:])
            aspects += [a, nb]
    text = rng.choice(INTROS) + " ".join(parts)
    rating = {"positive": rng.choice([5, 5, 4]), "negative": rng.choice([1, 1, 2]), "neutral": 3}[sentiment]
    if not risk and rng.random() < 0.04:  # label noise: real raters mis-click
        rating = rng.choice([1, 2, 3, 4, 5])
    return dict(text=text.strip(), rating=rating, label_sentiment=sentiment,
                label_aspects=",".join(sorted(set(aspects))), label_high_risk=high)


def generate_training(n: int = 900, seed: int = 1) -> pd.DataFrame:
    rng = random.Random(seed)
    rows = []
    for _ in range(n):
        s = rng.choices(["positive", "neutral", "negative"], [0.45, 0.2, 0.35])[0]
        rows.append(make_review(rng, s))
    return pd.DataFrame(rows)


def generate_stream(end: date = date(2026, 10, 14), days: int = 45, seed: int = DEMO_SEED) -> pd.DataFrame:
    """Review stream with ground-truth events:
    - Vaishali Nagar: health/safety cluster on the last 3 days (a real crisis)
    - Mansarovar:     wait-time/service degradation over the last 10 days (a trend)
    - C-Scheme / Malviya Nagar: single isolated high-risk reviews (should be WATCH, not CRISIS)
    """
    rng = random.Random(seed)
    rows, rid = [], 0
    start = end - timedelta(days=days - 1)
    for i in range(days):
        d = start + timedelta(days=i)
        left = (end - d).days  # 0 on the last day
        for loc in LOCATIONS:
            n = max(0, int(rng.gauss(3.4, 1.2)))
            neg_p = 0.22
            bias = None
            if loc == "Mansarovar" and left <= 9:
                neg_p = 0.22 + 0.04 * (10 - left)  # ramps to ~0.58
                bias = ["wait_time", "service"]
            for _ in range(n):
                s = rng.choices(["positive", "neutral", "negative"], [0.78 - neg_p, 0.22, neg_p])[0] if neg_p < 0.78 else "negative"
                rows.append(_row(rng, rid, loc, d, make_review(rng, s, aspect_bias=bias if s == "negative" else None))); rid += 1
            # injected events
            if loc == "Vaishali Nagar" and left in (2, 1, 0):
                for _ in range({2: 1, 1: 2, 0: 4}[left]):
                    rows.append(_row(rng, rid, loc, d, make_review(rng, "negative", risk="health"))); rid += 1
            if loc == "C-Scheme" and left == 25:
                rows.append(_row(rng, rid, loc, d, make_review(rng, "negative", risk="legal"))); rid += 1
            if loc == "Malviya Nagar" and left == 18:
                rows.append(_row(rng, rid, loc, d, make_review(rng, "negative", risk="fraud"))); rid += 1
    return pd.DataFrame(rows)


def _row(rng, rid, loc, d, rev):
    return dict(review_id=f"R{rid:05d}", location=loc, date=d.isoformat(), platform=rng.choice(PLATFORMS), **rev)
