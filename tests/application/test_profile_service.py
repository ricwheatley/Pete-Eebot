from __future__ import annotations

from datetime import date

import pytest

from pete_e.application.exceptions import ConflictError, NotFoundError
from pete_e.application.profile_service import ProfileService
from pete_e.config import settings
from pete_e.domain.auth import AuthUser, ROLE_READ_ONLY
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

    def list_profiles_for_user(self, user_id):
        return [self.profiles[slug] for slug in self.user_profiles.get(user_id, [])]

    def list_profiles(self):
        return list(self.profiles.values())


def _user(user_id: int = 7) -> AuthUser:
    return AuthUser(
        id=user_id,
        username="reader",
        email=None,
        display_name=None,
        roles=(ROLE_READ_ONLY,),
        is_active=True,
    )


def test_resolve_profile_without_repository_preserves_settings_backed_default() -> None:
    profile = ProfileService().resolve_profile()

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

    profile = ProfileService(repo).resolve_profile()

    assert profile.display_name == "Pete"
    assert profile.date_of_birth == date(1990, 1, 1)
    assert profile.goal_weight_kg == settings.USER_GOAL_WEIGHT_KG


def test_unknown_non_default_profile_raises_not_found() -> None:
    with pytest.raises(NotFoundError):
        ProfileService().resolve_profile("other")


def test_read_only_user_cannot_resolve_unassigned_profile_when_assignments_exist() -> None:
    repo = ProfileRepo()
    repo.profiles["default"] = UserProfile(id=1, slug="default", display_name="Default", is_default=True)
    repo.profiles["family"] = UserProfile(id=2, slug="family", display_name="Family")
    repo.user_profiles[7] = ["default"]

    with pytest.raises(NotFoundError):
        ProfileService(repo).resolve_profile("family", user=_user())


def test_create_profile_normalizes_slug_and_assigns_owner() -> None:
    repo = ProfileRepo()
    service = ProfileService(repo)

    profile = service.create_profile(
        slug=" Athlete_2 ",
        display_name="Athlete 2",
        height_cm=180,
        goal_weight_kg=82,
        owner_user_id=7,
    )

    assert profile.slug == "athlete_2"
    assert repo.user_profiles[7] == ["athlete_2"]


def test_create_profile_rejects_duplicate_slug() -> None:
    repo = ProfileRepo()
    repo.profiles["default"] = UserProfile(id=1, slug="default", display_name="Default")

    with pytest.raises(ConflictError):
        ProfileService(repo).create_profile(slug="default", display_name="Default")
