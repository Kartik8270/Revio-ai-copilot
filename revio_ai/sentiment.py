"""Sentiment models: VADER baseline, TF-IDF + logistic regression, and a hybrid of the two.

The hybrid appends VADER's valence scores to the TF-IDF matrix, so the classifier can learn
domain vocabulary ("bland", "paisa vasool") while keeping VADER's handling of negation,
intensifiers and punctuation.
"""
from __future__ import annotations

import numpy as np
from scipy.sparse import csr_matrix, hstack
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

LABELS = ["negative", "neutral", "positive"]
_vader = SentimentIntensityAnalyzer()


def vader_compound(text: str) -> float:
    return _vader.polarity_scores(text)["compound"]


def vader_label(text: str, thr: float = 0.05) -> str:
    c = vader_compound(text)
    return "positive" if c >= thr else "negative" if c <= -thr else "neutral"


def _vader_feats(texts) -> csr_matrix:
    rows = []
    for t in texts:
        s = _vader.polarity_scores(t)
        rows.append([s["compound"], s["pos"], s["neg"], s["neu"]])
    return csr_matrix(np.array(rows))


class SentimentModel:
    """kind: 'tfidf' (text only) or 'hybrid' (text + VADER features)."""

    def __init__(self, kind: str = "hybrid", C: float = 3.0):
        self.kind = kind
        self.vec = TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True, lowercase=True)
        self.clf = LogisticRegression(C=C, max_iter=2000, class_weight="balanced")

    def _X(self, texts, fit=False):
        X = self.vec.fit_transform(texts) if fit else self.vec.transform(texts)
        return hstack([X, _vader_feats(texts)]).tocsr() if self.kind == "hybrid" else X

    def fit(self, texts, labels) -> "SentimentModel":
        texts = list(texts)
        self.clf.fit(self._X(texts, fit=True), labels)
        return self

    def predict_proba(self, texts) -> list[dict[str, float]]:
        texts = list(texts)
        P = self.clf.predict_proba(self._X(texts))
        return [dict(zip(self.clf.classes_, map(float, row))) for row in P]

    def predict(self, texts) -> list[str]:
        texts = list(texts)
        return list(self.clf.predict(self._X(texts)))
