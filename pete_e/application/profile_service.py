"""Application service for optional coached-person profiles."""

from __future__ import annotations

from datetime import date
from typing import Protocol

from pete_e.application.exceptions import BadRequestError, ConflictError, ForbiddenError, NotFoundError
from pete_e.domain.auth import AuthenticatedPrincipal
from pete_e.domain.profile import (
    UserProfile,
    merge_profile_with_fallback,
    profile_from_settings,
    validate_profile_slug,
)
from pete_e.infrastructure import log_utils


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

    def get_default_profile_for_user(self, user_id: int) -> UserProfile | None:
        ...

    def get_profile_by_slug_for_user(self, user_id: int, slug: str) -> UserProfile | None:
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
        principal: AuthenticatedPrincipal,
    ) -> UserProfile:
        fallback = self.settings_profile
        slug = validate_profile_slug(profile_slug) if profile_slug else None

        if self.repository is None:
            if not principal.can_read_all_profiles:
                self._audit_profile_access(principal, slug, outcome="denied")
                raise self._profile_not_found()
            if slug and slug != fallback.slug:
                self._audit_profile_access(principal, slug, outcome="denied")
                raise self._profile_not_found()
            self._audit_profile_access(principal, slug, outcome="authorized", profile=fallback)
            return fallback

        if principal.can_read_all_profiles:
            profile = self.repository.get_profile_by_slug(slug) if slug else self.repository.get_default_profile()
        elif principal.user is not None:
            profile = (
                self.repository.get_profile_by_slug_for_user(principal.user.id, slug)
                if slug
                else self.repository.get_default_profile_for_user(principal.user.id)
            )
        else:
            profile = None

        if profile is None:
            if principal.can_read_all_profiles and (slug is None or slug == fallback.slug):
                self._audit_profile_access(principal, slug, outcome="authorized", profile=fallback)
                return fallback
            self._audit_profile_access(principal, slug, outcome="denied")
            raise self._profile_not_found()

        resolved = merge_profile_with_fallback(profile, fallback)
        self._audit_profile_access(principal, slug, outcome="authorized", profile=resolved)
        return resolved

    def list_profiles(self, *, principal: AuthenticatedPrincipal) -> list[UserProfile]:
        fallback = self.settings_profile
        if self.repository is None:
            return [fallback] if principal.can_read_all_profiles else []
        if principal.can_read_all_profiles:
            profiles = self.repository.list_profiles()
        elif principal.user is not None:
            profiles = self.repository.list_profiles_for_user(principal.user.id)
        else:
            profiles = []
        if not profiles:
            return [fallback] if principal.can_read_all_profiles else []
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
        principal: AuthenticatedPrincipal,
    ) -> UserProfile:
        if not principal.can_manage_profiles:
            raise ForbiddenError("Profile management requires owner access.", code="profile_management_forbidden")
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

    @staticmethod
    def _profile_not_found() -> NotFoundError:
        return NotFoundError("Profile not found.", code="profile_not_found")

    @staticmethod
    def _audit_profile_access(
        principal: AuthenticatedPrincipal,
        requested_slug: str | None,
        *,
        outcome: str,
        profile: UserProfile | None = None,
    ) -> None:
        fields = {
            **principal.audit_fields(),
            "outcome": outcome,
            "requested_profile_slug": requested_slug or "<default>",
        }
        if profile is not None:
            fields.update({"profile_id": profile.id, "profile_slug": profile.slug})
        log_utils.log_event(
            event="profile_authorization",
            message=f"profile access {outcome}",
            tag="AUDIT",
            level="INFO" if outcome == "authorized" else "WARNING",
            **fields,
        )
