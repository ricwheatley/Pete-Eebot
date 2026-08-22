from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from pete_e import api
from pete_e.api_routes import auth, dependencies, metrics
from pete_e.application.api_services import MetricsService
from pete_e.application.exceptions import NotFoundError
from pete_e.application.profile_service import ProfileService
from pete_e.application.user_service import UserService
from pete_e.domain.auth import AuthenticatedPrincipal, AuthUser, ROLE_READ_ONLY, StoredUser, UserSession
from pete_e.domain.profile import UserProfile


pytestmark = pytest.mark.contract


class _SessionRepository:
    """In-memory application port used with the real UserService and password/session code."""

    def __init__(self) -> None:
        self.users: dict[int, StoredUser] = {}
        self.logins: dict[str, StoredUser] = {}
        self.sessions: dict[str, UserSession] = {}
        self._next_user_id = 1
        self._next_session_id = 1

    def create_user(
        self,
        *,
        username,
        username_normalized,
        email,
        email_normalized,
        display_name,
        password_hash,
        roles,
    ):
        user = AuthUser(
            id=self._next_user_id,
            username=username,
            email=email,
            display_name=display_name,
            roles=roles,
            is_active=True,
        )
        self._next_user_id += 1
        stored = StoredUser(user=user, password_hash=password_hash)
        self.users[user.id] = stored
        self.logins[username_normalized] = stored
        if email_normalized:
            self.logins[email_normalized] = stored
        return user

    def get_user_by_login(self, login_normalized):
        return self.logins.get(login_normalized)

    def record_successful_login(self, user_id, when):
        return None

    def create_session(self, *, user_id, token_hash, expires_at, ip_address=None, user_agent=None):
        session = UserSession(
            id=self._next_session_id,
            user_id=user_id,
            created_at=datetime.now(timezone.utc),
            expires_at=expires_at,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        self._next_session_id += 1
        self.sessions[token_hash] = session
        return session

    def get_user_for_active_session(self, token_hash, now):
        session = self.sessions.get(token_hash)
        if session is None or session.revoked_at is not None or session.expires_at <= now:
            return None
        stored = self.users.get(session.user_id)
        return stored.user if stored and stored.user.is_active else None

    def touch_session(self, token_hash, when):
        return None


class _ProfileRepository:
    def __init__(self, profiles: list[UserProfile], assignments: dict[int, list[str]]) -> None:
        self.profiles = {profile.slug: profile for profile in profiles}
        self.assignments = assignments

    def get_default_profile(self):
        return next((profile for profile in self.profiles.values() if profile.is_default), None)

    def get_profile_by_slug(self, slug):
        return self.profiles.get(slug)

    def get_default_profile_for_user(self, user_id):
        assigned = self.list_profiles_for_user(user_id)
        return next((profile for profile in assigned if profile.is_default), assigned[0] if assigned else None)

    def get_profile_by_slug_for_user(self, user_id, slug):
        if slug not in self.assignments.get(user_id, []):
            return None
        return self.profiles.get(slug)

    def list_profiles_for_user(self, user_id):
        return [self.profiles[slug] for slug in self.assignments.get(user_id, [])]

    def list_profiles(self):
        return list(self.profiles.values())


class _MetricsDal:
    def get_historical_data(self, start_date, end_date):
        return []

    def get_recent_running_workouts(self, *, days, end_date):
        return []

    def get_recent_strength_workouts(self, *, days, end_date):
        return []

    def get_nutrition_daily_summaries(self, start_date, end_date):
        return []

    def get_active_plan(self):
        return None

    def get_latest_training_maxes(self):
        return {}

    def get_latest_training_max_date(self):
        return None


@dataclass
class _ContractContext:
    alice_client: TestClient
    bob_client: TestClient
    machine_client: TestClient
    alice: AuthUser
    bob: AuthUser
    metrics_service: MetricsService


@pytest.fixture()
def contract_context(monkeypatch: pytest.MonkeyPatch):
    user_service = UserService(_SessionRepository())
    alice = user_service.create_user(username="alice", password="alice-pass", roles=(ROLE_READ_ONLY,))
    bob = user_service.create_user(username="bob", password="bob-password", roles=(ROLE_READ_ONLY,))
    profile_repository = _ProfileRepository(
        profiles=[
            UserProfile(
                id=10,
                slug="alice-profile",
                display_name="Alice Athlete",
                height_cm=165,
                goal_weight_kg=60,
                timezone="Europe/London",
                is_default=True,
            ),
            UserProfile(
                id=20,
                slug="bob-profile",
                display_name="Bob Athlete",
                height_cm=190,
                goal_weight_kg=95,
                timezone="Europe/London",
            ),
        ],
        assignments={alice.id: ["alice-profile"], bob.id: ["bob-profile"]},
    )
    metrics_service = MetricsService(_MetricsDal(), profile_service=ProfileService(profile_repository))

    monkeypatch.setattr(dependencies, "get_user_service", lambda: user_service)
    monkeypatch.setattr(auth, "get_user_service", lambda: user_service)
    monkeypatch.setattr(metrics, "get_metrics_service", lambda: metrics_service)
    monkeypatch.setattr(dependencies.settings, "PETEEEBOT_API_KEY", "profile-contract-key", raising=False)
    monkeypatch.setattr(
        "pete_e.application.api_services.alerts.emit_stale_ingest_if_needed",
        lambda **_kwargs: False,
    )

    with TestClient(api.app) as alice_client, TestClient(api.app) as bob_client, TestClient(api.app) as machine_client:
        alice_login = alice_client.post(
            "/api/v1/auth/login",
            json={"login": "alice", "password": "alice-pass"},
        )
        bob_login = bob_client.post(
            "/api/v1/auth/login",
            json={"login": "bob", "password": "bob-password"},
        )
        assert alice_login.status_code == 200
        assert bob_login.status_code == 200
        yield _ContractContext(
            alice_client=alice_client,
            bob_client=bob_client,
            machine_client=machine_client,
            alice=alice,
            bob=bob,
            metrics_service=metrics_service,
        )


def _error_contract(response) -> tuple[int, str, str]:
    error = response.json()["error"]
    return response.status_code, error["code"], error["message"]


def test_real_sessions_scope_coach_and_goal_metadata_without_enumeration(contract_context) -> None:
    ctx = contract_context

    own_coach = ctx.alice_client.get(
        "/api/v1/coach_state",
        params={"date": "2026-08-22", "profile": "alice-profile"},
    )
    denied_coach = ctx.alice_client.get(
        "/api/v1/coach_state",
        params={"date": "2026-08-22", "profile": "bob-profile"},
    )
    denied_goal = ctx.alice_client.get(
        "/api/v1/goal_state",
        params={"profile": "bob-profile"},
    )
    missing_goal = ctx.alice_client.get(
        "/api/v1/goal_state",
        params={"profile": "missing-profile"},
    )
    bob_default = ctx.bob_client.get(
        "/api/v1/goal_state",
    )

    assert own_coach.status_code == 200
    assert own_coach.json()["profile"]["slug"] == "alice-profile"
    assert bob_default.status_code == 200
    assert bob_default.json()["profile"]["slug"] == "bob-profile"
    assert _error_contract(denied_coach) == (404, "profile_not_found", "Profile not found.")
    assert _error_contract(denied_goal) == _error_contract(missing_goal)
    for denied in (denied_coach, denied_goal):
        assert set(denied.json()) == {"error"}
        assert set(denied.json()["error"]) == {"code", "message", "correlation_id"}


def test_machine_api_key_has_explicit_global_profile_read_scope(contract_context) -> None:
    ctx = contract_context
    headers = {"X-API-Key": "profile-contract-key"}

    bob_goal = ctx.machine_client.get(
        "/api/v1/goal_state",
        params={"profile": "bob-profile"},
        headers=headers,
    )
    default_goal = ctx.machine_client.get("/api/v1/goal_state", headers=headers)

    assert bob_goal.status_code == 200
    assert bob_goal.json()["profile"]["slug"] == "bob-profile"
    assert default_goal.status_code == 200
    assert default_goal.json()["profile"]["slug"] == "alice-profile"


def test_direct_metrics_service_calls_require_and_enforce_the_principal(contract_context) -> None:
    ctx = contract_context
    alice_principal = AuthenticatedPrincipal.for_user(ctx.alice)

    own_goal = ctx.metrics_service.goal_state(principal=alice_principal, profile_slug="alice-profile")

    assert own_goal["profile"]["slug"] == "alice-profile"
    with pytest.raises(NotFoundError):
        ctx.metrics_service.coach_state(
            "2026-08-22",
            principal=alice_principal,
            profile_slug="bob-profile",
        )
    with pytest.raises(NotFoundError):
        ctx.metrics_service.goal_state(principal=alice_principal, profile_slug="bob-profile")
    with pytest.raises(TypeError):
        ctx.metrics_service.goal_state(profile_slug="alice-profile")  # type: ignore[call-arg]


def test_denied_profile_audit_does_not_claim_a_resolved_private_profile(
    contract_context,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events = []
    monkeypatch.setattr(
        "pete_e.application.profile_service.log_utils.log_event",
        lambda **fields: events.append(fields),
    )

    response = contract_context.alice_client.get(
        "/api/v1/goal_state",
        params={"profile": "bob-profile"},
    )

    denied = [event for event in events if event.get("event") == "profile_authorization"][-1]
    assert response.status_code == 404
    assert denied["actor_id"] == f"user:{contract_context.alice.id}"
    assert denied["requested_profile_slug"] == "bob-profile"
    assert denied["outcome"] == "denied"
    assert "profile_id" not in denied
