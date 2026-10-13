# Thermal Model House Weyer

Grey-box **RC thermal model** of a house near Weyer (Upper Austria), identified from Home Assistant data in InfluxDB. Goal: understand losses and couplings, and get the heat load for sizing a heat pump to replace the oil boiler.

## House

- Oil boiler with two heating circuits, **EG** and **OG**. Each circuit has a fixed-speed Grundfos UPS 25-50 180 pump at stage 2 (55 W), see [docs/](docs/).
- Each pump is switched by the relay of a Bosch Raumthermostat II 230V: Wohnzimmer → OG, Gastzimmer → EG.
- Pipe sensors (Shelly i4 Gen3) measure Vorlauf OG, Vorlauf EG and one **common** Rücklauf.
- Radiators have partly thermostatic valves and partly manual valves.
- Room couplings are recorded in [docs/adjacency_matrix.xlsx](docs/adjacency_matrix.xlsx) (`w` wall, `d` door, `o` open, `c` ceiling/floor, `cu` ceiling/floor insulated).

## Data

- InfluxDB 2, bucket `homeassistant`. Tags are `entity_id`, `domain` and `friendly_name`; numeric values are in field `value`, attributes in their own fields.
- All signals used are configured in [entities.py](rc-house/src/rc_house/entities.py).
- The pump state is the `hvac_action_str` attribute of the relay rooms' `climate` entities.
- Credentials: `INFLUX_TOKEN` (and optionally `INFLUX_URL`), or `influx_api_token.txt` in the repo root (line 1 host, line 2 token). This file is git-ignored.

Caveats:
- GeoSphere Weyer and VL/RL are only logged since 2026-10-13.
- The 230V thermostats report 0.0 °C while unpowered (heating off). The loader masks these values and keeps them as `pwr_<room>`.
- Manual readings (oil tanks, burner hours, `input_number`) are not in Influx yet. They are needed for calibrating ṁ.

## Approach

1. Heat per circuit: Q = ṁ c_p (T_VL − T_RL) × pump duty. ṁ ≈ 0.7 m³/h is a guess; calibrate it via oil consumption (≈ 10 kWh/L × η).
2. Start with a 2R2C model per floor, with the floors coupled through the ceiling and EG coupled to the ground. Later: one node per room, built from the adjacency matrix.
3. Identify offline with output-error least squares; later online (EKF/RLS) as a service on the NAS, writing to Influx/Grafana.
4. Data is resampled to 15 min as a zero-order hold.

## Usage

```
cd rc-house
uv sync
uv run jupyter lab              # notebooks/01_daten -> 02_rc_2r2c
uv run python tests/test_rc.py  # synthetic parameter recovery
```

| Path | Content |
|---|---|
| `rc-house/src/rc_house/influx.py` | Influx access, entity dump, zero-order-hold resampling |
| `rc-house/src/rc_house/prep.py` | floor temperatures, pump duty, heat input |
| `rc-house/src/rc_house/rc.py` | generic RC network: simulate, fit (±σ), heat load |
| `rc-house/src/rc_house/models.py` | model structures with initial values |
| `rc-house/notebooks/` | `01_daten` (data export), `02_rc_2r2c` (identification) |

Conventions: SI units with temperatures in °C. Room IDs are lowercase without umlauts. Code is in English, plot labels in German.
