from __future__ import annotations

from datetime import date

import pytest

from pete_e.application.exceptions import ConflictError, ForbiddenError, NotFoundError
from pete_e.application.profile_service import ProfileService
from pete_e.config import settings
from pete_e.domain.auth import (
    AuthenticatedPrincipal,
    AuthUser,
    ROLE_OPERATOR,
    ROLE_OWNER,
    ROLE_READ_ONLY,
    trusted_profile_reader,
)
from pete_e.domain.profile import UserProfile


class ProfileRepo:
    def __init__(self) -> None:
        self.profiles: dict[str, UserProfile] = {}
        self.user_profiles: dict[int, list[str]] = {}
        self.created: list[UserProfile] = []

    def create_profile(
        self,
        *,
        slug,
        display_name,
        date_of_birth,
        height_cm,
        goal_weight_kg,
        timezone,
        is_default,
        owner_user_id=None,
    ):
        profile = UserProfile(
            id=len(self.profiles) + 1,
            slug=slug,
            display_name=display_name,
            date_of_birth=date_of_birth,
            height_cm=height_cm,
            goal_weight_kg=goal_weight_kg,
            timezone=timezone,
            is_default=is_default,
        )
        self.profiles[slug] = profile
        self.created.append(profile)
        if owner_user_id is not None:
            self.user_profiles.setdefault(owner_user_id, []).append(slug)
        return profile

    def get_default_profile(self):
        return next((profile for profile in self.profiles.values() if profile.is_default), None)

    def get_profile_by_slug(self, slug):
        return self.profiles.get(slug)

    def get_default_profile_for_user(self, user_id):
        assigned = self.list_profiles_for_user(user_id)
        return next((profile for profile in assigned if profile.is_default), assigned[0] if assigned else None)

    def get_profile_by_slug_for_user(self, user_id, slug):
        return next((profile for profile in self.list_profiles_for_user(user_id) if profile.slug == slug), None)

    def list_profiles_for_user(self, user_id):
        return [self.profiles[slug] for slug in self.user_profiles.get(user_id, [])]

    def list_profiles(self):
        return list(self.profiles.values())


def _user(user_id: int = 7, *, roles=(ROLE_READ_ONLY,)) -> AuthUser:
    return AuthUser(
        id=user_id,
        username="reader",
        email=None,
        display_name=None,
        roles=roles,
        is_active=True,
    )


def _principal(user_id: int = 7, *, roles=(ROLE_READ_ONLY,)) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal.for_user(_user(user_id, roles=roles))


def _machine() -> AuthenticatedPrincipal:
    return trusted_profile_reader("test-machine", auth_scheme="api_key")


def test_resolve_profile_without_repository_preserves_settings_backed_default() -> None:
    profile = ProfileService().resolve_profile(principal=_machine())

    assert profile.slug == "default"
    assert profile.date_of_birth == settings.USER_DATE_OF_BIRTH
    assert profile.height_cm == settings.USER_HEIGHT_CM
    assert profile.goal_weight_kg == settings.USER_GOAL_WEIGHT_KG
    assert profile.timezone == settings.USER_TIMEZONE


def test_repository_default_is_merged_with_settings_for_backward_compatibility() -> None:
    repo = ProfileRepo()
    repo.profiles["default"] = UserProfile(
        id=1,
        slug="default",
        display_name="Pete",
        timezone="Europe/London",
        is_default=True,
    )

    profile = ProfileService(repo).resolve_profile(principal=_machine())

    assert profile.display_name == "Pete"
    assert profile.date_of_birth == date(1990, 1, 1)
    assert profile.goal_weight_kg == settings.USER_GOAL_WEIGHT_KG


def test_unknown_non_default_profile_raises_not_found() -> None:
    with pytest.raises(NotFoundError):
        ProfileService().resolve_profile("other", principal=_machine())


def test_read_only_user_cannot_resolve_unassigned_profile_when_assignments_exist() -> None:
    repo = ProfileRepo()
    repo.profiles["default"] = UserProfile(id=1, slug="default", display_name="Default", is_default=True)
    repo.profiles["family"] = UserProfile(id=2, slug="family", display_name="Family")
    repo.user_profiles[7] = ["default"]

    with pytest.raises(NotFoundError):
        ProfileService(repo).resolve_profile("family", principal=_principal())


