from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from pete_e.application.orchestrator import CycleRolloverResult, WeeklyAutomationResult, WeeklyCalibrationResult, Orchestrator


def test_dataclasses_capture_expected_fields():
    calibration = WeeklyCalibrationResult(message="ok", validation=None)
    rollover = CycleRolloverResult(plan_id=17, created=True, exported=True, message="done")
    result = WeeklyAutomationResult(calibration=calibration, rollover=rollover, rollover_triggered=True)

    assert result.calibration.message == "ok"
    assert result.rollover.plan_id == 17
    assert result.rollover_triggered is True


def test_close_invokes_dal_close():
    calls = []

    class Closer:
        def close(self):
            calls.append("closed")

    orch = Orchestrator(
        dal=Closer(),
        wger_client=SimpleNamespace(),
        plan_service=SimpleNamespace(),
        export_service=SimpleNamespace(),
    )

    orch.close()

    assert calls == ["closed"]
