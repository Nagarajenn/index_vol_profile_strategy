"""Milestone 11B: incremental candidate direction features, tested one at
a time against the frozen Milestone 11A control (market_transition.
direction_baseline -- untouched, imported and used exactly as-is).

RESEARCH ONLY. No production trading logic. Every numeric/categorical
candidate below is combined with the control as a straight "control's 3
votes + this candidate's 1 vote" 4-way majority; a 2-2 tie is an honest
abstention (no prediction), never arbitrarily broken. Divergence and
Expiry Regime are NOT combined into a vote -- per the spec's explicit
"do not automatically make divergence [or expiry] a decision rule",
they are reported as diagnostic splits of the control's own accuracy
instead (Sections F/13).

Every feature value used here is read from columns market_transition.
direction_dataset already puts in the <=14:59 pre-cutoff half of a row
(including the last-10-minute 14:50-14:59 trajectory) -- nothing here
reads a new DB table, a post-15:00 column, or performs any threshold
search/optimization. Every sign below is stated as an a priori,
documented rationale (mirroring an already-established convention in
this codebase -- direction_baseline's own control signs, or
option_chain.snapshot_features.classify_option_positioning's own
bullish/bearish reasoning) BEFORE any Validation result is looked at,
per the "do not overfit Validation" mandate.
"""

from dataclasses import dataclass
from typing import Callable, Literal

from market_transition.direction_baseline import predict_row
from market_transition.direction_dataset import TRAJECTORY_MINUTES

Vote = Literal["up", "down"]

# ---------------------------------------------------------------------
# Trajectory characteristics (Section 7 / G) -- computed for every
# candidate trajectory variable, but only `slope` is promoted to a
# formally vote-tested candidate per variable (the spec's own two named
# examples -- "PCR trajectory slope", "IV skew trajectory slope" -- both
# name slope specifically; testing all 6 characteristics x 4 variables
# would be exactly the "dozens of thresholds" search the spec forbids).
# The rest are reported in Section G as diagnostic-only.
# ---------------------------------------------------------------------

TRAJECTORY_FIELDS = ("pcr_oi", "iv_skew", "atm_straddle_value", "call_put_volume_imbalance")


def trajectory_values(row: dict, field_name: str) -> list[float | None]:
    """The 10 values traj_1450_{field}..traj_1459_{field}, in minute order."""
    return [row.get(f"traj_{cp.strftime('%H%M')}_{field_name}") for cp in TRAJECTORY_MINUTES]


def _clean(values: list[float | None]) -> list[tuple[int, float]]:
    return [(i, v) for i, v in enumerate(values) if v is not None]


def trajectory_slope(values: list[float | None]) -> float | None:
    """Simple OLS slope of value vs. minute-index (0..9). None unless at
    least 5 of the 10 points are present -- a slope fit through 2-3
    scattered points is not a stable, interpretable summary."""
    pts = _clean(values)
    if len(pts) < 5:
        return None
    n = len(pts)
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    mean_x, mean_y = sum(xs) / n, sum(ys) / n
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    den = sum((x - mean_x) ** 2 for x in xs)
    return (num / den) if den else None


def trajectory_start_to_end_change(values: list[float | None]) -> float | None:
    pts = _clean(values)
    if len(pts) < 2:
        return None
    return pts[-1][1] - pts[0][1]


def trajectory_monotonicity(values: list[float | None]) -> float | None:
    """Fraction of consecutive present-value steps that move in the same
    (majority) direction -- 1.0 = perfectly monotonic, ~0.5 = choppy."""
    pts = _clean(values)
    if len(pts) < 3:
        return None
    diffs = [pts[i + 1][1] - pts[i][1] for i in range(len(pts) - 1)]
    up_steps = sum(1 for d in diffs if d > 0)
    down_steps = sum(1 for d in diffs if d < 0)
    total = up_steps + down_steps
    return (max(up_steps, down_steps) / total) if total else None


def trajectory_max_excursion(values: list[float | None]) -> float | None:
    pts = _clean(values)
    if len(pts) < 2:
        return None
    first = pts[0][1]
    return max(v - first for _, v in pts)


def trajectory_min_excursion(values: list[float | None]) -> float | None:
    pts = _clean(values)
    if len(pts) < 2:
        return None
    first = pts[0][1]
    return min(v - first for _, v in pts)


