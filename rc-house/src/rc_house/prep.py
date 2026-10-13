"""Turn the resampled house data into model inputs."""

import numpy as np
import pandas as pd

from .entities import CIRCUITS, CP_WATER, MDOT_INIT, ROOMS


def floor_temperatures(df: pd.DataFrame, weights: dict[str, float] | None = None) -> pd.DataFrame:
    """Mean room temperature per floor (weights e.g. room areas, default equal)."""
    out = {}
    for floor in sorted(set(ROOMS.values())):
        rooms = [r for r, f in ROOMS.items() if f == floor]
        w = pd.Series({r: (weights or {}).get(r, 1.0) for r in rooms})
        T = df[[f"T_{r}" for r in rooms]].set_axis(rooms, axis=1)
        # weighted mean over the rooms that are available in each interval
        out[f"T_{floor}"] = (T * w).sum(axis=1, min_count=1) / T.notna().mul(w).sum(axis=1).replace(0, np.nan)
    return pd.DataFrame(out)


def pump_duty(df: pd.DataFrame) -> pd.DataFrame:
    """Fraction of each interval the circuit pump runs (relay = hvac_action heating)."""
    return pd.DataFrame({f"pump_{c}": df[f"heat_{v['relay']}"] for c, v in CIRCUITS.items()})


def heat_input(df: pd.DataFrame, mdot: dict[str, float] | None = None) -> pd.DataFrame:
    """Heat delivered per circuit, Q = ṁ c_p (T_VL − T_RL) · pump duty, in W.

    Approximations:
    - T_RL is a common return; while both pumps run it is a mixed temperature.
    - The pipe sensors only see the water temperature while it flows; multiplying
      by the interval-mean duty ignores this within an interval.
    NaN where VL/RL are not available (before 2026-10-13).
    """
    duty = pump_duty(df)
    out = {}
    for c, v in CIRCUITS.items():
        m = (mdot or {}).get(c, MDOT_INIT)
        dT = (df[v["T_VL"]] - df["T_RL"]).clip(lower=0)
        out[f"Q_{c}"] = m * CP_WATER * dT * duty[f"pump_{c}"]
    return pd.DataFrame(out)


def model_data(df: pd.DataFrame, weights=None, mdot=None, max_gap: str = "2h") -> pd.DataFrame:
    """All model columns, short gaps in the inputs interpolated."""
    every = pd.Timedelta(df.index.freq or (df.index[1] - df.index[0]))
    limit = int(pd.Timedelta(max_gap) / every)
    m = pd.concat([
        floor_temperatures(df, weights),
        pump_duty(df),
        heat_input(df, mdot),
        df[["T_aussen", "I_glob"]],
    ], axis=1)
    inputs = [c for c in m if not c.startswith("T_") or c == "T_aussen"]
    m[inputs] = m[inputs].interpolate(limit=limit, limit_area="inside")
    return m
