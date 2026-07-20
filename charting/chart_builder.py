from datetime import datetime
from pathlib import Path

import matplotlib.patches as patches
import matplotlib.pyplot as plt
import mplfinance as mpf
import pandas as pd

from analytics.volume_profile import VolumeProfileResult
from charting import style


def _find_ax(axlist, ylabel: str):
    for ax in axlist:
        if ax.get_visible() and ax.get_ylabel() == ylabel:
            return ax
    return axlist[0]


def _draw_value_area(ax, vp: VolumeProfileResult | None, label_prefix: str, poc_color: str) -> None:
    if vp is None:
        return
    ax.axhspan(vp.val, vp.vah, color=style.COLOR_VALUE_AREA, alpha=style.VALUE_AREA_ALPHA, zorder=0)
    ax.axhline(vp.poc, color=poc_color, linestyle="--", linewidth=1.2, zorder=2)
    ax.text(
        1.001,
        vp.poc,
        f"{label_prefix} POC {vp.poc:,.0f}",
        transform=ax.get_yaxis_transform(),
        color=poc_color,
        fontsize=7,
        va="center",
    )


def _draw_volume_profile_panel(fig, ax_price, vp: VolumeProfileResult | None) -> None:
    if vp is None or not vp.bins:
        return
    pos = ax_price.get_position()
    panel_width = 0.10
    ax_vp = fig.add_axes([pos.x1 - panel_width, pos.y0, panel_width, pos.y1 - pos.y0])
    ax_vp.set_ylim(ax_price.get_ylim())
    ax_vp.patch.set_alpha(0.0)

    prices = sorted(vp.bins)
    volumes = [vp.bins[p] for p in prices]
    bin_size = prices[1] - prices[0] if len(prices) > 1 else 1
    ax_vp.barh(
        [p + bin_size / 2 for p in prices],
        volumes,
        height=bin_size * 0.9,
        color=style.COLOR_VOLUME_PROFILE_BAR,
        alpha=0.55,
        zorder=1,
    )
    ax_vp.axis("off")


def _time_to_xpos(index: pd.DatetimeIndex, ts: pd.Timestamp) -> float:
    """mplfinance plots candles at integer x-positions (0..N-1), not real
    datetimes — it collapses gaps (nights/weekends) so bars stay evenly
    spaced. Any overlay drawn with a raw Timestamp x-coordinate would land
    in the wrong place, so every overlay must go through this mapping,
    including trendline rays that extrapolate past the last candle.
    """
    if len(index) == 0:
        return 0.0
    if ts in index:
        return float(index.get_loc(ts))

    pos = index.searchsorted(ts)
    if pos <= 0:
        bar_delta = (index[1] - index[0]) if len(index) > 1 else pd.Timedelta(minutes=5)
        return -float((index[0] - ts) / bar_delta)
    if pos >= len(index):
        bar_delta = (index[-1] - index[-2]) if len(index) > 1 else pd.Timedelta(minutes=5)
        return float(len(index) - 1) + float((ts - index[-1]) / bar_delta)

    bar_delta = index[pos] - index[pos - 1]
    frac = (ts - index[pos - 1]) / bar_delta
    return float(pos - 1) + float(frac)


def _draw_swings(ax, index: pd.DatetimeIndex, overlays: dict) -> None:
    for ts, price in overlays.get("swing_highs", []):
        ax.scatter([_time_to_xpos(index, ts)], [price], marker="v", color=style.COLOR_SWING_HIGH, s=35, zorder=4)
    for ts, price in overlays.get("swing_lows", []):
        ax.scatter([_time_to_xpos(index, ts)], [price], marker="^", color=style.COLOR_SWING_LOW, s=35, zorder=4)


def _draw_trendlines(ax, index: pd.DatetimeIndex, overlays: dict) -> None:
    for tl in overlays.get("trendlines", []):
        (t0, p0), (t1, p1) = tl["points"]
        color = style.COLOR_TRENDLINE_UP if tl.get("direction") == "up" else style.COLOR_TRENDLINE_DOWN
        x0, x1 = _time_to_xpos(index, t0), _time_to_xpos(index, t1)
        ax.plot([x0, x1], [p0, p1], color=color, linestyle="--", linewidth=1.3, zorder=3)


