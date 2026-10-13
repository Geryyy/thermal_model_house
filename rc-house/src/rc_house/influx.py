"""InfluxDB access for the Home Assistant bucket."""

import os
import warnings
from pathlib import Path

import pandas as pd
from influxdb_client import InfluxDBClient

BUCKET = "homeassistant"
ORG_ID = "d504e6dc24b940e3"
DEFAULT_URL = "https://influx.home.arpa"

# influx_api_token.txt in the repo root: line 1 = host, line 2 = token (never commit)
TOKEN_FILE = Path(__file__).resolve().parents[3] / "influx_api_token.txt"


def _credentials() -> tuple[str, str]:
    url = os.environ.get("INFLUX_URL", DEFAULT_URL)
    token = os.environ.get("INFLUX_TOKEN")
    if not token and TOKEN_FILE.exists():
        lines = TOKEN_FILE.read_text().split()
        token = lines[-1]
    if not token:
        raise RuntimeError("Set INFLUX_TOKEN or provide influx_api_token.txt")
    return url, token


def client() -> InfluxDBClient:
    url, token = _credentials()
    # LAN reverse proxy with self-signed certificate
    warnings.filterwarnings("ignore", message="Unverified HTTPS request")
    return InfluxDBClient(url=url, token=token, org=ORG_ID, verify_ssl=False, timeout=120_000)


def list_datapoints(start: str = "-30d") -> pd.DataFrame:
    """One row per series (measurement, entity_id, field) with last value and time."""
    flux = f"""
from(bucket: "{BUCKET}")
  |> range(start: {start})
  |> last()
  |> keep(columns: ["_time", "_value", "_measurement", "_field", "entity_id", "domain", "friendly_name"])
"""
    with client() as c:
        tables = c.query_api().query(flux)
    rows = [
        {
            "entity_id": r.values.get("entity_id"),
            "domain": r.values.get("domain"),
            "friendly_name": r.values.get("friendly_name"),
            "measurement": r.get_measurement(),
            "field": r.get_field(),
            "last_value": r.get_value(),
            "last_time": r.get_time(),
        }
        for t in tables
        for r in t.records
    ]
    df = pd.DataFrame(rows)
    df["last_time"] = df["last_time"].dt.tz_convert(None)
    return df.sort_values(["domain", "entity_id", "measurement", "field"]).reset_index(drop=True)


def load_raw(signals: dict[str, tuple[str, str]], start: str, stop: str = "now()") -> dict[str, pd.Series]:
    """Raw (event-based) series per signal name, values mapped to float."""
    from .entities import STRING_MAP

    ids = sorted({e for e, _ in signals.values()})
    fields = sorted({f for _, f in signals.values()})
    id_rx = "|".join(ids)
    field_set = ", ".join(f'"{f}"' for f in fields)
    flux = f"""
from(bucket: "{BUCKET}")
  |> range(start: {start}, stop: {stop})
  |> filter(fn: (r) => r.entity_id =~ /^({id_rx})$/ and contains(value: r._field, set: [{field_set}]))
  |> keep(columns: ["_time", "_value", "_field", "entity_id"])
"""
    points: dict[tuple[str, str], list] = {}
    with client() as c:
        for t in c.query_api().query(flux):
            for r in t.records:
                points.setdefault((r.values["entity_id"], r.get_field()), []).append((r.get_time(), r.get_value()))

    out = {}
    for name, key in signals.items():
        if key not in points:
            continue
        t, v = zip(*points[key])
        v = [STRING_MAP.get(x, float("nan")) if isinstance(x, str) else float(x) for x in v]
        s = pd.Series(v, index=pd.DatetimeIndex(t).tz_convert("UTC"), name=name).sort_index()
        out[name] = s[~s.index.duplicated(keep="last")]
    return out


def resample_hold(raw: dict[str, pd.Series], every: str = "15min", start=None, stop=None) -> pd.DataFrame:
    """Time-weighted mean per interval, treating each series as zero-order hold.

    HA writes on change, so a value is valid until the next one. For 0/1 signals
    the result is the duty cycle within the interval.
    """
    from .entities import THERMOSTAT_230V, VALID_RANGE

    start = pd.Timestamp(start or min(s.index[0] for s in raw.values())).floor(every)
    stop = pd.Timestamp(stop or max(s.index[-1] for s in raw.values())).ceil(every)
    fine = pd.date_range(start, stop, freq="1min", tz="UTC")
    def hold(s):
        return s.reindex(s.index.union(fine)).ffill().reindex(fine)

    cols = {}
    for name, s in raw.items():
        if name.startswith("T_") and name[2:] in THERMOSTAT_230V:
            # Raumthermostat II 230V reports 0.0 when the heating control cuts its power
            cols["pwr_" + name[2:]] = hold((s != 0).astype(float))
        for prefix, (lo, hi) in VALID_RANGE.items():
            if name.startswith(prefix):
                s = s.where((s >= lo) & (s <= hi))
        # hold each value until the next sample; nothing before the first sample
        s = s.dropna()
        if s.empty:
            continue
        cols[name] = hold(s)
    df = pd.DataFrame(cols).resample(every, label="left").mean()
    return df


def entities(datapoints: pd.DataFrame) -> pd.DataFrame:
    """Collapse to one row per entity: unit, numeric last value, list of attribute fields."""
    g = datapoints.groupby(["domain", "entity_id"], dropna=False)
    num = datapoints[datapoints["field"] == "value"].set_index(["domain", "entity_id"])
    out = pd.DataFrame({
        "friendly_name": g["friendly_name"].first(),
        "unit": g["measurement"].first(),
        "value": num["last_value"].groupby(level=[0, 1]).first(),
        "last_time": g["last_time"].max(),
        "fields": g["field"].agg(lambda s: ",".join(sorted(set(s)))),
    })
    return out.reset_index()
