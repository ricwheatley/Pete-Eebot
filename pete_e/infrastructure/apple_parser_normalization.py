"""Pure scalar, timestamp, unit, and environment normalisation for Apple JSON."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
import re
from typing import cast


ISO_WITH_TZ = "%Y-%m-%d %H:%M:%S %z"
RawDict = dict[object, object]

_NUMERIC_KEYS = ("qty", "value", "number", "doubleValue", "numericValue", "amount")
_NUMERIC_CONTAINER_KEYS = ("measurement", "data")
_UNIT_KEYS = ("unit", "unitName", "unitSymbol", "unitString")
_UNIT_CONTAINER_KEYS = ("value", "measurement")
_METADATA_VALUE_KEYS = ("numberValue", "numericValue", "qty", "doubleValue")


@dataclass(frozen=True)
class HeartRateValues:
    """Hold rounded bounds and a legacy-clamped heart-rate average."""

    minimum: int
    average: float
    maximum: int


@dataclass(frozen=True)
class Measure:
    """Hold a numeric environmental measure and its optional source unit."""

    value: float
    unit: str | None


@dataclass(frozen=True)
class WorkoutEnvironment:
    """Hold canonical workout temperature and humidity values."""

    temperature_degc: float | None
    humidity_percent: float | None


def as_raw_dict(value: object) -> RawDict | None:
    """Narrow only built-in dictionaries, matching the legacy shape checks."""

    if not isinstance(value, dict):
        return None
    return cast(RawDict, value)


def as_raw_list(value: object) -> list[object] | None:
    """Narrow only built-in lists, matching the legacy shape checks."""

    if not isinstance(value, list):
        return None
    return cast(list[object], value)


def parse_datetime(value: object) -> datetime | None:
    """Parse the export timestamp while preserving falsey and exception semantics."""

    if not value:
        return None
    return datetime.strptime(cast(str, value), ISO_WITH_TZ)


def numeric_value(data: object) -> float | None:
    """Extract the first numeric value from supported scalar and wrapper shapes."""

    if data is None:
        return None
    if isinstance(data, (int, float)):
        return float(data)
    if isinstance(data, str):
        return _numeric_from_string(data)
    mapping = as_raw_dict(data)
    if mapping is not None:
        return _numeric_from_mapping(mapping)
    if _is_recursive_iterable(data):
        return _numeric_from_iterable(cast(Iterable[object], data))
    return None


def _numeric_from_string(data: str) -> float | None:
    stripped = data.strip()
    if not stripped:
        return None
    try:
        return float(stripped)
    except ValueError:
        return _numeric_prefix(stripped)


def _numeric_prefix(value: str) -> float | None:
    match = re.match(r"^-?\d+(?:\.\d+)?", value)
    if match is None:
        return None
    return float(match.group(0))


def _numeric_from_mapping(data: RawDict) -> float | None:
    direct = _numeric_from_keys(data, _NUMERIC_KEYS)
    if direct is not None:
        return direct
    return _numeric_from_keys(data, _NUMERIC_CONTAINER_KEYS)


def _numeric_from_keys(data: RawDict, keys: tuple[str, ...]) -> float | None:
    for key in keys:
        if key in data:
            value = numeric_value(data.get(key))
            if value is not None:
                return value
    return None


def _is_recursive_iterable(data: object) -> bool:
    return isinstance(data, Iterable) and not isinstance(data, (str, bytes, bytearray))


def _numeric_from_iterable(data: Iterable[object]) -> float | None:
    for item in data:
        value = numeric_value(item)
        if value is not None:
            return value
    return None


def extract_unit(source: object) -> str | None:
    """Extract an explicit or inferred environmental unit recursively."""

    mapping = as_raw_dict(source)
    if mapping is not None:
        return _unit_from_mapping(mapping)
    if isinstance(source, str):
        return _unit_from_string(source)
    return None


def _unit_from_mapping(source: RawDict) -> str | None:
    explicit = _explicit_unit(source)
    if explicit is not None:
        return explicit
    for key in _UNIT_CONTAINER_KEYS:
        unit = extract_unit(source.get(key))
        if unit:
            return unit
    return None


def _explicit_unit(source: RawDict) -> str | None:
    for key in _UNIT_KEYS:
        unit = source.get(key)
        if isinstance(unit, str):
            stripped = unit.strip()
            if stripped:
                return stripped
    return None


def _unit_from_string(source: str) -> str | None:
    stripped = source.strip().lower()
    if not stripped:
        return None
    if "degf" in stripped or "fahrenheit" in stripped or stripped.endswith("f"):
        return "degF"
    if "degc" in stripped or "celsius" in stripped or stripped.endswith("c"):
        return "degC"
    if "%" in stripped or "percent" in stripped or "pct" in stripped:
        return "%"
    if "ratio" in stripped or "fraction" in stripped:
        return "ratio"
    return None


def extract_measure(raw: object) -> tuple[float | None, str | None]:
    """Return the legacy numeric and unit pair for an environmental value."""

    if raw is None:
        return None, None
    unit = extract_unit(raw)
    value = numeric_value(raw)
    return value, unit


def normalise_temperature(value: float | None, unit: str | None) -> float | None:
    """Convert explicit Fahrenheit values to degrees Celsius."""

    if value is None:
        return None
    unit_normalised = (unit or "").strip().lower()
    if unit_normalised in {"degf", "fahrenheit", "f"}:
        return (value - 32.0) * (5.0 / 9.0)
    return value


def normalise_humidity(value: float | None, unit: str | None) -> float | None:
    """Convert ratio humidity to percent while retaining legacy inference."""

    if value is None:
        return None
    unit_normalised = (unit or "").strip().lower()
    if unit_normalised in {"fraction", "ratio"}:
        value *= 100.0
    elif unit_normalised not in {"percent", "pct", "%"} and value <= 1.0:
        value *= 100.0
    return value


def normalise_heart_rate(
    minimum_raw: object,
    average_raw: object,
    maximum_raw: object,
) -> HeartRateValues | None:
    """Extract, round, and clamp a heart-rate triple."""

    minimum_value = numeric_value(minimum_raw)
    average_value = numeric_value(average_raw)
    maximum_value = numeric_value(maximum_raw)
    if minimum_value is None or average_value is None or maximum_value is None:
        return None
    minimum = int(round(minimum_value))
    maximum = int(round(maximum_value))
    average = max(minimum, min(average_value, maximum))
    return HeartRateValues(minimum, average, maximum)


def normalise_workout_environment(workout: RawDict) -> WorkoutEnvironment:
    """Recognise environmental layouts and apply canonical conversion rules."""

    temperature = _top_level_measure(workout, "temp", ("attempt", "timestamp"))
    humidity = _top_level_measure(workout, "humid")
    if temperature is None:
        temperature = _nested_measure(workout, "temperature")
    if humidity is None:
        humidity = _nested_measure(workout, "humidity")
    temperature, humidity = _metadata_measures(workout, temperature, humidity)
    return WorkoutEnvironment(
        temperature_degc=_canonical_temperature(temperature),
        humidity_percent=_canonical_humidity(humidity),
    )


def _top_level_measure(
    workout: RawDict,
    fragment: str,
    excluded_fragments: tuple[str, ...] = (),
) -> Measure | None:
    for key, raw in workout.items():
        key_lower = str(key).lower()
        if fragment not in key_lower or _contains_any(key_lower, excluded_fragments):
            continue
        measure = _measure(raw)
        if measure is not None:
            return measure
    return None


def _contains_any(value: str, fragments: tuple[str, ...]) -> bool:
    return any(fragment in value for fragment in fragments)


def _nested_measure(workout: RawDict, measure_key: str) -> Measure | None:
    for container_key in ("environment", "weather"):
        container = as_raw_dict(workout.get(container_key))
        if container is None or measure_key not in container:
            continue
        measure = _measure(container.get(measure_key))
        if measure is not None:
            return measure
    return None


def _measure(raw: object) -> Measure | None:
    value, unit = extract_measure(raw)
    if value is None:
        return None
    return Measure(value, unit)


def _metadata_measures(
    workout: RawDict,
    temperature: Measure | None,
    humidity: Measure | None,
) -> tuple[Measure | None, Measure | None]:
    entries = as_raw_list(workout.get("metadataEntries"))
    if entries is None:
        return temperature, humidity
    for raw_entry in entries:
        entry = as_raw_dict(raw_entry)
        if entry is not None:
            temperature, humidity = _apply_metadata_entry(entry, temperature, humidity)
    return temperature, humidity


def _apply_metadata_entry(
    entry: RawDict,
    temperature: Measure | None,
    humidity: Measure | None,
) -> tuple[Measure | None, Measure | None]:
    key = str(entry.get("key") or entry.get("name") or "").lower()
    if not key:
        return temperature, humidity
    raw_value = _metadata_value(entry)
    if raw_value is None:
        return temperature, humidity
    if temperature is None and "temp" in key:
        temperature = _metadata_measure(raw_value, entry)
    elif humidity is None and "humid" in key:
        humidity = _metadata_measure(raw_value, entry)
    return temperature, humidity


def _metadata_value(entry: RawDict) -> object:
    raw_value = entry.get("value")
    if raw_value is not None:
        return raw_value
    for candidate in _METADATA_VALUE_KEYS:
        if entry.get(candidate) is not None:
            return entry.get(candidate)
    return None


def _metadata_measure(raw_value: object, entry: RawDict) -> Measure | None:
    measure = _measure(raw_value)
    if measure is None:
        return None
    return Measure(measure.value, measure.unit or extract_unit(entry))


def _canonical_temperature(measure: Measure | None) -> float | None:
    if measure is None:
        return None
    value = normalise_temperature(measure.value, measure.unit)
    assert value is not None
    return round(value, 1)


def _canonical_humidity(measure: Measure | None) -> float | None:
    if measure is None:
        return None
    value = normalise_humidity(measure.value, measure.unit)
    assert value is not None
    return round(max(0.0, min(100.0, value)), 1)