def _draw_sr_zones(ax, overlays: dict) -> None:
    for zone in overlays.get("sr_zones", []):
        color = style.COLOR_SUPPORT_ZONE if zone.get("kind") == "support" else style.COLOR_RESISTANCE_ZONE
        ax.axhspan(zone["low"], zone["high"], color=color, alpha=0.10, zorder=0)


def _draw_breakout_boxes(ax, index: pd.DatetimeIndex, overlays: dict) -> None:
    for box in overlays.get("breakout_boxes", []):
        color = style.COLOR_BREAKOUT_CONFIRMED if box.get("status", "").startswith("confirmed") else style.COLOR_BREAKOUT_BOX
        x_start = _time_to_xpos(index, box["t_start"])
        x_end = _time_to_xpos(index, box["t_end"])
        rect = patches.Rectangle(
            (x_start, box["p_low"]),
            x_end - x_start,
            box["p_high"] - box["p_low"],
            linewidth=1.0,
            edgecolor=color,
            facecolor="none",
            linestyle="-" if box.get("status", "").startswith("confirmed") else ":",
            zorder=2,
        )
        ax.add_patch(rect)


def render_chart(
    candles_5min: pd.DataFrame,
    vwap_5min: pd.Series,
    volume_profile: VolumeProfileResult | None,
    symbol: str,
    as_of: datetime,
    out_path: Path,
    prior_day_poc: float | None = None,
    overlays: dict | None = None,
) -> Path:
    """Render a 5-min candlestick chart with VWAP, developing Volume Profile
    (POC/Value Area), yesterday's POC, and (once M4 lands) swing/trendline/
    S-R/breakout overlays, saved as a PNG.
    """
    overlays = overlays or {}
    ohlc = candles_5min.set_index("timestamp")[["open", "high", "low", "close", "volume"]]

    addplots = []
    vwap_aligned = vwap_5min.reindex(ohlc.index).ffill()
    if not vwap_aligned.dropna().empty:
        addplots.append(mpf.make_addplot(vwap_aligned, color=style.COLOR_VWAP, width=1.3))

    plot_kwargs = dict(
        type="candle",
        volume=True,
        style=style.MPF_STYLE,
        returnfig=True,
        figsize=(14, 8),
        datetime_format="%H:%M",
        xrotation=0,
        title=f"{symbol} 5-min - as of {as_of.strftime('%Y-%m-%d %H:%M')} IST",
    )
    if addplots:
        plot_kwargs["addplot"] = addplots

    fig, axlist = mpf.plot(ohlc, **plot_kwargs)

    ax_price = _find_ax(axlist, "Price")

    _draw_value_area(ax_price, volume_profile, "Today", style.COLOR_POC)
    if prior_day_poc is not None:
        ax_price.axhline(prior_day_poc, color=style.COLOR_PRIOR_POC, linestyle=":", linewidth=1.2, zorder=2)
        ax_price.text(
            1.001,
            prior_day_poc,
            f"Y-POC {prior_day_poc:,.0f}",
            transform=ax_price.get_yaxis_transform(),
            color=style.COLOR_PRIOR_POC,
            fontsize=7,
            va="center",
        )

    _draw_swings(ax_price, ohlc.index, overlays)
    _draw_trendlines(ax_price, ohlc.index, overlays)
    _draw_sr_zones(ax_price, overlays)
    _draw_breakout_boxes(ax_price, ohlc.index, overlays)
    _draw_volume_profile_panel(fig, ax_price, volume_profile)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out_path


def build_overlays(levels) -> dict:
    """Convert a `analytics.levels.LevelsResult` into the plain-dict overlay
    shape `render_chart` expects (kept as dicts, not typed, so chart_builder
    doesn't need to import analytics.levels and risk a circular import).
    """
    return {
        "swing_highs": [(s.timestamp, s.price) for s in levels.swings if s.kind == "high"],
        "swing_lows": [(s.timestamp, s.price) for s in levels.swings if s.kind == "low"],
        "trendlines": [{"points": t.points, "direction": t.direction} for t in levels.trendlines],
        "sr_zones": (
            ([{"low": levels.support.low, "high": levels.support.high, "kind": "support"}] if levels.support else [])
            + ([{"low": levels.resistance.low, "high": levels.resistance.high, "kind": "resistance"}] if levels.resistance else [])
        ),
        "breakout_boxes": [
            {"t_start": b.t_start, "t_end": b.t_end, "p_low": b.p_low, "p_high": b.p_high, "status": b.status}
            for b in levels.breakout_boxes
        ],
    }
