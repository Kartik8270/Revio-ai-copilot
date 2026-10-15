"""Per-brand configuration. In production this lives in the tenant settings table."""
from dataclasses import dataclass, field


@dataclass
class BrandConfig:
    name: str = "Spice Route Kitchen"
    contact_email: str = "care@spiceroute.example"
    tone: str = "warm, concise, professional, never defensive"
    max_words: int = 80
    # Offers/compensation are a business decision, so by default the bot may not make them.
    allow_offers: bool = False
    sign_off: str = "Team Spice Route"
    banned_phrases: list[str] = field(default_factory=lambda: ["fake review", "you are lying"])


DEFAULT_BRAND = BrandConfig()