def trajectory_late_reversal(values: list[float | None]) -> bool | None:
    """True when the slope of the first 7 minutes and the slope of the
    last 3 minutes have opposite signs (a genuine late-window reversal,
    not just noise) -- None when either half can't be fit."""
    pts = _clean(values)
    if len(pts) < 6:
        return None
    early = [v for i, v in pts if i <= 6]
    late = [v for i, v in pts if i >= 7]
    if len(early) < 4 or len(late) < 2:
        return None
    early_slope = trajectory_slope([v for v in early] + [None] * (10 - len(early)))
    late_trend = late[-1] - late[0]
    if early_slope is None or early_slope == 0 or late_trend == 0:
        return None
    return (early_slope > 0) != (late_trend > 0)


# ---------------------------------------------------------------------
# Generic "control + 1 candidate vote" combiner
# ---------------------------------------------------------------------

def combined_prediction(control_votes: dict[str, Vote], candidate_vote: Vote | None) -> Vote | None:
    votes = list(control_votes.values())
    if candidate_vote is not None:
        votes.append(candidate_vote)
    up, down = votes.count("up"), votes.count("down")
    if up == down:
        return None  # honest abstention on a genuine tie -- never broken arbitrarily
    return "up" if up > down else "down"


def median_split_threshold(training_rows: list[dict], feature: str) -> float | None:
    values = sorted(r[feature] for r in training_rows if r.get(feature) is not None)
    if not values:
        return None
    n = len(values)
    mid = n // 2
    return values[mid] if n % 2 else (values[mid - 1] + values[mid]) / 2


@dataclass
class Candidate:
    name: str
    description: str
    rationale: str  # the a priori sign rationale, documented before any Validation look
    value_fn: Callable[[dict], float | str | None]
    fit_fn: Callable[[list[dict]], dict]  # training_rows -> params (e.g. {"threshold": x} or {})
    vote_fn: Callable[[float | str, dict], Vote | None]  # (value, params) -> vote


def _median_vote(sign: int) -> Callable[[float, dict], Vote | None]:
    def vote(value, params):
        threshold = params.get("threshold")
        if threshold is None:
            return None
        above = value > threshold
        up = above if sign > 0 else not above
        return "up" if up else "down"
    return vote


def _median_fit(feature_extractor):
    def fit(training_rows):
        values = sorted(v for v in (feature_extractor(r) for r in training_rows) if v is not None)
        if not values:
            return {"threshold": None}
        n = len(values)
        mid = n // 2
        return {"threshold": values[mid] if n % 2 else (values[mid - 1] + values[mid]) / 2}
    return fit


# ---- 11B-1: IV Skew (level) -------------------------------------------
# A priori rationale: Milestone 10's discovery-set finding (report Part 6)
# showed UP days had LOWER (more negative) iv_skew than DOWN days at
# 14:59 -- mirrors the control's own PCR sign convention (sign -1).
def _iv_skew_value(row):
    return row.get("opt_1459_iv_skew")


CANDIDATE_IV_SKEW = Candidate(
    name="iv_skew",
    description="ATM IV skew level at 14:59",
    rationale="Milestone 10 discovery set: UP days showed lower (more negative) iv_skew than DOWN days -- sign -1, mirroring the control's PCR-level convention.",
    value_fn=_iv_skew_value,
    fit_fn=_median_fit(_iv_skew_value),
    vote_fn=_median_vote(sign=-1),
)


# ---- 11B-2: last-10-minute trajectory slopes ---------------------------
def _traj_slope_value(field_name):
    def fn(row):
        return trajectory_slope(trajectory_values(row, field_name))
    return fn


CANDIDATE_PCR_TRAJECTORY = Candidate(
    name="pcr_trajectory_slope",
    description="Slope of PCR(OI) over 14:50-14:59",
    rationale="Mirrors the control's PCR-level sign (-1): a falling PCR trajectory is treated the same direction as a low PCR level.",
    value_fn=_traj_slope_value("pcr_oi"),
    fit_fn=_median_fit(_traj_slope_value("pcr_oi")),
    vote_fn=_median_vote(sign=-1),
)

CANDIDATE_IV_SKEW_TRAJECTORY = Candidate(
    name="iv_skew_trajectory_slope",
    description="Slope of IV skew over 14:50-14:59",
    rationale="Mirrors CANDIDATE_IV_SKEW's sign (-1): a falling iv_skew trajectory is treated the same direction as a low iv_skew level.",
    value_fn=_traj_slope_value("iv_skew"),
    fit_fn=_median_fit(_traj_slope_value("iv_skew")),
    vote_fn=_median_vote(sign=-1),
)

