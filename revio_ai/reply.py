"""Reply drafting + output guardrails.

Design rule: the LLM never decides *whether* to reply or *what is allowed to be said*. Routing is
decided upstream by deterministic logic; this module drafts text and then a checker enforces policy.
A draft that fails the checker is replaced by a vetted template, so a bad generation cannot reach a customer.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .brand import BrandConfig
from .llm import LLMProvider

_OFFER = re.compile(r"\b(refund\w*|compensat\w*|voucher|discount|reimburs\w*|free (?:meal|dessert|drink)|complimentary)\b", re.I)
_LIABILITY = re.compile(r"\b(our fault|we are responsible|we were responsible|caused by our|our food (?:made|caused)|we admit|we poisoned|we accept (?:blame|liability))\b", re.I)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PHONE = re.compile(r"(?<!\d)(?:\+?\d[\d\s-]{8,}\d)(?!\d)")
_ALLEGATION = re.compile(r"\b(food poison\w*|poisoned|vomit\w*|cockroach\w*|rats?|lawyer|police|scam|fraud|discriminat\w*|allergic|hospital)\b", re.I)

AUTO_ROUTES = {"auto_publish", "human_review", "escalate"}


@dataclass
class Draft:
    text: str
    source: str  # "template" | "llm" | "template_fallback"
    violations: list[str]


def check_reply(reply: str, review_text: str, brand: BrandConfig, risk_level: str = "none") -> list[str]:
    v: list[str] = []
    if len(reply.split()) > brand.max_words:
        v.append(f"too_long(>{brand.max_words} words)")
    if not brand.allow_offers and _OFFER.search(reply):
        v.append("unauthorised_commitment")
    if _LIABILITY.search(reply):
        v.append("admits_liability")
    for e in _EMAIL.findall(reply):
        if e.lower() != brand.contact_email.lower():
            v.append("unknown_contact_email")
    leaked = {m.strip() for m in _PHONE.findall(review_text)}
    if any(p and p in reply for p in leaked) or _PHONE.search(reply):
        v.append("phone_number_in_reply")
    if any(b in reply.lower() for b in brand.banned_phrases):
        v.append("defensive_language")
    if risk_level == "high" and _ALLEGATION.search(reply):
        v.append("repeats_allegation")  # never restate or confirm a serious claim in public
    if not reply.strip():
        v.append("empty")
    return v


def _top_aspects(aspects: list[str]) -> str:
    nice = {"food": "the food", "service": "our service", "price": "pricing", "cleanliness": "cleanliness",
            "wait_time": "wait times", "ambiance": "the ambience", "safety": "safety"}
    names = [nice[a] for a in aspects if a in nice][:2]
    return " and ".join(names)


def template_reply(sentiment: str, aspects: list[str], location: str, risk_level: str, brand: BrandConfig) -> str:
    aspect = _top_aspects(aspects)
    if risk_level == "high":
        return (f"Thank you for telling us. We take this very seriously and want to look into it properly. "
                f"Our {location} manager will contact you personally; you can also write to {brand.contact_email}. "
                f"- {brand.sign_off}")
    if sentiment == "positive":
        about = f" about {aspect}" if aspect else ""
        return (f"Thank you so much for the lovely words{about}! We're delighted you enjoyed your visit to "
                f"{location} and can't wait to welcome you back. - {brand.sign_off}")
    if sentiment == "negative":
        on = f" with {aspect}" if aspect else ""
        return (f"We're sorry your visit to {location} fell short{on}. That isn't the experience we want for you. "
                f"Please write to {brand.contact_email} so we can make this right. - {brand.sign_off}")
    return (f"Thank you for your feedback on {location}. We're always working to do better and would love to hear "
            f"more at {brand.contact_email}. - {brand.sign_off}")


SYSTEM_TMPL = """You write public replies to customer reviews for {brand}, a restaurant brand in Jaipur.
Tone: {tone}. Max {max_words} words. Reply in the language of the review (English, Hindi or Hinglish).
Rules you must follow:
- Use ONLY the facts in the review and analysis; never invent details, names, dishes or events.
- Do NOT offer refunds, discounts, free items or compensation. Do NOT admit legal liability or fault.
- Do NOT repeat or confirm serious allegations (illness, pests, legal threats, discrimination, fraud).
- If risk is 'high': acknowledge, say a manager will contact them, give {email}. Nothing else.
- For complaints: apologise sincerely, acknowledge the specific aspect, offer {email}. Do not argue.
- For praise: thank them, mention one specific thing they liked, invite them back.
- Sign off as "- {sign_off}". Output the reply text only."""

FEWSHOT = """Example 1
Review: "Waited 50 minutes and the waiter was rude." | sentiment=negative | aspects=wait_time,service | risk=none
Reply: We're sorry about the long wait and the way you were treated at {location}; that's not our standard. Please write to {email} so we can look into it. - {sign_off}

Example 2
Review: "Best dosa in the city!" | sentiment=positive | aspects=food | risk=none
Reply: Thank you! We're so glad the dosa hit the spot. See you again soon at {location}. - {sign_off}
"""


def draft_reply(
    review_text: str, sentiment: str, aspects: list[str], location: str, risk_level: str,
    brand: BrandConfig, provider: LLMProvider | None = None,
) -> Draft:
    safe = template_reply(sentiment, aspects, location, risk_level, brand)
    if provider is None:
        return Draft(safe, "template", [])
    system = SYSTEM_TMPL.format(brand=brand.name, tone=brand.tone, max_words=brand.max_words,
                                email=brand.contact_email, sign_off=brand.sign_off)
    user = (FEWSHOT.format(location=location, email=brand.contact_email, sign_off=brand.sign_off)
            + f"\nNow reply to this review at {location}.\nReview: \"\"\"{review_text}\"\"\" | sentiment={sentiment} "
              f"| aspects={','.join(aspects) or 'none'} | risk={risk_level}\nReply:")
    try:
        text = provider.complete(system, user, max_tokens=250)
    except Exception as e:  # network / quota / etc.
        return Draft(safe, "template_fallback", [f"llm_error:{type(e).__name__}"])
    violations = check_reply(text, review_text, brand, risk_level)
    if violations:
        return Draft(safe, "template_fallback", violations)
    return Draft(text, "llm", [])
