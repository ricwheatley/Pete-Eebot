"""Unit tests for small utility helpers in :mod:`pete_e.utils`."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Iterable
import random

import pytest

from pete_e.utils import converters, formatters, helpers, math


def test_to_float_handles_various_inputs():
    class Convertible:
        def __float__(self):
            return 3.25

    assert converters.to_float(None) is None
    assert converters.to_float(2.5) == 2.5
    assert converters.to_float(5) == 5.0
    assert converters.to_float(Decimal("7.2")) == pytest.approx(7.2)
    assert converters.to_float("  8.5  ") == pytest.approx(8.5)
    assert converters.to_float(" ") is None
    assert converters.to_float("not-a-number") is None
    assert converters.to_float(Convertible()) == pytest.approx(3.25)


def test_to_date_accepts_common_representations():
    sample_date = date(2024, 5, 17)
    sample_datetime = datetime(2024, 5, 17, 8, 30)

    assert converters.to_date(sample_date) == sample_date
    assert converters.to_date(sample_datetime) == sample_date
    assert converters.to_date("2024-05-17") == sample_date
    assert converters.to_date(" 2024-05-17T10:00:00 ") == sample_date
    assert converters.to_date("not-a-date") is None
    assert converters.to_date(42) is None
    assert converters.to_date("") is None


def test_minutes_to_hours_normalises_to_float():
    assert converters.minutes_to_hours(120) == pytest.approx(2.0)
    assert converters.minutes_to_hours("90") == pytest.approx(1.5)
    assert converters.minutes_to_hours(None) is None
    assert converters.minutes_to_hours("not-minutes") is None


def test_ensure_sentence_appends_punctuation():
    assert formatters.ensure_sentence("Bonjour") == "Bonjour."
    assert formatters.ensure_sentence("Already done!") == "Already done!"
    assert formatters.ensure_sentence(" ") == ""


def test_choose_from_respects_defaults():
    rng = random.Random(1)
    # When options exist we expect a deterministic pick via the seeded RNG.
    assert helpers.choose_from(["one", "two", "three"], rand=rng) == "one"
    # Empty options fall back to the provided default.
    assert helpers.choose_from([], default="fallback", rand=rng) == "fallback"


@pytest.mark.parametrize(
    "values, expected",
    [
        ([1.0, 2.0, 3.0], 2.0),
        ([None, 2.0, None, 4.0], 3.0),
        ([None, None], None),
    ],
)
def test_average_skips_none(values: Iterable[float | None], expected: float | None):
    result = math.average(values)
    if expected is None:
        assert result is None
    else:
        assert result == pytest.approx(expected)


def test_mean_or_none_and_near_helpers():
    assert math.mean_or_none([]) is None
    assert math.mean_or_none([1, 2, 3]) == pytest.approx(2.0)
    assert math.near(1.000001, 1.000002, tolerance=1e-3)
    assert not math.near(None, 1.0)
    assert not math.near(1.0, 1.1, tolerance=1e-3)
