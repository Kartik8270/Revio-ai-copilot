"""Reproducible evaluation. Run: python -m revio_ai.evaluate  (writes docs/eval_results.json)

Three questions, three honest answers:
  1. Text models: how well do they classify sentiment on a *hand-written* held-out set?
  2. Safety:     does anything high-risk ever get auto-published? Is risk recall acceptable?
  3. Alerts:     on a stream with injected ground-truth events, are they found, early, without false alarms?
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, precision_recall_fscore_support

from .anomaly import detect_alerts
from .aspects import ASPECTS, extract_aspects
from .brand import DEFAULT_BRAND
from .gold_data import CHALLENGE_RISK, GOLD
from .pipeline import process_dataframe
from .risk import assess_risk
from .sentiment import LABELS, SentimentModel, vader_label
from .synth import generate_stream, generate_training

ROOT = Path(__file__).resolve().parent.parent


def gold_df() -> pd.DataFrame:
    df = pd.DataFrame(GOLD, columns=["text", "rating", "sentiment", "aspects", "high_risk"])
    df["location"] = "Vaishali Nagar"
    return df


def rating_label(r: float) -> str:
    return "positive" if r >= 4 else "negative" if r <= 2 else "neutral"


def _sent_metrics(y, p) -> dict:
    return {"accuracy": round(accuracy_score(y, p), 3), "macro_f1": round(f1_score(y, p, average="macro", labels=LABELS), 3),
            "confusion(rows=true,cols=pred;neg,neu,pos)": confusion_matrix(y, p, labels=LABELS).tolist()}


def alert_multiseed(model: SentimentModel, seeds) -> dict:
    drift = pd.Timestamp("2026-10-05")
    crisis_day = pd.Timestamp("2026-10-13")  # second health report at Vaishali Nagar
    n = c_hit = c_on_time = false_crisis = t_hit = 0
    lags, false_trend_runs, watch_ok = [], 0, 0
    for seed in seeds:
        n += 1
        proc = process_dataframe(generate_stream(seed=seed), model, DEFAULT_BRAND)
        a = detect_alerts(proc, collapse=False)
        cr = a[a.kind == "CRISIS"]
        v = cr[cr.location == "Vaishali Nagar"]
        c_hit += len(v) > 0
        c_on_time += bool(len(v) and v.first_detected.min() <= crisis_day)
        false_crisis += int((cr.location != "Vaishali Nagar").any())
        t = a[a.kind.str.startswith("TREND")]
        good = t[(t.location == "Mansarovar") & (t.first_detected >= drift) & t.kind.isin(["TREND:wait_time", "TREND:service"])]
        t_hit += len(good) > 0
        if len(good):
            lags.append(int((good.first_detected.min() - drift).days))
        bad = t[~((t.location == "Mansarovar") & (t.first_detected >= drift))]
        false_trend_runs += bad.location.nunique() if len(bad) else 0
    return {"n_streams": n, "crisis_detected": f"{c_hit}/{n}", "crisis_detected_by_2nd_report_day": f"{c_on_time}/{n}",
            "streams_with_false_crisis": false_crisis, "trend_detected_at_mansarovar": f"{t_hit}/{n}",
            "median_days_after_drift_start": float(np.median(lags)) if lags else None,
            "false_trend_alerts_location_runs": f"{false_trend_runs}/{4 * n}",
            "note": "tuned on seeds 100-115, reported on unseen seeds 200-229; synthetic data from my own generator"}


def evaluate() -> dict:
    train = generate_training()
    gold = gold_df()
    res: dict = {"n_train_synthetic": len(train), "n_gold": len(gold)}

    # 1. sentiment -------------------------------------------------
    models = {"tfidf_lr": SentimentModel("tfidf").fit(train.text, train.label_sentiment),
              "hybrid_tfidf_vader_lr": SentimentModel("hybrid").fit(train.text, train.label_sentiment)}
    sent = {"vader_default": _sent_metrics(gold.sentiment, [vader_label(t) for t in gold.text])}
    for k, m in models.items():
        sent[k] = _sent_metrics(gold.sentiment, m.predict(gold.text))
    res["sentiment"] = sent
    hybrid = models["hybrid_tfidf_vader_lr"]

    # slice: Hinglish rows (last-but-few); mark by simple heuristic list
    hinglish = gold.text.str.contains(r"\b(?:khana|bahut|khaane|paisa|ekdum|zaroor)\b", case=False)
    res["sentiment_hinglish_slice"] = {"n": int(hinglish.sum()),
                                       "hybrid_accuracy": round(accuracy_score(gold.sentiment[hinglish], hybrid.predict(gold.text[hinglish])), 3),
                                       "vader_accuracy": round(accuracy_score(gold.sentiment[hinglish], [vader_label(t) for t in gold.text[hinglish]]), 3)}

    # 2. aspects + risk --------------------------------------------
    tp = fp = fn = 0
    for t, a in zip(gold.text, gold.aspects):
        truth, pred = set(filter(None, a.split(","))), set(extract_aspects(t))
        tp += len(truth & pred); fp += len(pred - truth); fn += len(truth - pred)
    p, r = tp / (tp + fp), tp / (tp + fn)
    res["aspects_micro"] = {"precision": round(p, 3), "recall": round(r, 3), "f1": round(2 * p * r / (p + r), 3)}

    pred_risk = np.array([assess_risk(t).level == "high" for t in gold.text], dtype=int)
    pr, rc, f1, _ = precision_recall_fscore_support(gold.high_risk, pred_risk, average="binary", zero_division=0)
    res["risk_detector"] = {"precision": round(pr, 3), "recall": round(rc, 3), "f1": round(f1, 3),
                            "true_positives": int(((pred_risk == 1) & (gold.high_risk == 1)).sum()),
                            "false_positives": int(((pred_risk == 1) & (gold.high_risk == 0)).sum()),
                            "false_negatives": int(((pred_risk == 0) & (gold.high_risk == 1)).sum())}

    ch = pd.DataFrame(CHALLENGE_RISK, columns=["text", "high_risk"])
    cp = np.array([assess_risk(t).level == "high" for t in ch.text], dtype=int)
    pr, rc, f1, _ = precision_recall_fscore_support(ch.high_risk, cp, average="binary", zero_division=0)
    res["risk_detector_challenge_set"] = {
        "n": len(ch), "n_high_risk": int(ch.high_risk.sum()), "precision": round(pr, 3), "recall": round(rc, 3), "f1": round(f1, 3),
        "missed": ch.text[(cp == 0) & (ch.high_risk == 1)].tolist(), "false_alarms": ch.text[(cp == 1) & (ch.high_risk == 0)].tolist(),
        "note": "written after rules were frozen; small n, so treat as indicative only"}

    # 3. end-to-end routing safety on gold --------------------------
    out = process_dataframe(gold[["text", "rating", "location"]], hybrid, DEFAULT_BRAND)
    auto_idx = out.index[out.route == "auto_publish"]
    truth = gold.loc[auto_idx]
    esc_idx = out.index[out.route == "escalate"]
    res["routing_gold"] = {
        "route_counts": out.route.value_counts().to_dict(),
        "high_risk_reviews_auto_published": int(truth.high_risk.sum()),
        "negative_reviews_auto_published": int((truth.sentiment == "negative").sum()),
        "auto_publish_precision_truly_positive": round(float((truth.sentiment == "positive").mean()), 3) if len(truth) else None,
        "auto_publish_share": round(len(auto_idx) / len(out), 3),
        "escalated_that_were_truly_high_risk": f"{int(gold.loc[esc_idx].high_risk.sum())}/{len(esc_idx)}",
        "template_draft_guardrail_violations": int((out.draft_violations != "").sum()),
    }

    # 4. alerts on the default demo stream (seed 7) ------------------
    proc = process_dataframe(generate_stream(), hybrid, DEFAULT_BRAND)
    alerts = detect_alerts(proc)
    c = alerts[alerts.kind == "CRISIS"]
    res["alerts_demo_stream"] = {
        "n_reviews": len(proc),
        "alerts": alerts.astype({"first_detected": str, "last_seen": str})[["location", "kind", "first_detected", "detail"]].to_dict("records"),
        "crisis_detected_at_vaishali": bool((c.location == "Vaishali Nagar").any()),
    }
    # 5. alerts, many seeds. Thresholds were tuned on seeds 100-115; report on UNSEEN seeds 200-229
    res["alerts_multiseed"] = alert_multiseed(hybrid, range(200, 230))
    return res


if __name__ == "__main__":
    r = evaluate()
    (ROOT / "docs" / "eval_results.json").write_text(json.dumps(r, indent=2, default=str))
    print(json.dumps(r, indent=2, default=str))
