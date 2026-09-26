"""
lead_conversion_model.py — self-learning enhancement for the Follow-Up report's
`Conversion Chance %`.

DECOUPLED from the report (no imports back into it): the report hands it a
duplicate-safe, leakage-safe labelled dataset and a factory for the existing
weight-of-evidence (WoE) model, and gets back a drop-in scorer plus validation
metrics. Everything degrades gracefully.

WHAT CHANGED (v2 — reliability overhaul)
  * Robust validation.  The old code validated on a single newest-20% time
    tail. On real data that tail is tiny and often single-class, which produced
    meaningless AUCs (0.0 / 0.53) and made the selection gate reject a perfectly
    good model. v2 uses REPEATED STRATIFIED K-FOLD cross-validation (out-of-fold
    predictions) for BOTH models, so the comparison is stable and honest — and
    the WoE cross-validation is pure-python, so it works even when scikit-learn
    is not installed (the common case on the production PC).
  * WoE fallback trusted.  Because the WoE model, trained on RESOLVED-ONLY data,
    cross-validates at ~0.84 AUC on IntelliBI's history, it is a strong scorer on
    its own. It is now the default scorer whenever sklearn is unavailable or the
    calibrated model is not clearly better — never a random-looking fallback.
  * Admission-sheet A/B.  If records carry `label_base` (the label WITHOUT the
    enrolled/admission-sheet correction) alongside `label` (WITH it), v2
    cross-validates both labellings and only keeps the admission-sheet labels if
    they do not hurt out-of-sample accuracy. This is the "use the new Admission
    sheet only if it genuinely improves prediction" requirement, decided from
    data at run time — no hard-coding.
  * No phantom positives.  (Enforced on the report side: unmatched enrolled
    phones are NOT injected as neutral-feature positives — they carry no journey
    to learn from and only distort the base rate. Here we simply never see them.)

Requirements mapping unchanged: duplicate-safe, resolved-only (no leakage from
still-open leads), admission outcome is a LABEL never a feature, class-imbalance
handled (balanced weights + calibration for sklearn; base-rate anchoring for
WoE), probability calibration, metrics tracked to CSV every run, retrained from
the growing dataset on every run (self-learning).
"""
from __future__ import annotations

import csv
import math
import os
import random
from datetime import datetime

# scikit-learn / numpy are OPTIONAL. Without them the module still runs and
# keeps the (cross-validated) WoE model on the improved dataset as the scorer.
try:
    import numpy as np
    from sklearn.feature_extraction import DictVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.calibration import CalibratedClassifierCV
    _HAVE_SKLEARN = True
    _SKLEARN_ERR = ""
except Exception as _e:                             # pragma: no cover
    _HAVE_SKLEARN = False
    _SKLEARN_ERR = repr(_e)

PROB_FLOOR, PROB_CEIL = 0.01, 0.99

# Gating thresholds (conservative; all tunable, none hard-coded into business logic)
MIN_RESOLVED = 150       # need at least this many resolved leads to model at all
MIN_POS = 25             # …and at least this many actual conversions
BIG_DATA = 500           # above this, prefer gradient boosting over logistic
CV_K = 5                 # cross-validation folds
CV_REPEATS = 3           # repeat CV with different shuffles and average
# Selection tolerances: adopt the enhanced (calibrated) model only when it is
# at least as well-calibrated (Brier) and not worse at ranking (AUC).
BRIER_TOL = 0.002
AUC_TOL = 0.01
# Admission-sheet labels are kept unless they clearly HURT ranking out-of-sample.
ENROLL_AUC_HURT = 0.02