CANDIDATE_STRADDLE_TRAJECTORY = Candidate(
    name="straddle_trajectory_slope",
    description="Slope of ATM straddle value over 14:50-14:59",
    rationale="Mirrors the control's ATM-straddle-CHANGE sign (+1): a rising straddle trajectory is treated the same direction as a rising straddle change.",
    value_fn=_traj_slope_value("atm_straddle_value"),
    fit_fn=_median_fit(_traj_slope_value("atm_straddle_value")),
    vote_fn=_median_vote(sign=1),
)

CANDIDATE_VOLUME_IMBALANCE_TRAJECTORY = Candidate(
    name="volume_imbalance_trajectory_slope",
    description="Slope of call/put volume imbalance over 14:50-14:59",
    rationale="Mirrors the control's call/put-volume-imbalance sign (+1).",
    value_fn=_traj_slope_value("call_put_volume_imbalance"),
    fit_fn=_median_fit(_traj_slope_value("call_put_volume_imbalance")),
    vote_fn=_median_vote(sign=1),
)


# ---- 11B-10: PCR change (14:59 - 14:50, prioritized per spec Section 10)
def _pcr_change_value(row):
    a, b = row.get("opt_1459_pcr_oi"), row.get("opt_1450_pcr_oi")
    return (a - b) if (a is not None and b is not None) else None


CANDIDATE_PCR_CHANGE = Candidate(
    name="pcr_change_1450_1459",
    description="PCR(OI) at 14:59 minus PCR(OI) at 14:50",
    rationale="Mirrors the control's PCR-level sign (-1): a more negative (falling) change is treated as bullish.",
    value_fn=_pcr_change_value,
    fit_fn=_median_fit(_pcr_change_value),
    vote_fn=_median_vote(sign=-1),
)


# ---- 11B-9: OI dynamics sub-candidates ---------------------------------
# Signs drawn directly from option_chain.snapshot_features.
# classify_option_positioning's own documented bullish/bearish reasoning
# (put buildup = bullish, call buildup = bearish); unwinding signs are the
# explicitly-reasoned mirror image of their same-side buildup sign.
def _field_value(field_name):
    def fn(row):
        return row.get(f"opt_1459_{field_name}")
    return fn


CANDIDATE_CALL_OI_BUILDUP = Candidate(
    name="call_oi_buildup",
    description="Call OI build-up at 14:59",
    rationale="classify_option_positioning: heavier call OI build-up = bearish -- sign -1.",
    value_fn=_field_value("call_oi_buildup"),
    fit_fn=_median_fit(_field_value("call_oi_buildup")),
    vote_fn=_median_vote(sign=-1),
)

CANDIDATE_PUT_OI_BUILDUP = Candidate(
    name="put_oi_buildup",
    description="Put OI build-up at 14:59",
    rationale="classify_option_positioning: heavier put OI build-up = bullish -- sign +1.",
    value_fn=_field_value("put_oi_buildup"),
    fit_fn=_median_fit(_field_value("put_oi_buildup")),
    vote_fn=_median_vote(sign=1),
)

CANDIDATE_CALL_UNWINDING = Candidate(
    name="call_unwinding",
    description="Call OI unwinding at 14:59",
    rationale="Reasoned mirror-image of CANDIDATE_CALL_OI_BUILDUP (call OI being covered/reduced removes prior bearish pressure) -- sign +1. Not itself used by classify_option_positioning; this sign is this module's own documented, a priori reasoning, not tuned.",
    value_fn=_field_value("call_unwinding"),
    fit_fn=_median_fit(_field_value("call_unwinding")),
    vote_fn=_median_vote(sign=1),
)

CANDIDATE_PUT_UNWINDING = Candidate(
    name="put_unwinding",
    description="Put OI unwinding at 14:59",
    rationale="Reasoned mirror-image of CANDIDATE_PUT_OI_BUILDUP (put OI being covered/reduced removes prior bullish floor) -- sign -1. Not itself used by classify_option_positioning; this sign is this module's own documented, a priori reasoning, not tuned.",
    value_fn=_field_value("put_unwinding"),
    fit_fn=_median_fit(_field_value("put_unwinding")),
    vote_fn=_median_vote(sign=-1),
)


# ---- 11B-12: Position Classification (categorical, no threshold) ------
def _position_classification_value(row):
    return row.get("opt_1459_position_classification")


def _position_classification_vote(value, params):
    if value == "BULLISH":
        return "up"
    if value == "BEARISH":
        return "down"
    return None  # NEUTRAL/MIXED/RAPIDLY_CHANGING -- honest abstention, not forced


