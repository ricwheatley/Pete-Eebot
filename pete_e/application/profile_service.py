"""Application service for optional coached-person profiles."""

from __future__ import annotations

from datetime import date
from typing import Protocol

from pete_e.application.exceptions import BadRequestError, ConflictError, NotFoundError
from pete_e.domain.auth import AuthUser
from pete_e.domain.profile import (
    UserProfile,
    merge_profile_with_fallback,
    profile_from_settings,
    validate_profile_slug,
)


class ProfileRepository(Protocol):
    def create_profile(
        self,
        *,
        slug: str,
        display_name: str,
        date_of_birth: date | None,
        height_cm: int | None,
        goal_weight_kg: float | None,
        timezone: str,
        is_default: bool,
        owner_user_id: int | None = None,
    ) -> UserProfile:
        ...

    def get_default_profile(self) -> UserProfile | None:
        ...

    def get_profile_by_slug(self, slug: str) -> UserProfile | None:
        ...

    def list_profiles_for_user(self, user_id: int) -> list[UserProfile]:
        ...

    def list_profiles(self) -> list[UserProfile]:
        ...


class ProfileService:
    def __init__(self, repository: ProfileRepository | None = None) -> None:
        self.repository = repository

    @property
    def settings_profile(self) -> UserProfile:
        from pete_e.config import settings

        return profile_from_settings(settings)

    def resolve_profile(
        self,
        profile_slug: str | None = None,
        *,
        user: AuthUser | None = None,
    ) -> UserProfile:
        fallback = self.settings_profile
        slug = validate_profile_slug(profile_slug) if profile_slug else None

        if self.repository is None:
            if slug and slug != fallback.slug:
                raise NotFoundError("Profile not found.", code="profile_not_found")
            return fallback

        profile = self.repository.get_profile_by_slug(slug) if slug else self.repository.get_default_profile()
        if profile is None:
            if slug and slug != fallback.slug:
                raise NotFoundError("Profile not found.", code="profile_not_found")
            return fallback

        if user is not None and not user.is_owner:
            allowed = {item.slug for item in self.repository.list_profiles_for_user(user.id)}
            if allowed and profile.slug not in allowed:
                raise NotFoundError("Profile not found.", code="profile_not_found")

        return merge_profile_with_fallback(profile, fallback)

    def list_profiles(self, *, user: AuthUser | None = None) -> list[UserProfile]:
        fallback = self.settings_profile
        if self.repository is None:
            return [fallback]
        profiles = (
            self.repository.list_profiles_for_user(user.id)
            if user is not None and not user.is_owner
            else self.repository.list_profiles()
        )
        if not profiles:
            return [fallback]
        return [merge_profile_with_fallback(profile, fallback) for profile in profiles]

    def create_profile(
        self,
        *,
        slug: str,
        display_name: str,
        date_of_birth: date | None = None,
        height_cm: int | None = None,
        goal_weight_kg: float | None = None,
        timezone: str | None = None,
        is_default: bool = False,
        owner_user_id: int | None = None,
    ) -> UserProfile:
        if self.repository is None:
            raise ConflictError("Profile repository is not configured.", code="profile_repository_missing")

        normalized_slug = validate_profile_slug(slug)
        name = str(display_name or "").strip()
        if not name:
            raise BadRequestError("display_name is required", code="profile_display_name_required")
        if height_cm is not None and height_cm <= 0:
            raise BadRequestError("height_cm must be positive", code="invalid_profile_height")
        if goal_weight_kg is not None and goal_weight_kg <= 0:
            raise BadRequestError("goal_weight_kg must be positive", code="invalid_profile_goal_weight")

        if self.repository.get_profile_by_slug(normalized_slug) is not None:
            raise ConflictError("profile slug already exists", code="profile_already_exists")

        return self.repository.create_profile(
            slug=normalized_slug,
            display_name=name,
            date_of_birth=date_of_birth,
            height_cm=height_cm,
            goal_weight_kg=goal_weight_kg,
            timezone=str(timezone or self.settings_profile.timezone),
            is_default=is_default,
            owner_user_id=owner_user_id,
        )
