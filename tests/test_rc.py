"""Synthetic check: simulate the 2R2C model with known parameters, fit, recover them.

Run: uv run python tests/test_rc.py
"""

import numpy as np
import pandas as pd

from rc_house.models import two_floor_2r2c


def synthetic(days=14, seed=0):
    rng = np.random.default_rng(seed)
    t = pd.date_range("2026-11-01", periods=days * 96, freq="15min", tz="UTC")
    h = (t.hour + t.minute / 60).to_numpy()
    T_out = 3 + 5 * np.sin(2 * np.pi * (h - 9) / 24) + np.cumsum(rng.normal(0, 0.05, len(t)))
    I = np.clip(400 * np.sin(np.pi * (h - 7) / 10), 0, None) * rng.uniform(0.3, 1, len(t))
    # thermostat-like pump cycling
    pump = {f: (rng.random(len(t)) < 0.4).astype(float) for f in ("og", "eg")}
    return pd.DataFrame({
        "T_aussen": T_out, "I_glob": I,
        "Q_og": 6000 * pump["og"], "Q_eg": 5000 * pump["eg"],
    }, index=t)


def test_recovery():
    net, p0 = two_floor_2r2c("measured")
    true = {**p0, "H_ea_og": 140.0, "H_ia_og": 45.0, "H_ea_eg": 110.0, "H_ia_eg": 25.0,
            "k_Q_og": 0.8, "k_Q_eg": 1.1, "C_Ti_og": 8e6, "x0_Te_og": 16.0, "x0_Te_eg": 14.0}
    d = synthetic()
    d["T_og"] = d["T_eg"] = 18.0  # initial states for the measured nodes
    sim = net.simulate(true, d)
    rng = np.random.default_rng(1)
    d["T_og"] = sim["Ti_og"] + rng.normal(0, 0.05, len(d))
    d["T_eg"] = sim["Ti_eg"] + rng.normal(0, 0.05, len(d))

    # well-identifiable subset free, rest fixed at truth
    free = ["H_ea_og", "H_ia_og", "H_ea_eg", "H_ia_eg", "k_Q_og", "k_Q_eg", "C_Ti_og", "x0_Te_og", "x0_Te_eg"]
    fixed = {k: v for k, v in true.items() if k not in free}
    fit = net.fit(d, p0, fixed=fixed)
    print(fit.summary().loc[free])
    print("rmse", fit.rmse)
    for k in free:
        assert abs(fit.params[k] - true[k]) / abs(true[k]) < 0.1, k
    assert fit.rmse < 0.07

    # steady state: total heat load equals UA·ΔT for a network without hidden coupling quirks
    q = net.heat_load(fit.params, T_in=20.0, T_out={"T_aussen": -13.0})
    print("heat load at -13 °C:", q.round(0).to_dict(), "total", round(q.sum()))
    assert q.sum() > 0


if __name__ == "__main__":
    test_recovery()
    print("ok")