CANDIDATE_POSITION_CLASSIFICATION = Candidate(
    name="position_classification",
    description="classify_option_positioning() label at 14:59",
    rationale="Directly reuses classify_option_positioning's own BULLISH/BEARISH semantics; NEUTRAL/MIXED/RAPIDLY_CHANGING abstain rather than being forced to a side.",
    value_fn=_position_classification_value,
    fit_fn=lambda training_rows: {},  # no threshold to fit -- categorical
    vote_fn=lambda value, params: _position_classification_vote(value, params),
)


ALL_VOTE_CANDIDATES: list[Candidate] = [
    CANDIDATE_IV_SKEW,
    CANDIDATE_PCR_TRAJECTORY,
    CANDIDATE_IV_SKEW_TRAJECTORY,
    CANDIDATE_STRADDLE_TRAJECTORY,
    CANDIDATE_VOLUME_IMBALANCE_TRAJECTORY,
    CANDIDATE_PCR_CHANGE,
    CANDIDATE_CALL_OI_BUILDUP,
    CANDIDATE_PUT_OI_BUILDUP,
    CANDIDATE_CALL_UNWINDING,
    CANDIDATE_PUT_UNWINDING,
    CANDIDATE_POSITION_CLASSIFICATION,
]


# ---------------------------------------------------------------------
# Evaluation (mirrors market_transition.direction_baseline.evaluate's
# metric shape, kept separate rather than modifying that frozen module)
# ---------------------------------------------------------------------

def evaluate_candidate(
    rows: list[dict], control_thresholds: dict, candidate: Candidate, params: dict,
    actual_field: str = "actual_15m_direction",
) -> dict:
    audit = []
    for row in rows:
        actual = row.get(actual_field)
        if actual not in ("up", "down"):
            continue
        control_result = predict_row(row, control_thresholds)
        if control_result["prediction"] is None:
            continue
        value = candidate.value_fn(row)
        candidate_vote = candidate.vote_fn(value, params) if value is not None else None
        combined = combined_prediction(control_result["votes"], candidate_vote)
        audit.append({
            "symbol": row.get("symbol"), "session_date": row.get("session_date"), "tier": row.get("tier"),
            "control_prediction": control_result["prediction"],
            "control_correct": control_result["prediction"] == actual,
            "candidate_feature_value": value,
            "candidate_threshold": params.get("threshold"),
            "candidate_vote": candidate_vote,
            "candidate_prediction": combined,
            "actual_direction": actual,
            "candidate_correct": (combined == actual) if combined is not None else None,
        })
    return _aggregate(audit)


def _aggregate(audit: list[dict]) -> dict:
    scored = [a for a in audit if a["candidate_prediction"] is not None]
    n = len(scored)
    correct = sum(1 for a in scored if a["candidate_correct"])
    control_scoreable = [a for a in audit if a["control_prediction"] is not None]
    control_correct = sum(1 for a in control_scoreable if a["control_correct"])
    actual_up = sum(1 for a in scored if a["actual_direction"] == "up")
    actual_down = sum(1 for a in scored if a["actual_direction"] == "down")
    predicted_up = sum(1 for a in scored if a["candidate_prediction"] == "up")
    predicted_down = sum(1 for a in scored if a["candidate_prediction"] == "down")
    tp_up = sum(1 for a in scored if a["candidate_prediction"] == "up" and a["actual_direction"] == "up")
    tp_down = sum(1 for a in scored if a["candidate_prediction"] == "down" and a["actual_direction"] == "down")
    fp_up = sum(1 for a in scored if a["candidate_prediction"] == "up" and a["actual_direction"] == "down")
    fp_down = sum(1 for a in scored if a["candidate_prediction"] == "down" and a["actual_direction"] == "up")
    majority_class_accuracy = (max(actual_up, actual_down) / n) if n else None

    def _symbol_slice(sym):
        sub = [a for a in scored if a["symbol"] == sym]
        c = sum(1 for a in sub if a["candidate_correct"])
        return {"n": len(sub), "correct": c, "accuracy": (c / len(sub)) if sub else None}

    return {
        "n": n, "correct": correct, "incorrect": n - correct,
        "accuracy": (correct / n) if n else None,
        "control_n": len(control_scoreable),
        "control_accuracy": (control_correct / len(control_scoreable)) if control_scoreable else None,
        "abstained_on_tie": len(audit) - n,
        "actual_up": actual_up, "actual_down": actual_down,
        "predicted_up": predicted_up, "predicted_down": predicted_down,
        "up_precision": (tp_up / predicted_up) if predicted_up else None,
        "down_precision": (tp_down / predicted_down) if predicted_down else None,
        "confusion_matrix": {
            "predicted_up_actual_up": tp_up, "predicted_up_actual_down": fp_up,
            "predicted_down_actual_up": fp_down, "predicted_down_actual_down": tp_down,
        },
        "majority_class_accuracy": majority_class_accuracy,
        "by_symbol": {"NIFTY": _symbol_slice("NIFTY"), "SENSEX": _symbol_slice("SENSEX")},
        "audit": audit,
    }


