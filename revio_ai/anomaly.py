"""Location-level crisis / trend detection over a stream of analysed reviews.

Both detectors are evaluated "as of" each day, so results are what an operator would actually
have seen on that day (no look-ahead).

1. CRISIS / WATCH - rule on high-risk reviews. >=2 health/safety reports at one location within 72h
   is a CRISIS (a cluster is far more credible than one claim); any other high-risk review is a
   WATCH (a human should look, but nobody gets paged).
2. TREND - one-sided two-proportion z-test of the trailing-7-day share of reviews that are negative
   *about a specific aspect* (e.g. wait_time) against the location's own prior-28-day baseline,
   (persist_days consecutive days, default 1). Aspect-level beats overall-negative-share because a specific
   complaint has a low baseline rate, so a real shift stands out from noise (see docs/02, section 6).
"""
from __future__ import annotations

import json
import math

import pandas as pd

from .aspects import ASPECTS

ASPECT_NEG_THRESHOLD = -0.25  # clause-level VADER score at/below which an aspect counts as a complaint
_EMPTY = ["first_detected", "last_seen", "location", "kind", "detail"]


def _neg_aspects(df: pd.DataFrame) -> pd.Series:
    def f(js):
        try:
            return {a for a, v in json.loads(js).items() if v <= ASPECT_NEG_THRESHOLD}
        except Exception:
            return set()
    if "aspect_sentiment" not in df:
        return pd.Series([set() for _ in range(len(df))], index=df.index)
    return df["aspect_sentiment"].map(f)


def _two_prop_z(flag_w: pd.Series, flag_b: pd.Series) -> tuple[float, int, float, float]:
    nw, nb = len(flag_w), len(flag_b)
    kw, kb = int(flag_w.sum()), int(flag_b.sum())
    pw, p0 = kw / nw, kb / nb
    pooled = (kw + kb) / (nw + nb)
    se = math.sqrt(max(pooled * (1 - pooled), 0.02) * (1 / nw + 1 / nb))
    return (pw - p0) / se, kw, pw, p0


def detect_alerts(
    df: pd.DataFrame,
    crisis_window_days: int = 3,
    crisis_min_reports: int = 2,
    trend_window: int = 7,
    baseline_days: int = 28,
    z_thresh: float = 3.0,
    persist_days: int = 1,
    min_window_events: int = 4,
    min_window_n: int = 10,
    min_baseline_n: int = 30,
    collapse: bool = True,
) -> pd.DataFrame:
    """Alerts table. Required columns: location, date, sentiment, risk_level, risk_categories;
    optional: aspect_sentiment (JSON) for aspect-level TREND alerts.

    collapse=True -> one row per (location, kind) with first_detected/last_seen;
    collapse=False -> one row per alert-day (used by the evaluation).
    """
    if df.empty:
        return pd.DataFrame(columns=_EMPTY)
    d = df.copy()
    d["day"] = pd.to_datetime(d["date"]).dt.normalize()
    na = _neg_aspects(d)
    for a in ASPECTS:
        d[f"_neg_{a}"] = na.map(lambda s, a=a: a in s)
    days = pd.date_range(d["day"].min(), d["day"].max(), freq="D")
    rows: list[dict] = []

    for loc, g in d.groupby("location"):
        high = g[g["risk_level"] == "high"]
        health = high[high["risk_categories"].str.contains("health_safety", na=False)]
        hits: dict[str, list[bool]] = {k: [] for k in ASPECTS}
        for day in days:
            # ---- risk detector ----
            lo = day - pd.Timedelta(days=crisis_window_days - 1)
            n_health = int(((health["day"] >= lo) & (health["day"] <= day)).sum())
            todays_high = high[high["day"] == day]
            if n_health >= crisis_min_reports:
                rows.append(dict(day=day, location=loc, kind="CRISIS",
                                 detail=f"{n_health} health/safety reports in {crisis_window_days} days"))
            elif len(todays_high):
                cats = sorted({c for s in todays_high["risk_categories"] for c in s.split(",") if c})
                rows.append(dict(day=day, location=loc, kind="WATCH",
                                 detail=f"{len(todays_high)} high-risk review(s): {', '.join(cats)}"))
            # ---- aspect-level trend detector ----
            w = g[(g["day"] > day - pd.Timedelta(days=trend_window)) & (g["day"] <= day)]
            b = g[(g["day"] <= day - pd.Timedelta(days=trend_window)) &
                  (g["day"] > day - pd.Timedelta(days=trend_window + baseline_days))]
            enough = len(w) >= min_window_n and len(b) >= min_baseline_n
            for a in ASPECTS:
                if a == "safety":  # handled by the risk detector, not by rate statistics
                    continue
                hit, z, pw, p0 = False, 0.0, 0.0, 0.0
                if enough:
                    z, kw, pw, p0 = _two_prop_z(w[f"_neg_{a}"], b[f"_neg_{a}"])
                    hit = z >= z_thresh and kw >= min_window_events
                hits[a].append(hit)
                if len(hits[a]) >= persist_days and all(hits[a][-persist_days:]):
                    rows.append(dict(day=day, location=loc, kind=f"TREND:{a}",
                                     detail=f"{a} complaints in {pw:.0%} of reviews vs {p0:.0%} baseline "
                                            f"(z={z:.1f}, n={len(w)}/{trend_window}d)"))
    if not rows:
        return pd.DataFrame(columns=_EMPTY)
    a = pd.DataFrame(rows)
    if not collapse:
        return a.rename(columns={"day": "first_detected"}).sort_values("first_detected").reset_index(drop=True)
    out = (a.sort_values("day").groupby(["location", "kind"], as_index=False)
            .agg(first_detected=("day", "min"), last_seen=("day", "max"), detail=("detail", "last")))
    return out.sort_values(["first_detected", "kind"]).reset_index(drop=True)
