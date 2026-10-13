"""Relevant Home Assistant entities for the RC model.

Each signal maps to (entity_id, field). Numeric states are in field "value",
climate attributes in their own fields (e.g. "hvac_action_str", "temperature").
Older entity names (raumthermostat_*, <room>_call_for_heat) stopped on 2026-09-21
after a rename and are ignored.
"""

# room id -> floor; room ids match the Excel coupling matrix (lowercase, no umlauts)
ROOMS = {
    "wohnzimmer": "og",
    "schlafzimmer": "og",
    "bad": "og",
    "gastzimmer": "eg",
    "extrazimmer": "eg",
    "vorhaus": "eg",  # Vorhaus EG (next to Vorkeller)
}

# Raumthermostat II 230V: powered via the heating control, report 0.0 while unpowered
# (2026-09-22 .. 2026-10-02 06:00, heating system off before the season).
# Their relays switch the circulation pumps.
THERMOSTAT_230V = {"wohnzimmer", "gastzimmer"}

# heating circuits: relay room (pump on <=> hvac_action == heating) and supply sensor.
# Both circuits share one return sensor T_RL.
CIRCUITS = {
    "og": {"relay": "wohnzimmer", "T_VL": "T_VL_og"},
    "eg": {"relay": "gastzimmer", "T_VL": "T_VL_eg"},
}

# Grundfos UPS 25-50 180, stage 2: flow read off the pump curve is uncertain,
# ~0.7 m³/h is the initial guess; calibrate via oil consumption.
MDOT_INIT = 0.7 * 998.0 / 3600.0  # kg/s
CP_WATER = 4186.0  # J/(kg K)

# Bosch naming per room: (sensor prefix, climate entity, call_for_heat binary_sensor)
_BOSCH = {
    "wohnzimmer": ("wohnzimmer_raumthermostat_wohnzimmer", "wohnzimmer_wohnzimmer"),
    "schlafzimmer": ("schlafzimmer_raumthermostat_schlafzimmer", "schlafzimmer_schlafzimmer"),
    "bad": ("bad_raumthermostat_bad", "bad_bad"),
    "gastzimmer": ("gastzimmer_raumthermostat_gastezimmer", "gastzimmer_gastezimmer"),
    "extrazimmer": ("extra_zimmer_raumthermostat_extrazimmer", "extra_zimmer_extrazimmer"),
    "vorhaus": ("vorhaus_raumthermostat_vorhaus", "vorhaus_vorhaus"),
}

SIGNALS: dict[str, tuple[str, str]] = {}
for room, (sensor, climate) in _BOSCH.items():
    SIGNALS[f"T_{room}"] = (sensor, "value")                    # room temperature, °C
    SIGNALS[f"RH_{room}"] = (f"{sensor}_2", "value")            # relative humidity, %
    SIGNALS[f"Tset_{room}"] = (climate, "temperature")          # setpoint, °C
    SIGNALS[f"heat_{room}"] = (climate, "hvac_action_str")      # heating/idle -> 1/0
    SIGNALS[f"cfh_{room}"] = (f"{climate}_call_for_heat", "value")  # call for heat 0/1

SIGNALS.update({
    # GeoSphere Austria, station Weyer (in Influx only since 2026-10-13)
    "T_aussen": ("weyer_temperature", "value"),
    "RH_aussen": ("weyer_humidity", "value"),
    "I_glob": ("weyer_global_radiation", "value"),       # W/m²
    "wind": ("weyer_wind_speed", "value"),               # km/h
    "sun_10min": ("weyer_sun_last_10_minutes", "value"),  # s
    # Shelly i4 Gen3 in the boiler room (since 2026-10-13), pipe sensors.
    # One common return for both circuits.
    "T_VL_og": ("shellyi4g3_dcb4d9d9edf0_temperature", "value"),    # Vorlauf OG
    "T_RL": ("shellyi4g3_dcb4d9d9edf0_temperature_2", "value"),     # Rücklauf (common)
    "T_VL_eg": ("shellyi4g3_dcb4d9d9edf0_temperature_3", "value"),  # Vorlauf EG
    # TODO: inputs unused so far (always 0) - pump sensing?
    **{f"shelly_in{i}": (f"shellyi4g3_dcb4d9d9edf0_input_{i}", "value") for i in range(4)},
})

# string states -> numbers
STRING_MAP = {"heating": 1.0, "idle": 0.0, "off": 0.0}

# physically implausible values -> NaN (Bosch reports 0.0 when a thermostat is unavailable)
VALID_RANGE = {"T_": (1.0, 40.0), "RH_": (1.0, 100.0)}
