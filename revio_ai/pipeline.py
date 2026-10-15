"""End-to-end review pipeline: analyse -> route -> draft -> guardrail."""
from __future__ import annotations

import json
from dataclasses import dataclass, field

import pandas as pd

from .aspects import aspect_sentiment, extract_aspects
from .brand import DEFAULT_BRAND, BrandConfig
from .llm import LLMProvider
from .llm_risk import combine, llm_second_opinion
from .reply import check_reply, draft_reply, template_reply
from .risk import assess_risk
from .sentiment import SentimentModel, vader_compound

CONF_THRESHOLD = 0.60


@dataclass
class Analysis:
    sentiment: str
    confidence: float
    aspects: list[str]
    aspect_sentiment: dict[str, float]
    risk_level: str
    risk_categories: list[str]
    risk_reasons: list[str]
    flags: list[str] = field(default_factory=list)
    route: str = "human_review"  # auto_publish | human_review | escalate


def route(sentiment: str, confidence: float, risk_level: str, rating: float | None, flags: list[str]) -> str:
    """Deterministic routing policy. The model never gets to decide that a risky review is safe."""
    if risk_level == "high":
        return "escalate"
    if sentiment == "positive" and confidence >= CONF_THRESHOLD and risk_level == "none" \
            and (rating is None or rating >= 4) and not flags:
        return "auto_publish"
    return "human_review"


def analyze(text: str, model: SentimentModel, rating: float | None = None,
            provider: LLMProvider | None = None) -> Analysis:
    proba = model.predict_proba([text])[0]
    label, conf = max(proba.items(), key=lambda kv: kv[1])
    risk = assess_risk(text)
    flags: list[str] = []
    if provider is not None:  # LLM second opinion; union with rules, never a downgrade
        combined = combine(risk, llm_second_opinion(provider, text))
        if risk.level != "high" and combined.level == "high":
            flags.append("llm_only_escalation")
        risk = combined
    if rating is not None and ((label == "positive" and rating <= 2) or (label == "negative" and rating >= 4)):
        flags.append("rating_text_mismatch")  # sarcasm / mis-click / model error: send to a human
    if conf < CONF_THRESHOLD:
        flags.append("low_confidence")
    aspects = extract_aspects(text)
    if risk.level == "high" and "health_safety" in risk.categories and "safety" not in aspects:
        aspects.append("safety")
    return Analysis(
        sentiment=label, confidence=round(conf, 3), aspects=aspects,
        aspect_sentiment=aspect_sentiment(text, vader_compound),
        risk_level=risk.level, risk_categories=risk.categories, risk_reasons=risk.reasons,
        flags=flags, route=route(label, conf, risk.level, rating, flags),
    )


def process_dataframe(
    df: pd.DataFrame, model: SentimentModel, brand: BrandConfig = DEFAULT_BRAND,
) -> pd.DataFrame:
    """Analyse every review and attach a *template* draft (cheap, offline). LLM drafts are on demand."""
    recs = []
    for r in df.itertuples(index=False):
        rating = getattr(r, "rating", None)
        a = analyze(r.text, model, None if pd.isna(rating) else float(rating))
        draft = template_reply(a.sentiment, a.aspects, r.location, a.risk_level, brand)
        recs.append({
            "sentiment": a.sentiment, "confidence": a.confidence,
            "aspects": ",".join(a.aspects), "aspect_sentiment": json.dumps(a.aspect_sentiment),
            "risk_level": a.risk_level, "risk_categories": ",".join(a.risk_categories),
            "risk_reasons": "; ".join(a.risk_reasons), "flags": ",".join(a.flags),
            "route": a.route, "draft_reply": draft,
            "draft_violations": ",".join(check_reply(draft, r.text, brand, a.risk_level)),
        })
    return pd.concat([df.reset_index(drop=True), pd.DataFrame(recs)], axis=1)


def llm_draft(row: dict, brand: BrandConfig, provider: LLMProvider | None):
    return draft_reply(row["text"], row["sentiment"], [a for a in row["aspects"].split(",") if a],
                       row["location"], row["risk_level"], brand, provider)