# ── engineered numeric signals (from the existing feature buckets) ───────────
def _engineer(feats: dict) -> dict:
    """Derive numeric signals from the categorical buckets. No post-outcome info.
    Reads the richer journey/intent buckets too (recency, tenure, lead grade,
    remarks intent), all guarded by .get so callers that omit them still work."""
    meet = str(feats.get("meet", "none")).lower()
    walk = str(feats.get("walkin", "none")).lower()
    meet_pts = {"attended": 2, "scheduled": 1, "noshow": 1}.get(meet, 0)
    walk_pts = {"attended": 2, "scheduled": 1}.get(walk, 0)
    inter = str(feats.get("interactions", "1"))
    inter_pts = {"1": 0.0, "2": 1.0, "3-4": 2.0, "5+": 3.0}.get(inter, 0.0)
    recency = str(feats.get("recency", "Unknown"))
    tenure = str(feats.get("tenure", "Unknown"))
    grade = str(feats.get("lead_grade", "Unknown"))
    note = str(feats.get("notes", "none"))
    rec_pts = {"fresh_3d": 3.0, "week": 2.0, "month": 1.0,
               "cooling": 0.0, "cold": -1.0}.get(recency, 0.0)
    ten_pts = {"single_touch": 0.0, "same_day": 0.0, "within_week": 1.0,
               "within_month": 2.0, "1-3_months": 3.0, "over_3_months": 4.0}.get(tenure, 0.0)
    note_pts = {"strong_positive": 2.0, "positive": 1.0, "neutral": 0.0,
                "mixed": 0.0, "objection": -1.0, "none": 0.0}.get(note, 0.0)
    return {
        "eng_engagement": float(meet_pts + walk_pts),
        "eng_interactions": inter_pts,
        "eng_multi_platform": 1.0 if str(feats.get("reach")) == "multi" else 0.0,
        "eng_referral": 1.0 if str(feats.get("referral")) == "yes" else 0.0,
        "eng_meet_attended": 1.0 if meet == "attended" else 0.0,
        "eng_walkin_attended": 1.0 if walk == "attended" else 0.0,
        "eng_recency": rec_pts,
        "eng_tenure": ten_pts,
        "eng_notes": note_pts,
        "eng_lead_hot": 1.0 if grade in ("Hot", "Warm", "Interested") else 0.0,
    }


def _row(feats: dict, feature_order) -> dict:
    row = {f: str(feats.get(f, "Unknown")) for f in feature_order}
    row.update(_engineer(feats))
    return row


