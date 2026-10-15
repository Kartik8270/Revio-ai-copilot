# Revio Intelligence: AI/ML proof of concept for Cynbit

Submission for the **Cynbit AI/ML Engineer Intern** task, *"Identify an AI Opportunity for Cynbit"*, by Kartik Jain.

**Chosen opportunity:** an AI layer for **Revio**, Cynbit's review-management product. It analyses reviews, escalates anything serious to a human, drafts policy-checked replies, and alerts operators to location-level crises and trends. The Revio site names "AI replies, sentiment and crisis detection" without describing a method; this PoC makes them concrete and measurable.

| Deliverable | Where |
|---|---|
| AI Opportunity Report | [`docs/01_AI_Opportunity_Report.md`](docs/01_AI_Opportunity_Report.md) |
| Proof of concept (Streamlit app + Python package + tests) | `app.py`, `revio_ai/`, `tests/` |
| Technical Approach Report | [`docs/02_Technical_Approach_Report.md`](docs/02_Technical_Approach_Report.md) |
| Evaluation output | [`docs/eval_results.json`](docs/eval_results.json) (regenerate: `python -m revio_ai.evaluate`) |

## Run it

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m pytest -q                 # 27 tests
streamlit run app.py                # demo UI (works fully offline)
python -m revio_ai.evaluate         # reproduces every number in the reports (~1 min)
```

Optional LLM mode (drafting and risk second opinion): set `ANTHROPIC_API_KEY` **or** `OPENAI_API_KEY`
(optionally `REVIO_LLM_PROVIDER=anthropic|openai`, `REVIO_LLM_MODEL=...`). With no key, the app uses vetted templates.
Deploys as-is on Streamlit Community Cloud (entry point `app.py`).

Upload your own CSV in the sidebar with columns `text, location, date` (optional `rating, review_id, platform`).

## What it does

```
review → sentiment + aspects + risk (rules ∪ LLM) → deterministic routing → draft → guardrail check → human inbox
                                                      escalate / human_review / auto_publish
reviews over time → per-location alerts: CRISIS (≥2 health/safety reports in 72h) · WATCH · TREND:<aspect>
```

Design rule: **the LLM drafts text, it never decides policy.** Routing is deterministic; a guardrail checker runs after generation; any failure falls back to a vetted template.

## Results (honest summary; details and caveats in report 02)

| Check | Result | Caveat |
|---|---|---|
| Sentiment, 60 hand-written reviews | 73% accuracy (hybrid TF-IDF+VADER LR); VADER alone 58% | Small n (95% CI 61-83%); Hinglish 1/4; sarcasm fails. Not production quality |
| High-risk review auto-published | 0 of 11 | Rules written with this set in view |
| Risk rules on rephrased unseen cases | **recall 1/8**, 5 false alarms in 8 look-alikes | Why an LLM second opinion is part of the design |
| Crisis cluster detection (30 unseen simulated streams) | 30/30 on time, 0 false crises | Synthetic data from my own generator |
| Aspect-level trend detection | 20/30 streams, ~14% false-alarm location-runs | Low review volume limits power |

## Data

No real Cynbit or customer data was used. `data/` holds synthetic training/demo reviews, a 60-review hand-written gold set, and a 16-review risk challenge set (all regenerable with `python scripts/export_data.py`).

## Layout

```
app.py              Streamlit demo
revio_ai/           sentiment, aspects, risk, llm, llm_risk, reply, pipeline, anomaly, synth, evaluate
tests/              27 unit tests (guardrails, routing, injection, alerts)
data/  docs/  scripts/
```

## Limitations

No live LLM call was made while building (no API key available), so LLM paths are verified with fake providers only; models are trained on synthetic text; no authentication, multi-tenancy or PII scrubbing. See report 02, sections 6-8.
