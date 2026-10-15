"""Write the synthetic + gold datasets to data/*.csv so reviewers can inspect them."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pandas as pd

from revio_ai.evaluate import gold_df
from revio_ai.gold_data import CHALLENGE_RISK
from revio_ai.synth import generate_stream, generate_training

d = Path(__file__).resolve().parent.parent / "data"
d.mkdir(exist_ok=True)
generate_stream().to_csv(d / "demo_reviews.csv", index=False)
generate_training().to_csv(d / "synthetic_train.csv", index=False)
gold_df().drop(columns=["location"]).to_csv(d / "gold_eval.csv", index=False)
pd.DataFrame(CHALLENGE_RISK, columns=["text", "high_risk"]).to_csv(d / "risk_challenge.csv", index=False)
print("wrote", sorted(p.name for p in d.glob("*.csv")))
