"""Linear RC network: simulation, least-squares identification, steady-state heat load.

Parameter naming decides the transform used in the fit:
  C_*  capacities [J/K], H_* conductances [W/K], k_* / A_* gains   -> log (positive)
  T_*  constant boundary temperatures [°C], x0_* hidden initial states -> linear
"""

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.linalg import expm
from scipy.optimize import least_squares

_LOG_PREFIX = ("C_", "H_", "k_", "A_")


@dataclass
class RCNetwork:
    states: list[str]                        # node names; capacity param "C_<node>"
    links: list[tuple[str, str, str]]        # (node, node or boundary, H param)
    boundaries: list[str] = field(default_factory=list)   # data columns [°C]
    const_boundaries: list[str] = field(default_factory=list)  # T_* params [°C]
    gains: list[tuple[str, str, str]] = field(default_factory=list)  # (node, data column, gain param) -> W
    measured: dict[str, str] = field(default_factory=dict)  # node -> data column

    # ---- structure ---------------------------------------------------------
    @property
    def inputs(self) -> list[str]:
        """Columns of u: boundary temperatures, then gain inputs."""
        return self.boundaries + list(dict.fromkeys(g[1] for g in self.gains))

    @property
    def hidden(self) -> list[str]:
        return [s for s in self.states if s not in self.measured]

    def param_names(self) -> list[str]:
        names = [f"C_{s}" for s in self.states] + [l[2] for l in self.links]
        names += self.const_boundaries + [g[2] for g in self.gains] + [f"x0_{s}" for s in self.hidden]
        return list(dict.fromkeys(names))

    def matrices(self, p: dict) -> tuple[np.ndarray, np.ndarray]:
        """Continuous dx/dt = A x + B [u; 1] (last column carries constant boundaries)."""
        n, inp = len(self.states), self.inputs
        si = {s: i for i, s in enumerate(self.states)}
        A = np.zeros((n, n))
        B = np.zeros((n, len(inp) + 1))
        for a, b, h in self.links:
            H = p[h]
            for x, y in ((a, b), (b, a)):
                if x not in si:
                    continue
                A[si[x], si[x]] -= H
                if y in si:
                    A[si[x], si[y]] += H
                elif y in self.const_boundaries:
                    B[si[x], -1] += H * p[y]
                else:
                    B[si[x], inp.index(y)] += H
        for node, col, g in self.gains:
            B[si[node], inp.index(col)] += p[g]
        C = np.array([p[f"C_{s}"] for s in self.states])
        return A / C[:, None], B / C[:, None]

    # ---- simulation --------------------------------------------------------
    def simulate(self, p: dict, data: pd.DataFrame) -> pd.DataFrame:
        """Zero-order-hold simulation over data's index (inputs must be complete)."""
        dt = (data.index[1] - data.index[0]).total_seconds()
        A, B = self.matrices(p)
        n, m = B.shape
        M = expm(np.block([[A, B], [np.zeros((m, n + m))]]) * dt)
        Ad, Bd = M[:n, :n], M[:n, n:]
        U = np.column_stack([data[self.inputs].to_numpy(float), np.ones(len(data))])
        x = np.array([self._x0(s, p, data) for s in self.states])
        X = np.empty((len(data), n))
        for k in range(len(data)):
            X[k] = x
            x = Ad @ x + Bd @ U[k]
        return pd.DataFrame(X, index=data.index, columns=self.states)

    def _x0(self, s, p, data):
        if s in self.measured:
            col = data[self.measured[s]]
            return col.iloc[0] if pd.notna(col.iloc[0]) else col.dropna().iloc[0]
        return p[f"x0_{s}"]

    # ---- identification ----------------------------------------------------
    def fit(self, data: pd.DataFrame, p0: dict, fixed: dict | None = None, **ls_kw) -> "FitResult":
        """Output-error least squares on the measured nodes.

        p0: initial values for all free parameters; fixed: parameters held constant.
        """
        fixed = dict(fixed or {})
        free = [k for k in self.param_names() if k not in fixed]
        missing = [k for k in free if k not in p0]
        if missing:
            raise ValueError(f"no initial value for {missing}")
        data = self.usable(data)
        is_log = np.array([k.startswith(_LOG_PREFIX) for k in free])
        Y = data[[self.measured[s] for s in self.measured]].to_numpy(float)
        ok = np.isfinite(Y)

        def unpack(z):
            v = np.where(is_log, np.exp(z), z)
            return {**fixed, **dict(zip(free, v))}

        def residual(z):
            X = self.simulate(unpack(z), data)[list(self.measured)].to_numpy()
            return (X - Y)[ok]

        z0 = np.array([np.log(p0[k]) if lg else p0[k] for k, lg in zip(free, is_log)])
        res = least_squares(residual, z0, x_scale="jac", **ls_kw)

        # covariance from the Jacobian (in transformed space), mapped to linear values
        dof = max(ok.sum() - len(free), 1)
        s2 = 2 * res.cost / dof
        try:
            cov_z = np.linalg.pinv(res.jac.T @ res.jac) * s2
        except np.linalg.LinAlgError:
            cov_z = np.full((len(free), len(free)), np.nan)
        v = np.where(is_log, np.exp(res.x), res.x)
        var = np.diag(cov_z)
        sd = np.sqrt(np.where(var >= 0, var, np.nan)) * np.where(is_log, v, 1.0)  # NaN: not identifiable
        params = unpack(res.x)
        table = pd.DataFrame({"value": params, "sigma": pd.Series(dict(zip(free, sd)))})
        table["fixed"] = table.index.isin(list(fixed))
        sim = self.simulate(params, data)
        return FitResult(self, params, table, data, sim, res, np.sqrt(s2))

    def usable(self, data: pd.DataFrame) -> pd.DataFrame:
        """Longest contiguous block where all inputs are available."""
        good = data[self.inputs].notna().all(axis=1)
        if not good.any():
            raise ValueError("no interval with all inputs available: " + ", ".join(
                f"{c}={data[c].notna().sum()}" for c in self.inputs))
        block = (good != good.shift()).cumsum()[good]
        longest = block.value_counts().idxmax()
        return data.loc[block[block == longest].index]

    # ---- steady state ------------------------------------------------------
    def heat_load(self, p: dict, T_in: float | dict, T_out: dict) -> pd.Series:
        """Steady-state heat [W] needed per measured node to hold it at T_in.

        T_out: boundary column -> temperature (e.g. {"T_aussen": -13}); gain inputs are 0.
        """
        A, B = self.matrices(p)
        C = np.array([p[f"C_{s}"] for s in self.states])
        A, B = A * C[:, None], B * C[:, None]  # back to W/K
        u = np.array([T_out.get(c, 0.0) for c in self.inputs] + [1.0])
        si = {s: i for i, s in enumerate(self.states)}
        m = [si[s] for s in self.measured]
        h = [si[s] for s in self.hidden]
        xm = np.array([T_in[s] if isinstance(T_in, dict) else T_in for s in self.measured])
        xh = np.linalg.solve(A[np.ix_(h, h)], -(A[np.ix_(h, m)] @ xm + B[h] @ u)) if h else np.array([])
        q = -(A[np.ix_(m, m)] @ xm + (A[np.ix_(m, h)] @ xh if h else 0) + B[m] @ u)
        return pd.Series(q, index=list(self.measured), name="Q_W")


@dataclass
class FitResult:
    net: RCNetwork
    params: dict
    table: pd.DataFrame
    data: pd.DataFrame
    sim: pd.DataFrame
    ls: object
    rmse: float

    @property
    def residuals(self) -> pd.DataFrame:
        return pd.DataFrame({s: self.data[c] - self.sim[s] for s, c in self.net.measured.items()})

    def summary(self) -> pd.DataFrame:
        t = self.table.copy()
        t["rel_sigma_%"] = (100 * t["sigma"] / t["value"].abs()).round(1)
        return t
