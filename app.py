"""Revio Intelligence: Streamlit demo.   Run:  streamlit run app.py"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

from revio_ai.anomaly import detect_alerts
from revio_ai.brand import BrandConfig
from revio_ai.llm import get_provider
from revio_ai.pipeline import analyze, llm_draft, process_dataframe
from revio_ai.reply import check_reply, template_reply
from revio_ai.sentiment import SentimentModel
from revio_ai.synth import LOCATIONS, generate_stream, generate_training

ROOT = Path(__file__).parent
st.set_page_config(page_title="Revio Intelligence (PoC)", page_icon="⭐", layout="wide")


@st.cache_resource(show_spinner="Training sentiment model on synthetic data...")
def get_model() -> SentimentModel:
    t = generate_training()
    return SentimentModel("hybrid").fit(t.text, t.label_sentiment)


@st.cache_resource
def provider():
    return get_provider()


@st.cache_data(show_spinner="Analysing reviews...")
def run_pipeline(df: pd.DataFrame, brand_name: str, contact: str) -> pd.DataFrame:
    return process_dataframe(df, get_model(), BrandConfig(name=brand_name, contact_email=contact))


def load_input(upload) -> pd.DataFrame:
    if upload is None:
        return generate_stream()
    df = pd.read_csv(upload)
    need = {"text", "location", "date"}
    if not need <= set(df.columns):
        st.error(f"CSV needs columns {sorted(need)} (optional: rating, review_id, platform).")
        st.stop()
    if "rating" not in df:
        df["rating"] = float("nan")
    if "review_id" not in df:
        df["review_id"] = [f"U{i:05d}" for i in range(len(df))]
    return df


# ---------------------------------------------------------------- sidebar
st.sidebar.title("Revio Intelligence")
st.sidebar.caption("PoC for Cynbit's Revio: review triage, crisis alerts, guard-railed replies")
upload = st.sidebar.file_uploader("Reviews CSV (text, location, date[, rating])", type="csv")
brand_name = st.sidebar.text_input("Brand name", "Spice Route Kitchen")
contact = st.sidebar.text_input("Brand contact email", "care@spiceroute.example")
prov = provider()
st.sidebar.info(f"LLM: **{prov.name if prov else 'offline (templates only)'}**\n\n"
                "Set `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` to enable LLM drafts and the risk second opinion.")
st.sidebar.caption("Demo data is synthetic. No real customer data is used.")

brand = BrandConfig(name=brand_name, contact_email=contact)
raw = load_input(upload)
df = run_pipeline(raw, brand_name, contact)
alerts = detect_alerts(df)

tab_over, tab_alerts, tab_inbox, tab_try, tab_eval = st.tabs(
    ["Overview", "Alerts", "Reply inbox", "Try a review", "Evaluation"])

# ---------------------------------------------------------------- overview
with tab_over:
    c = st.columns(4)
    c[0].metric("Reviews", len(df))
    c[1].metric("Negative", f"{(df.sentiment == 'negative').mean():.0%}")
    c[2].metric("Escalated (high risk)", int((df.route == "escalate").sum()))
    c[3].metric("Safe to auto-publish", f"{(df.route == 'auto_publish').mean():.0%}")
    left, right = st.columns(2)
    with left:
        st.subheader("Sentiment by location")
        st.bar_chart(pd.crosstab(df.location, df.sentiment, normalize="index")
                     .reindex(columns=["negative", "neutral", "positive"], fill_value=0))
    with right:
        st.subheader("Daily negative share (7-day rolling)")
        d = df.assign(day=pd.to_datetime(df.date), neg=(df.sentiment == "negative").astype(float))
        piv = d.pivot_table(index="day", columns="location", values="neg", aggfunc="mean")
        st.line_chart(piv.rolling(7, min_periods=3).mean())
    st.subheader("What are customers complaining about? (share of reviews with a negative mention)")
    rows = []
    for loc, g in df.groupby("location"):
        cnt: dict[str, float] = {}
        for js in g.aspect_sentiment:
            for a, v in json.loads(js).items():
                cnt[a] = cnt.get(a, 0) + (v <= -0.25)
        rows.append({"location": loc, **{a: v / len(g) for a, v in cnt.items()}})
    heat = pd.DataFrame(rows).set_index("location").fillna(0)
    st.dataframe(heat.style.format("{:.0%}").background_gradient(cmap="Reds", axis=None), width="stretch")

# ---------------------------------------------------------------- alerts
with tab_alerts:
    st.subheader("Operator alerts")
    if alerts.empty:
        st.success("No alerts.")
    for r in alerts.itertuples():
        msg = f"**{r.kind}** · {r.location} · first detected {r.first_detected:%d %b} · {r.detail}"
        (st.error if r.kind == "CRISIS" else st.warning if r.kind.startswith("TREND") else st.info)(msg)
    st.caption("CRISIS = 2+ health/safety reports at one location within 3 days. WATCH = a single high-risk review. "
               "TREND = aspect-specific complaint rate significantly above that location's own baseline (z-test). "
               "On synthetic data, trend detection finds a real shift in about 2/3 of streams with ~14% false alarms; "
               "see docs/02 for the honest numbers.")

# ---------------------------------------------------------------- inbox
with tab_inbox:
    f1, f2, f3 = st.columns(3)
    route_f = f1.multiselect("Route", ["escalate", "human_review", "auto_publish"], default=["escalate", "human_review"])
    loc_f = f2.multiselect("Location", sorted(df.location.unique()), default=sorted(df.location.unique()))
    n_show = f3.slider("Rows", 5, 100, 25)
    view = df[df.route.isin(route_f) & df.location.isin(loc_f)].sort_values(
        ["date"], ascending=False).head(n_show).reset_index(drop=True)
    st.dataframe(view[["date", "location", "rating", "sentiment", "risk_level", "route", "text"]], width="stretch", height=260)
    if len(view):
        i = st.number_input("Open row #", 0, len(view) - 1, 0)
        row = view.iloc[int(i)].to_dict()
        a, b = st.columns(2)
        with a:
            st.markdown(f"**{row['location']}** · {row['date']} · rating {row['rating']}")
            st.write(row["text"])
            st.markdown(f"Sentiment: `{row['sentiment']}` ({row['confidence']:.2f}) · Aspects: `{row['aspects'] or '-'}`")
            st.markdown(f"Risk: `{row['risk_level']}` {row['risk_reasons']}  \nFlags: `{row['flags'] or '-'}`")
        with b:
            if row["route"] == "escalate":
                st.error("ESCALATE: never auto-posted. Notify the location manager; the draft below is a holding reply only.")
            elif row["route"] == "auto_publish":
                st.success("Low-risk positive review: eligible for auto-publish.")
            else:
                st.warning("Needs human approval before posting.")
            key = f"draft_{row['review_id']}"
            if st.button("Regenerate with LLM", disabled=prov is None, help=None if prov else "No LLM key configured"):
                d = llm_draft(row, brand, prov)
                st.session_state[key] = d.text
                st.caption(f"source: {d.source}" + (f" · guardrail violations: {d.violations}" if d.violations else ""))
            text = st.text_area("Draft reply (editable)", st.session_state.get(key, row["draft_reply"]), height=140)
            v = check_reply(text, row["text"], brand, row["risk_level"])
            st.markdown("Guardrails: " + ("✅ pass" if not v else "❌ " + ", ".join(v)))
            st.button("Approve & publish (simulated)", disabled=bool(v) or row["route"] == "escalate",
                      help="Escalated reviews go to the location manager, never auto-posted" if row["route"] == "escalate" else None)

# ---------------------------------------------------------------- try
with tab_try:
    st.subheader("Paste any review")
    txt = st.text_area("Review text", "The biryani was great but we waited 50 minutes and the waiter was rude.")
    c1, c2 = st.columns(2)
    stars = c1.slider("Star rating (optional)", 1, 5, 3)
    loc = c2.selectbox("Location", LOCATIONS)
    if txt.strip():
        an = analyze(txt, get_model(), float(stars), prov)
        st.json({"sentiment": an.sentiment, "confidence": an.confidence, "aspects": an.aspects,
                 "aspect_sentiment": an.aspect_sentiment, "risk": an.risk_level, "risk_reasons": an.risk_reasons,
                 "flags": an.flags, "route": an.route})
        d = llm_draft({"text": txt, "sentiment": an.sentiment, "aspects": ",".join(an.aspects),
                       "location": loc, "risk_level": an.risk_level}, brand, prov)
        st.markdown(f"**Draft reply** (source: `{d.source}`)")
        st.info(d.text)
        if d.violations:
            st.caption(f"LLM draft rejected by guardrails: {d.violations}; safe template used instead.")

# ---------------------------------------------------------------- evaluation
with tab_eval:
    p = ROOT / "docs" / "eval_results.json"
    if p.exists():
        r = json.loads(p.read_text())
        st.subheader("Sentiment on 60 hand-written held-out reviews")
        st.dataframe(pd.DataFrame({k: {"accuracy": v["accuracy"], "macro-F1": v["macro_f1"]}
                                   for k, v in r["sentiment"].items()}).T)
        st.subheader("Risk rules")
        st.json({"gold_set": r["risk_detector"], "challenge_set_unseen_phrasing": r["risk_detector_challenge_set"]})
        st.subheader("Alerting on 30 unseen synthetic streams")
        st.json(r["alerts_multiseed"])
        st.caption("Regenerate with `python -m revio_ai.evaluate`.")
    else:
        st.info("Run `python -m revio_ai.evaluate` to create docs/eval_results.json")
