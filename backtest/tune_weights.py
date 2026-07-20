import random

import pandas as pd


def score_with_weights(sub_scores: dict, weights: dict) -> int:
    """Re-applies a candidate weight set to already-computed sub-scores
    (stored per snapshot in decision_card.json) without recomputing any
    technicals — mirrors analytics/confidence_score.py's renormalization
    when a component (e.g. institutional_bias on backfilled rows) is absent.
    """
    active = {k: v for k, v in weights.items() if k in sub_scores}
    total = sum(active.values())
    if not total:
        return 0
    normalized = {k: v / total for k, v in active.items()}
    raw = sum(sub_scores[k] * normalized.get(k, 0) for k in sub_scores) * 100
    return max(0, min(100, round(raw)))


def evaluate_weights(labeled_df: pd.DataFrame, weights: dict, horizon_min: int = 30) -> float:
    """Calibration proxy: mean confidence given to calls that turned out
    correct minus mean confidence given to calls that turned out wrong.
    Higher is better (confident calls should actually be the right ones).
    Returns NaN if there's not enough labeled data on both sides to compare.
    """
    correct_col = f"trend_correct_{horizon_min}m"
    rows = labeled_df.dropna(subset=[correct_col])
    if rows.empty:
        return float("nan")

    scores = rows["confidence_sub_scores"].apply(lambda s: score_with_weights(s, weights))
    correct_mask = rows[correct_col].astype(bool)
    if correct_mask.sum() == 0 or (~correct_mask).sum() == 0:
        return float("nan")

    return float(scores[correct_mask].mean() - scores[~correct_mask].mean())


def random_search(
    labeled_df: pd.DataFrame,
    base_weights: dict,
    horizon_min: int = 30,
    n_trials: int = 300,
    perturbation: int = 10,
    seed: int = 42,
) -> dict:
    """Random-neighborhood search over weight perturbations. A 7-dimensional
    weight space makes an exhaustive grid impractical; random search over
    integer perturbations of the current best is simple and scales fine
    here. Intended to run once there are enough labeled snapshots (mixing
    live + backfilled rows) that `evaluate_weights` isn't just noise -- with
    only the 60-day backfill (no institutional_bias signal, single realized
    path) treat any single run's result as a starting point, not gospel.
    """
    rng = random.Random(seed)
    best_weights = dict(base_weights)
    best_score = evaluate_weights(labeled_df, best_weights, horizon_min)

    for _ in range(n_trials):
        candidate = {k: max(1, v + rng.randint(-perturbation, perturbation)) for k, v in best_weights.items()}
        score = evaluate_weights(labeled_df, candidate, horizon_min)
        if score == score and (best_score != best_score or score > best_score):  # NaN-safe
            best_score = score
            best_weights = candidate

    return {"weights": best_weights, "score": best_score}