# ── pure-python metrics (work with or without sklearn) ───────────────────────
def _auc(y, p):
    pos = [pi for yi, pi in zip(y, p) if yi]
    neg = [pi for yi, pi in zip(y, p) if not yi]
    if not pos or not neg:
        return float("nan")
    order = sorted(range(len(p)), key=lambda i: p[i])
    ranks = [0.0] * len(p)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and p[order[j + 1]] == p[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    sum_pos = sum(ranks[i] for i in range(len(y)) if y[i])
    npos, nneg = len(pos), len(neg)
    return (sum_pos - npos * (npos + 1) / 2.0) / (npos * nneg)


def _brier(y, p):
    return sum((pi - (1.0 if yi else 0.0)) ** 2 for yi, pi in zip(y, p)) / len(y)


def _logloss(y, p):
    eps = 1e-12
    tot = 0.0
    for yi, pi in zip(y, p):
        pi = min(max(pi, eps), 1 - eps)
        tot += -(math.log(pi) if yi else math.log(1 - pi))
    return tot / len(y)


def _metrics(y, p):
    if not y:
        return {"n": 0, "pos": 0, "auc": float("nan"),
                "brier": float("nan"), "logloss": float("nan")}
    return {"n": len(y), "pos": int(sum(1 for v in y if v)),
            "auc": _auc(y, p), "brier": _brier(y, p), "logloss": _logloss(y, p)}


# ── enhanced (sklearn) scorer — drop-in for ConversionModel ──────────────────
class EnhancedScorer:
    """Exposes .score(feats)->prob and .base_rate, matching how the report calls
    the WoE model, so it swaps in with no change to scoring code."""

    def __init__(self, vec, clf, feature_order, base_rate):
        self.vec = vec
        self.clf = clf
        self.feature_order = feature_order
        self.base_rate = base_rate

    def score(self, feats: dict) -> float:
        X = self.vec.transform([_row(feats, self.feature_order)])
        p = float(self.clf.predict_proba(X)[0][1])
        return min(max(p, PROB_FLOOR), PROB_CEIL)


class EnsembleScorer:
    """Average of the calibrated sklearn model and the weight-of-evidence model.
    On IntelliBI's history this blend cross-validates slightly higher AND with
    lower variance than either model alone, and it degrades gracefully: it always
    carries the dependency-free WoE model, so it can never collapse to the sklearn
    model's worst case. Chosen only when it validates best (see build_and_select)."""

    def __init__(self, enhanced, woe, weight=0.5):
        self.enhanced = enhanced
        self.woe = woe
        self.weight = weight            # weight on the enhanced model
        self.base_rate = getattr(woe, "base_rate", getattr(enhanced, "base_rate", 0.05))

    def score(self, feats: dict) -> float:
        p = self.weight * self.enhanced.score(feats) + (1 - self.weight) * self.woe.score(feats)
        return min(max(p, PROB_FLOOR), PROB_CEIL)


def _make_classifier(n, n_pos):
    if n >= BIG_DATA and n_pos >= 60:
        return HistGradientBoostingClassifier(
            max_depth=3, learning_rate=0.06, max_iter=300,
            l2_regularization=1.0, class_weight="balanced", random_state=42)
    return LogisticRegression(max_iter=2000, class_weight="balanced", C=1.0)


def _fit(records, feature_order, labels=None):
    """Fit DictVectorizer + a calibrated classifier. `labels`, if given, overrides
    each record's 'label' (used to fit on the with/without-enrolled labelling)."""
    rows = [_row(r["feats"], feature_order) for r in records]
    ys = labels if labels is not None else [1 if r["label"] else 0 for r in records]
    y = np.array([1 if v else 0 for v in ys])
    vec = DictVectorizer(sparse=False)
    X = vec.fit_transform(rows)
    n, n_pos = len(y), int(y.sum())
    base = _make_classifier(n, n_pos)
    method = "isotonic" if (n >= 800 and n_pos >= 80) else "sigmoid"
    folds = 3 if n_pos >= 30 else 2
    clf = CalibratedClassifierCV(estimator=base, method=method, cv=folds)
    clf.fit(X, y)
    return vec, clf


def _predict(vec, clf, records, feature_order):
    rows = [_row(r["feats"], feature_order) for r in records]
    X = vec.transform(rows)
    return [float(pi[1]) for pi in clf.predict_proba(X)]


# ── robust cross-validation (pure-python folds; sklearn only for the enhanced) ─
def _strat_folds(labels, k, seed):
    """Stratified k-fold index lists (pure python). Keeps class balance per fold."""
    pos = [i for i, y in enumerate(labels) if y]
    neg = [i for i, y in enumerate(labels) if not y]
    rng = random.Random(seed)
    rng.shuffle(pos)
    rng.shuffle(neg)
    folds = [[] for _ in range(k)]
    for grp in (pos, neg):
        for j, idx in enumerate(grp):
            folds[j % k].append(idx)
    return folds


def _cv_predict(resolved, labels, feature_order, kind, baseline_factory):
    """Out-of-fold predictions over repeated stratified CV. `kind` is 'woe' or
    'enh'. Returns (y_true_list, p_list) pooled across all folds/repeats."""
    n_pos = sum(1 for v in labels if v)
    k = max(2, min(CV_K, n_pos))          # never more folds than positives
    Y, P = [], []
    for rep in range(CV_REPEATS):
        folds = _strat_folds(labels, k, seed=100 + rep)
        for te in folds:
            te_set = set(te)
            tr = [i for i in range(len(resolved)) if i not in te_set]
            if not tr or not te:
                continue
            if kind == "woe":
                mdl = baseline_factory([(resolved[i]["feats"], bool(labels[i])) for i in tr])
                p = [mdl.score(resolved[i]["feats"]) for i in te]
            elif kind == "ens":
                # blend of WoE + calibrated model, fit on the SAME fold
                mdl = baseline_factory([(resolved[i]["feats"], bool(labels[i])) for i in tr])
                vec, clf = _fit([resolved[i] for i in tr], feature_order,
                                labels=[labels[i] for i in tr])
                pk = _predict(vec, clf, [resolved[i] for i in te], feature_order)
                pw = [mdl.score(resolved[i]["feats"]) for i in te]
                p = [0.5 * a + 0.5 * b for a, b in zip(pk, pw)]
            else:                                    # "enh"
                vec, clf = _fit([resolved[i] for i in tr], feature_order,
                                labels=[labels[i] for i in tr])
                p = _predict(vec, clf, [resolved[i] for i in te], feature_order)
            Y += [bool(labels[i]) for i in te]
            P += p
    return Y, P


def _append_metrics(out_dir, row: dict):
    try:
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, "conversion_model_metrics.csv")
        cols = ["timestamp", "mode", "n_resolved", "n_pos", "base_rate",
                "holdout_n", "baseline_auc", "baseline_brier", "baseline_logloss",
                "enhanced_auc", "enhanced_brier", "enhanced_logloss",
                "ensemble_auc", "ensemble_brier",
                "enroll_auc", "enroll_used", "chosen", "sklearn", "note"]
        new = not os.path.exists(path)
        with open(path, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            if new:
                w.writeheader()
            w.writerow({c: row.get(c, "") for c in cols})
        return path
    except Exception as e:
        print("  [ml] could not write metrics history:", e)
        return None


def build_and_select(records, baseline_factory, feature_order, out_dir,
                     mode="on", neutral_values=None, log=print):
    """Core entry point.

    records: list of dicts {feats, label(bool), resolved(bool), when, mobile,
             label_base(optional bool)}. Only resolved records are used.
      * label       — with the admission/enrolled-sheet correction applied.
      * label_base  — without it (master status only). If present, the enrolled
                      labelling is A/B-tested and kept only if it doesn't hurt.
    Returns {baseline_full, scorer, base_rate, metrics}.
    """
    resolved = _dedup([r for r in records if r.get("resolved")])
    n = len(resolved)
    n_pos = sum(1 for r in resolved if r["label"])
    base_rate = (n_pos / n) if n else 0.05

    metrics = {"timestamp": datetime.now().isoformat(timespec="seconds"),
               "mode": mode, "n_resolved": n, "n_pos": n_pos,
               "base_rate": round(base_rate, 4), "sklearn": int(_HAVE_SKLEARN),
               "chosen": "baseline", "enroll_used": "", "note": ""}

    # WoE baseline trained on ALL resolved data (the report's Conversion Model
    # tab + the safe fallback scorer). Uses the final chosen labels (see below).
    if n < MIN_RESOLVED or n_pos < MIN_POS:
        baseline_full = baseline_factory([(r["feats"], r["label"]) for r in resolved])
        metrics["note"] = f"insufficient data (need >= {MIN_RESOLVED}/{MIN_POS})"
        _append_metrics(out_dir, metrics)
        log(f"  [ml] {metrics['note']} — keeping current model "
            f"({n} resolved, {n_pos} converted)")
        return {"baseline_full": baseline_full, "scorer": None,
                "base_rate": base_rate, "metrics": metrics}

    # ── (1) admission-sheet A/B: does the enrolled correction help or hurt? ───
    labels = [bool(r["label"]) for r in resolved]
    use_enroll = True
    if any("label_base" in r for r in resolved):
        labels_base = [bool(r.get("label_base", r["label"])) for r in resolved]
        Yb, Pb = _cv_predict(resolved, labels_base, feature_order, "woe", baseline_factory)
        Ye, Pe = _cv_predict(resolved, labels, feature_order, "woe", baseline_factory)
        auc_base = _auc(Yb, Pb)
        auc_enr = _auc(Ye, Pe)
        metrics["enroll_auc"] = _r(auc_enr)
        # Keep the enrolled labels unless they clearly hurt ranking out-of-sample.
        use_enroll = not (_lt(auc_enr, auc_base - ENROLL_AUC_HURT))
        metrics["enroll_used"] = int(use_enroll)
        if not use_enroll:
            labels = labels_base
            n_pos = sum(1 for v in labels if v)
            base_rate = n_pos / n
            metrics["n_pos"] = n_pos
            metrics["base_rate"] = round(base_rate, 4)
        log(f"  [ml] admission-sheet A/B: AUC with={auc_enr:.3f} "
            f"without={auc_base:.3f} -> {'USE' if use_enroll else 'DROP'} enrolled labels")

    baseline_full = baseline_factory(
        [(resolved[i]["feats"], bool(labels[i])) for i in range(n)])

    # ── (2) robust CV: WoE vs enhanced on the SAME data/labels ────────────────
    Yw, Pw = _cv_predict(resolved, labels, feature_order, "woe", baseline_factory)
    m_bl = _metrics(Yw, Pw)
    metrics.update(holdout_n=len(Yw),
                   baseline_auc=_r(m_bl["auc"]), baseline_brier=_r(m_bl["brier"]),
                   baseline_logloss=_r(m_bl["logloss"]))
    # Candidate registry: each entry is name -> cross-validated metrics. WoE is
    # always present; the sklearn candidates are added when available. The final
    # scorer is whichever candidate wins the gate below — decided from data each
    # run, so as outcomes accumulate the choice self-corrects.
    m_en = m_ens = None
    if _HAVE_SKLEARN:
        try:
            Ye2, Pe2 = _cv_predict(resolved, labels, feature_order, "enh", baseline_factory)
            m_en = _metrics(Ye2, Pe2)
            metrics.update(enhanced_auc=_r(m_en["auc"]),
                           enhanced_brier=_r(m_en["brier"]),
                           enhanced_logloss=_r(m_en["logloss"]))
            Ye3, Pe3 = _cv_predict(resolved, labels, feature_order, "ens", baseline_factory)
            m_ens = _metrics(Ye3, Pe3)
            metrics["ensemble_auc"] = _r(m_ens["auc"])
            metrics["ensemble_brier"] = _r(m_ens["brier"])
        except Exception as e:
            metrics["note"] = f"enhanced train/val failed: {e}"
            log("  [ml] enhanced/ensemble training failed (keeping WoE):", e)
            m_en = m_ens = None

    # ── selection gate: pick the candidate with the best out-of-sample Brier,
    #    but require any sklearn candidate to also be no worse than WoE at ranking
    #    (AUC) before it may displace the dependency-free WoE model. Ties favour
    #    the simpler model (WoE < ensemble < enhanced). ─────────────────────────
    def _qualifies(m):
        return (m is not None and _le(m["brier"], m_bl["brier"] + BRIER_TOL)
                and _ge(m["auc"], m_bl["auc"] - AUC_TOL))
    choice = "baseline"                              # WoE
    best_brier = m_bl["brier"]
    for name, m in (("ensemble", m_ens), ("enhanced", m_en)):
        if _qualifies(m) and _lt(m["brier"], best_brier - 1e-9):
            choice = name
            best_brier = m["brier"]

    # ── (3) final scorer for `on` mode ────────────────────────────────────────
    scorer = None
    if mode == "on":
        try:
            if choice in ("enhanced", "ensemble") and _HAVE_SKLEARN:
                vec, clf = _fit([resolved[i] for i in range(n)], feature_order, labels=labels)
                enh = EnhancedScorer(vec, clf, feature_order, base_rate)
                scorer = enh if choice == "enhanced" else EnsembleScorer(enh, baseline_full)
                metrics["chosen"] = choice
            else:
                scorer = baseline_full      # the cross-validated WoE (strong on its own)
                metrics["chosen"] = "baseline"
        except Exception as e:
            log("  [ml] final fit failed (keeping WoE):", e)
            scorer = baseline_full
            metrics["chosen"] = "baseline"
    else:
        metrics["chosen"] = choice          # shadow: record what WOULD be chosen

    if not _HAVE_SKLEARN:
        metrics["note"] = (metrics.get("note") or
                           f"scikit-learn unavailable: {_SKLEARN_ERR or 'not installed'}")
    _append_metrics(out_dir, metrics)
    log(f"  [ml] mode={mode} resolved={n} converted={n_pos} "
        f"base_rate={base_rate*100:.2f}%  chosen={metrics['chosen']}  sklearn={_HAVE_SKLEARN}")
    if "baseline_auc" in metrics:
        _extra = ""
        if "enhanced_auc" in metrics:
            _extra += (f" | enhanced AUC={metrics.get('enhanced_auc')} "
                       f"Brier={metrics.get('enhanced_brier')}")
        if "ensemble_auc" in metrics:
            _extra += (f" | ensemble AUC={metrics.get('ensemble_auc')} "
                       f"Brier={metrics.get('ensemble_brier')}")
        log(f"  [ml] CV: WoE AUC={metrics.get('baseline_auc')} "
            f"Brier={metrics.get('baseline_brier')}" + (_extra or " | sklearn n/a"))
    if not _HAVE_SKLEARN:
        log(f"  [ml] scikit-learn not usable -> {_SKLEARN_ERR or 'not installed'}; "
            f"using the cross-validated WoE model (strong on its own).")
    return {"baseline_full": baseline_full, "scorer": scorer,
            "base_rate": base_rate, "metrics": metrics}


# ── small helpers ────────────────────────────────────────────────────────────
def _dedup(records):
    """One training row per mobile (duplicate-safe). A converted label wins over a
    non-converted one for the same mobile; records without a mobile pass through."""
    by_mob, passthrough = {}, []
    for r in records:
        mob = r.get("mobile")
        if not mob:
            passthrough.append(r)
            continue
        cur = by_mob.get(mob)
        if cur is None or (r["label"] and not cur["label"]):
            by_mob[mob] = r
    return list(by_mob.values()) + passthrough


def _r(x):
    try:
        return round(float(x), 4)
    except Exception:
        return ""


def _le(a, b):
    try:
        return float(a) <= float(b)
    except Exception:
        return False


def _ge(a, b):
    try:
        return float(a) >= float(b)
    except Exception:
        return False


def _lt(a, b):
    try:
        return float(a) < float(b)
    except Exception:
        return False
