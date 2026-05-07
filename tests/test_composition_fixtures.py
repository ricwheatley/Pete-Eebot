from __future__ import annotations

from dataclasses import dataclass

from pete_e.application.collaborator_contracts import ValidationContract
from pete_e.application.orchestrator import Orchestrator
from tests.di_utils import _NoopDailySyncService
from pete_e.infrastructure.postgres_dal import PostgresDal

from tests.di_utils import build_contract_container


@dataclass
class _ValidationStub(ValidationContract):
    calls: int = 0

    def validate(self, reference_date):
        self.calls += 1
        return None


class _DalStub:
    def get_active_plan(self):
        return None


def test_contract_fixture_can_swap_validation_dependency():
    validation = _ValidationStub()
    container = build_contract_container(
        dal=_DalStub(),
        validation_service=validation,
    )

    orchestrator = Orchestrator(container=container, daily_sync_service=_NoopDailySyncService())

    assert orchestrator.validation_service is validation
    assert isinstance(container.resolve(PostgresDal), _DalStub)