def test_non_owner_with_no_assignments_cannot_resolve_existing_profile() -> None:
    repo = ProfileRepo()
    repo.profiles["family"] = UserProfile(id=2, slug="family", display_name="Family")

    with pytest.raises(NotFoundError) as exc:
        ProfileService(repo).resolve_profile("family", principal=_principal())

    assert exc.value.code == "profile_not_found"


@pytest.mark.parametrize("roles", [(ROLE_READ_ONLY,), (ROLE_OPERATOR,)])
def test_assigned_non_owner_can_resolve_only_assigned_profile(roles) -> None:
    repo = ProfileRepo()
    repo.profiles["athlete"] = UserProfile(id=1, slug="athlete", display_name="Athlete")
    repo.profiles["family"] = UserProfile(id=2, slug="family", display_name="Family")
    repo.user_profiles[7] = ["athlete"]

    profile = ProfileService(repo).resolve_profile("athlete", principal=_principal(roles=roles))

    assert profile.slug == "athlete"


def test_owner_can_resolve_any_active_profile_without_assignment() -> None:
    repo = ProfileRepo()
    repo.profiles["family"] = UserProfile(id=2, slug="family", display_name="Family")

    profile = ProfileService(repo).resolve_profile(
        "family",
        principal=_principal(roles=(ROLE_OWNER,)),
    )

    assert profile.slug == "family"


def test_missing_and_unassigned_profiles_have_the_same_error_contract() -> None:
    repo = ProfileRepo()
    repo.profiles["private"] = UserProfile(id=2, slug="private", display_name="Private")

    errors = []
    for slug in ("private", "missing"):
        with pytest.raises(NotFoundError) as exc:
            ProfileService(repo).resolve_profile(slug, principal=_principal())
        errors.append((exc.value.http_status, exc.value.code, exc.value.message))

    assert errors == [(404, "profile_not_found", "Profile not found.")] * 2


def test_omitted_profile_selects_first_assigned_profile_for_non_owner() -> None:
    repo = ProfileRepo()
    repo.profiles["athlete"] = UserProfile(id=1, slug="athlete", display_name="Athlete")
    repo.user_profiles[7] = ["athlete"]

    profile = ProfileService(repo).resolve_profile(principal=_principal())

    assert profile.slug == "athlete"


def test_non_owner_without_repository_cannot_inherit_settings_profile() -> None:
    with pytest.raises(NotFoundError):
        ProfileService().resolve_profile(principal=_principal())


def test_machine_without_global_profile_scope_is_denied() -> None:
    principal = AuthenticatedPrincipal.for_machine(
        "limited-machine",
        auth_scheme="api_key",
    )

    with pytest.raises(NotFoundError):
        ProfileService().resolve_profile(principal=principal)


def test_profile_access_audit_uses_safe_actor_and_request_identifiers(monkeypatch) -> None:
    repo = ProfileRepo()
    repo.profiles["private"] = UserProfile(id=2, slug="private", display_name="Private")
    events = []
    monkeypatch.setattr(
        "pete_e.application.profile_service.log_utils.log_event",
        lambda **fields: events.append(fields),
    )

    with pytest.raises(NotFoundError):
        ProfileService(repo).resolve_profile("private", principal=_principal())

    event = events[-1]
    assert event["event"] == "profile_authorization"
    assert event["outcome"] == "denied"
    assert event["actor_id"] == "user:7"
    assert event["requested_profile_slug"] == "private"
    assert "profile_id" not in event


def test_create_profile_normalizes_slug_and_assigns_owner() -> None:
    repo = ProfileRepo()
    service = ProfileService(repo)

    profile = service.create_profile(
        slug=" Athlete_2 ",
        display_name="Athlete 2",
        height_cm=180,
        goal_weight_kg=82,
        owner_user_id=7,
        principal=_principal(roles=(ROLE_OWNER,)),
    )

    assert profile.slug == "athlete_2"
    assert repo.user_profiles[7] == ["athlete_2"]


def test_create_profile_rejects_duplicate_slug() -> None:
    repo = ProfileRepo()
    repo.profiles["default"] = UserProfile(id=1, slug="default", display_name="Default")

    with pytest.raises(ConflictError):
        ProfileService(repo).create_profile(
            slug="default",
            display_name="Default",
            principal=_principal(roles=(ROLE_OWNER,)),
        )


def test_non_owner_cannot_manage_profiles_through_direct_service_call() -> None:
    with pytest.raises(ForbiddenError) as exc:
        ProfileService(ProfileRepo()).create_profile(
            slug="athlete",
            display_name="Athlete",
            principal=_principal(),
        )

    assert exc.value.code == "profile_management_forbidden"
