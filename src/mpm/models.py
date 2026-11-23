"""Phase 7: the candidate models, all behind one tiny interface: fit(X, y) and score(X).

X is always (n_cells, n_features) in the order of feature_catalog.json. Everything fitted (clipping limits,
scaling, which rare rock classes to drop) is fitted on the TRAINING cells of a fold only.

Ladder, simplest first - a model only earns its place by beating the one before it:
  prevalence      constant score; PR-AUC equals the prevalence. The floor.
  rule_geology    hand-made mineral-system rule (clastic host rock + near faults). No training at all.
  single_rad_U    just the uranium count. Is the model better than "look where U is high"?
  logreg          regularised logistic regression on clipped, standardised features. Linear, interpretable.
  rf / et         bagged trees (random forest, extra trees), shallow-ish and with big leaves for few positives.
  hgb             shallow gradient boosting (depth 3, small learning rate, L2).
"""
from __future__ import annotations

import numpy as np
from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression

RULE_SCALE_M = 5000.0


class Prep:
    """Clip extremes, standardise, drop rare rock-class dummies. Fitted on training cells only."""

    def __init__(self, names: list[str], rare_frac: float = 0.005, clip=(0.1, 99.9)):
        self.names, self.rare_frac, self.clip = names, rare_frac, clip

    def fit(self, X: np.ndarray) -> "Prep":
        self.keep = np.array([i for i, n in enumerate(self.names)
                              if not n.startswith("geo_is_") or X[:, i].mean() >= self.rare_frac])
        Xk = X[:, self.keep].astype("float64")
        self.lo, self.hi = np.percentile(Xk, self.clip, axis=0)
        Xc = np.clip(Xk, self.lo, self.hi)
        self.mu = Xc.mean(axis=0)
        sd = Xc.std(axis=0)
        self.sd = np.where(sd > 0, sd, 1.0)
        return self

    def transform(self, X: np.ndarray) -> np.ndarray:
        Xk = X[:, self.keep].astype("float64")
        return (np.clip(Xk, self.lo, self.hi) - self.mu) / self.sd

    @property
    def kept_names(self) -> list[str]:
        return [self.names[i] for i in self.keep]


class Constant:
    def fit(self, X, y):
        return self

    def score(self, X):
        return np.zeros(len(X))


class RuleGeology:
    """Mineral-system rule written before modelling: favourable host rock + pathway.

    NOTE: 'clastic sedimentary' was chosen after seeing the Phase 4 table (83 % of occurrences sit on it),
    so this baseline is not fully independent of the labels. Treat it as a strong simple reference, not a
    blind prediction.
    """

    def __init__(self, names):
        self.i_host = names.index("geo_is_sedimentary_clastic")
        self.i_fault = names.index("str_dist_fault_m")

    def fit(self, X, y):
        return self

    def score(self, X):
        return X[:, self.i_host] + np.exp(-X[:, self.i_fault] / RULE_SCALE_M)


class SingleFeature:
    def __init__(self, names, feature: str):
        self.i = names.index(feature)

    def fit(self, X, y):
        return self

    def score(self, X):
        return X[:, self.i].astype("float64")


class SklearnModel:
    def __init__(self, est, names=None, prep: bool = False):
        self.est, self.names, self.use_prep = est, names, prep

    def fit(self, X, y):
        if self.use_prep:
            self.prep = Prep(self.names).fit(X)
            X = self.prep.transform(X)
        self.est.fit(X, y)
        return self

    def score(self, X):
        if self.use_prep:
            X = self.prep.transform(X)
        return self.est.predict_proba(X)[:, 1]


def make_model(name: str, names: list[str], seed: int, params: dict | None = None):
    """`params` overrides the defaults below (used by tuning and ablation)."""
    p = params or {}
    if name == "prevalence":
        return Constant()
    if name == "rule_geology":
        return RuleGeology(names)
    if name == "single_rad_U":
        return SingleFeature(names, "rad_U")
    if name == "logreg":
        return SklearnModel(LogisticRegression(C=p.get("C", 0.05), class_weight="balanced", max_iter=3000),
                            names, prep=True)
    if name in ("rf", "et"):
        cls = RandomForestClassifier if name == "rf" else ExtraTreesClassifier
        return SklearnModel(cls(
            n_estimators=p.get("n_estimators", 200), max_depth=p.get("max_depth", 10),
            min_samples_leaf=p.get("min_samples_leaf", 10), max_features=p.get("max_features", "sqrt"),
            class_weight="balanced_subsample", n_jobs=-1, random_state=seed))
    if name == "hgb":
        return SklearnModel(HistGradientBoostingClassifier(
            max_depth=3, learning_rate=0.05, max_iter=200, min_samples_leaf=20, l2_regularization=1.0,
            class_weight="balanced", random_state=seed))
    raise ValueError(f"unknown model {name!r}")