# ---------------------------------------------------------------------
# Diagnostics: Divergence (Section 8) and Expiry Regime (Section 13) --
# NOT combined into a vote, per the spec's explicit instruction.
# ---------------------------------------------------------------------

UNDERLYING_VOTE_FEATURES: tuple[tuple[str, int], ...] = (
    ("under_1459_dist_from_vwap", 1),
    ("under_1459_mom_5min", 1),
    ("under_1459_mom_15min", 1),
    ("under_1459_poc_migration_15min", 1),
)
"""Mirrors Milestone 10's Model A (underlying-only) feature set/signs
exactly -- fit ONCE here (frozen for this milestone), used only to build
the diagnostic underlying-direction signal for the Divergence analysis.
Never used as a trading signal or combined into the control's vote."""


def fit_underlying_thresholds(training_rows: list[dict]) -> dict[str, float]:
    return {f: median_split_threshold(training_rows, f) for f, _ in UNDERLYING_VOTE_FEATURES if median_split_threshold(training_rows, f) is not None}


def underlying_vote(row: dict, thresholds: dict[str, float]) -> Vote | None:
    votes = []
    for feature, sign in UNDERLYING_VOTE_FEATURES:
        value, threshold = row.get(feature), thresholds.get(feature)
        if value is None or threshold is None:
            continue
        above = value > threshold
        votes.append("up" if (above if sign > 0 else not above) else "down")
    if not votes:
        return None
    up, down = votes.count("up"), votes.count("down")
    if up == down:
        return None
    return "up" if up > down else "down"


def divergence_analysis(rows: list[dict], control_thresholds: dict, underlying_thresholds: dict, actual_field: str = "actual_15m_direction") -> dict:
    states = {"AGREE": [], "DISAGREE": []}
    detail = []
    for row in rows:
        actual = row.get(actual_field)
        if actual not in ("up", "down"):
            continue
        options_pred = predict_row(row, control_thresholds)["prediction"]
        under_pred = underlying_vote(row, underlying_thresholds)
        if options_pred is None or under_pred is None:
            continue
        state = "AGREE" if options_pred == under_pred else "DISAGREE"
        correct = options_pred == actual
        states[state].append(correct)
        detail.append({
            "symbol": row.get("symbol"), "session_date": row.get("session_date"), "tier": row.get("tier"),
            "underlying_direction": under_pred, "options_direction": options_pred,
            "divergence_state": state, "actual_direction": actual, "control_correct": correct,
        })

    def _stats(label):
        vals = states[label]
        return {"n": len(vals), "correct": sum(vals), "accuracy": (sum(vals) / len(vals)) if vals else None}

    return {"agree": _stats("AGREE"), "disagree": _stats("DISAGREE"), "detail": detail}


def expiry_regime_analysis(rows: list[dict], control_thresholds: dict, actual_field: str = "actual_15m_direction", min_n_per_class: int = 5) -> dict:
    """min_n_per_class=5 is deliberately conservative: Milestone 10.5 found
    expiry cells "too thin for standalone conclusions" even across the
    full ~46-day option-usable sample -- the Validation+Test slice used
    here (18 rows) is far smaller again, so a low bar here would report a
    result the spec's own prior finding already warns against trusting."""
    by_regime = {"weekly": [], "monthly": []}
    for row in rows:
        actual = row.get(actual_field)
        regime = row.get("expiry_type")
        if actual not in ("up", "down") or regime not in by_regime:
            continue
        pred = predict_row(row, control_thresholds)["prediction"]
        if pred is None:
            continue
        by_regime[regime].append(pred == actual)

    counts = {k: len(v) for k, v in by_regime.items()}
    insufficient = any(c < min_n_per_class for c in counts.values())
    result = {"counts": counts, "status": "INSUFFICIENT_DATA" if insufficient else "EVALUATED"}
    if not insufficient:
        for regime, vals in by_regime.items():
            result[regime] = {"n": len(vals), "correct": sum(vals), "accuracy": sum(vals) / len(vals)}
    return result
