from __future__ import annotations

import pytest
import tenacity

from pete_e.application import sync


pytestmark = pytest.mark.contract


def test_sync_retry_uses_real_tenacity_without_waiting(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts = iter(
        [
            (False, ["Withings"], {"Withings": "failed"}, []),
            (False, ["Withings"], {"Withings": "failed"}, []),
            (True, [], {"Withings": "ok"}, []),
        ]
    )
    retry_events: list[dict[str, str]] = []
    monkeypatch.setattr(
        sync.observability,
        "record_job_retry",
        lambda **values: retry_events.append(values),
    )
    monkeypatch.setattr(sync.log_utils, "log_message", lambda *_args, **_kwargs: None)

    result = sync._run_with_retry(
        execute=lambda: next(attempts),
        max_attempts=3,
        base_delay=0,
        label="Sync",
        summary_name="daily",
    )

    assert sync.Retrying is tenacity.Retrying
    assert result.success is True
    assert result.attempts == 3
    assert result.source_statuses == {"Withings": "ok"}
    assert retry_events == [
        {"operation": "daily", "source": "Withings"},
        {"operation": "daily", "source": "Withings"},
    ]
