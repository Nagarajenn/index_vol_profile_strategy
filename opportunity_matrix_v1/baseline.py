"""Chronological random-entry baseline (Step 13) -- a comparator, not a target.

For every event, draw bars from the SAME symbol-day (same day type), the SAME window bucket,
with a random direction, requiring the SAME liquidity check on the SAME leg rule, and apply
the SAME entry/exit mechanics. Draws never cross days, so no future day contributes."""

import random

from opportunity_matrix_v1.counterfactual import counterfactual
from opportunity_matrix_v1.events import window_of
from opportunity_matrix_v1.response import event_atm_offset, liquidity_ok


def baseline_rows(day, events, cfg) -> list[dict]:
    rng = random.Random(f"{cfg.baseline_seed}-{day.symbol}-{day.trade_date}")
    by_window = {}
    for i in range(cfg.lookback_bars + 1, len(day) - 2):
        by_window.setdefault(window_of(day.known_at(i).time(), cfg), []).append(i)
    out = []
    for e in events:
        pool = by_window.get(e["window"], [])
        tries, drawn = 0, 0
        while drawn < cfg.baseline_per_event and tries < 50 and pool:
            tries += 1
            i = rng.choice(pool)
            d = rng.choice([1, -1])
            off = event_atm_offset(day, i)
            key = ("CE" if d > 0 else "PE", off)
            if key not in day.legs or not liquidity_ok(day, key, i, cfg)[0]:
                continue
            fake = dict(event_id=f"RB-{e['event_id']}-{drawn}", event_cluster_id=e["event_cluster_id"], i=i, dir=d, onset_i=None)
            gate = dict(selected_option=key[0], selected_offset=off)
            for lbl in cfg.executable_entries:
                cf = counterfactual(fake, gate, day, cfg, lbl)
                if cf and cf.get("status") == "OK":
                    cf.update(paired_event=e["event_id"], window=e["window"], expiry_flag=day.is_expiry, baseline=True)
                    out.append(cf)
            drawn += 1
    return out
