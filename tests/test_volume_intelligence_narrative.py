from analytics.volume_intelligence.models import (
    AbsorptionSignal,
    BuySellDominance,
    ExhaustionSignal,
    HistoricalSimilarity,
    InstitutionalParticipation,
    NextIntervalForecast,
    RvolBaselineResult,
    RvolReading,
    VolumeCharacter,
    VolumeDryUp,
    VolumeSpike,
)
from analytics.volume_intelligence.narrative import (
    _absorption_observation,
    _dominance_streak_observation,
    _dryup_observation,
    _exhaustion_observation,
    _institutional_observation,
    _rvol_observation,
    _spike_observation,
    build_headline,
    build_observations,
)
from analytics.volume_intelligence.proxy import attach_buy_sell_columns
from tests.fixtures.synthetic_candles import make_candles


def _minimal_enriched() -> "object":
    rows = [{"time": f"09:{15+i:02d}", "o": 100, "h": 100, "l": 100, "c": 100, "v": 100} for i in range(3)]
    return attach_buy_sell_columns(make_candles(rows))


def test_headline_continuation_lean():
    character = VolumeCharacter(label="Markup", rationale="x")
    forecast = NextIntervalForecast(horizon_minutes=10, probability_continuation=0.7, probability_reversal=0.3, confidence="High", supporting_factors=[], composite_score=0.5)
    assert build_headline(character, forecast) == "Markup character with a continuation lean (70%, High confidence)."


def test_headline_reversal_lean():
    character = VolumeCharacter(label="Climactic", rationale="x")
    forecast = NextIntervalForecast(horizon_minutes=10, probability_continuation=0.3, probability_reversal=0.7, confidence="Medium", supporting_factors=[], composite_score=-0.5)
    assert build_headline(character, forecast) == "Climactic character with a reversal lean (70%, Medium confidence)."


def test_rvol_observation_triggers_above_threshold():
    rvol = RvolReading(primary=RvolBaselineResult(group="last_20_days", interval_rvol_pct=142.0, cumulative_rvol_pct=100.0, label="Above Average", sample_days=10))
    result = _rvol_observation(rvol)
    assert result is not None
    assert "42%" in result[1] and "above" in result[1]


def test_rvol_observation_silent_below_threshold():
    rvol = RvolReading(primary=RvolBaselineResult(group="last_20_days", interval_rvol_pct=110.0, cumulative_rvol_pct=100.0, label="Average", sample_days=10))
    assert _rvol_observation(rvol) is None


def test_dominance_streak_observation_triggers():
    dominance = BuySellDominance(window_minutes=8, buy_volume=800, sell_volume=200, dominance_ratio=0.8, dominant_side="buy", consecutive_dominant_minutes=8)
    assert _dominance_streak_observation(dominance) == (1, "Buy volume has dominated the last 8 minutes.")


def test_dominance_streak_observation_silent_on_short_streak():
    dominance = BuySellDominance(window_minutes=8, buy_volume=800, sell_volume=200, dominance_ratio=0.8, dominant_side="buy", consecutive_dominant_minutes=2)
    assert _dominance_streak_observation(dominance) is None


def test_spike_observation():
    spike = VolumeSpike(is_spike=True, multiple=3.1, baseline_source="historical_20d", baseline_volume=100.0)
    assert _spike_observation(spike) == (1, "Volume spike detected: 3.1x the recent average.")


def test_dryup_observation():
    dryup = VolumeDryUp(is_dryup=True, fraction=0.35, baseline_source="historical_20d", baseline_volume=100.0)
    assert _dryup_observation(dryup) == (3, "Volume has dried up to 35% of the recent average.")


def test_absorption_observation():
    absorption = AbsorptionSignal(detected=True, range_ratio=0.4, volume_multiple=3.0, side_hint="buy_absorption")
    assert _absorption_observation(absorption) == (1, "High volume with little price movement suggests absorption near current levels.")


def test_exhaustion_observation():
    exhaustion = ExhaustionSignal(detected=True, direction="up", move_over_window=50.0, volume_multiple=10.0, wick_ratio=0.5)
    result = _exhaustion_observation(exhaustion)
    assert result[1] == "A volume climax with a rejection wick suggests possible exhaustion of the up-move."


def test_institutional_observation():
    institutional = InstitutionalParticipation(score=85, label="Very High", rvol_component=1.0, blockiness_component=0.5, dominance_component=1.0)
    dominance = BuySellDominance(window_minutes=8, buy_volume=800, sell_volume=200, dominance_ratio=0.8, dominant_side="buy", consecutive_dominant_minutes=6)
    result = _institutional_observation(institutional, dominance)
    assert "Very High" in result[1] and "buy" in result[1]


def test_build_observations_caps_at_four_sorted_by_priority():
    enriched = _minimal_enriched()
    rvol = RvolReading(primary=RvolBaselineResult(group="last_20_days", interval_rvol_pct=200.0, cumulative_rvol_pct=200.0, label="Above Average", sample_days=10))
    dominance = BuySellDominance(window_minutes=8, buy_volume=800, sell_volume=200, dominance_ratio=0.8, dominant_side="buy", consecutive_dominant_minutes=8)
    spike = VolumeSpike(is_spike=True, multiple=3.0, baseline_source="historical_20d", baseline_volume=100.0)
    dryup = VolumeDryUp(is_dryup=False, fraction=None, baseline_source=None, baseline_volume=None)
    absorption = AbsorptionSignal(detected=True, range_ratio=0.3, volume_multiple=3.0, side_hint="buy_absorption")
    exhaustion = ExhaustionSignal(detected=True, direction="up", move_over_window=10.0, volume_multiple=5.0, wick_ratio=0.5)
    institutional = InstitutionalParticipation(score=85, label="Very High", rvol_component=1.0, blockiness_component=0.5, dominance_component=1.0)
    similarity = HistoricalSimilarity()

    observations = build_observations(enriched, rvol, dominance, None, spike, dryup, absorption, exhaustion, institutional, similarity)

    assert len(observations) == 4
    # priority-1 candidates (dominance streak, spike, absorption, exhaustion) win over
    # priority-2 candidates (rvol, institutional) when more than 4 qualify.
    assert observations[0] == "Buy volume has dominated the last 8 minutes."
    assert "Volume spike detected" in observations[1]
    assert "absorption" in observations[2]
    assert "exhaustion" in observations[3]
