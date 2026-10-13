"""Model structures with initial values."""

from .rc import RCNetwork


def two_floor_2r2c(heat: str = "measured") -> tuple[RCNetwork, dict]:
    """2R2C per floor (air node Ti, envelope node Te), floors coupled via the ceiling.

    heat="measured": input Q_<floor> [W] from VL/RL, gain k_Q ≈ 1 (absorbs ṁ error).
    heat="duty":     input pump_<floor> [0..1], gain k_P = mean radiator power [W] while
                     the pump runs - usable before VL/RL were logged.
    EG couples to the ground (constant T_erdreich), OG to outside via the attic (in H_ea_og).
    """
    gain_in, gain_p, g0 = ("Q", "k_Q", 1.0) if heat == "measured" else ("pump", "k_P", 5000.0)
    links, gains, p0 = [], [], {}
    for f in ("og", "eg"):
        links += [
            (f"Ti_{f}", f"Te_{f}", f"H_ie_{f}"),     # air <-> envelope/mass
            (f"Te_{f}", "T_aussen", f"H_ea_{f}"),    # envelope <-> outside
            (f"Ti_{f}", "T_aussen", f"H_ia_{f}"),    # windows, ventilation
        ]
        gains += [
            (f"Ti_{f}", f"{gain_in}_{f}", f"{gain_p}_{f}"),
            (f"Ti_{f}", "I_glob", f"A_sol_{f}"),     # effective solar aperture [m²]
        ]
        p0.update({
            f"C_Ti_{f}": 5e6, f"C_Te_{f}": 5e7,
            f"H_ie_{f}": 300.0, f"H_ea_{f}": 100.0, f"H_ia_{f}": 30.0,
            f"{gain_p}_{f}": g0, f"A_sol_{f}": 2.0, f"x0_Te_{f}": 15.0,
        })
    links += [("Ti_og", "Ti_eg", "H_floor"), ("Ti_eg", "T_erdreich", "H_g")]
    p0.update({"H_floor": 100.0, "H_g": 30.0, "T_erdreich": 10.0})

    net = RCNetwork(
        states=["Ti_og", "Te_og", "Ti_eg", "Te_eg"],
        links=links,
        boundaries=["T_aussen"],
        const_boundaries=["T_erdreich"],
        gains=gains,
        measured={"Ti_og": "T_og", "Ti_eg": "T_eg"},
    )
    return net, p0
