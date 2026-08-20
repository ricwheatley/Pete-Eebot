from __future__ import annotations

import pytest

from pete_e.application.exceptions import ValidationError
from pete_e.application.plan_duration import (
    DEFAULT_PLAN_WEEKS,
    SUPPORTED_PLAN_WEEKS,
    validate_plan_weeks,
)


def test_standard_plan_duration_contract_is_fixed_at_four_weeks() -> None:
    assert DEFAULT_PLAN_WEEKS == 4
    assert SUPPORTED_PLAN_WEEKS == (4,)
    assert validate_plan_weeks(DEFAULT_PLAN_WEEKS) == 4


@pytest.mark.parametrize("weeks", [1, 3, 4.0, 5, 12, True])
def test_standard_plan_duration_rejects_unsupported_values(weeks: int) -> None:
    with pytest.raises(ValidationError) as exc_info:
        validate_plan_weeks(weeks)

    assert exc_info.value.code == "unsupported_plan_duration"
    assert exc_info.value.http_status == 400
    assert "Only 4-week plan generation" in exc_info.value.message
