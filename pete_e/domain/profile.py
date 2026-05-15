"""Coached-person profile primitives.

Profiles describe the athlete/person whose data and plans are being managed.
They are intentionally separate from browser auth users, which only describe
who can access the operator UI.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime
import re
from typing import Any

DEFAULT_PROFILE_SLUG = "default"
DEFAULT_PROFILE_NAME = "Default profile"
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


@dataclass(frozen=True, slots=True)
class UserProfile:
    id: int | None
    slug: str
    display_name: str
    date_of_birth: date | None = None
    height_cm: int | None = None
    goal_weight_kg: float | None = None
    timezone: str = "Europe/London"
    is_default: bool = False
    is_active: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def as_public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "slug": self.slug,
            "display_name": self.display_name,
            "date_of_birth": self.date_of_birth.isoformat() if self.date_of_birth else None,
            "height_cm": self.height_cm,
            "goal_weight_kg": self.goal_weight_kg,
            "timezone": self.timezone,
            "is_default": self.is_default,
            "is_active": self.is_active,
        }


def normalize_profile_slug(value: str | None) -> str:
    slug = str(value or "").strip().lower()
    if not slug:
        return DEFAULT_PROFILE_SLUG
    return slug


def validate_profile_slug(value: str | None) -> str:
    slug = normalize_profile_slug(value)
    if not _SLUG_RE.match(slug):
        raise ValueError("profile slug must use lowercase letters, numbers, hyphens, or underscores")
    return slug


def profile_from_settings(settings: Any) -> UserProfile:
    slug = validate_profile_slug(getattr(settings, "PETEEEBOT_DEFAULT_PROFILE_SLUG", DEFAULT_PROFILE_SLUG))
    display_name = str(
        getattr(settings, "PETEEEBOT_DEFAULT_PROFILE_NAME", None)
        or DEFAULT_PROFILE_NAME
    ).strip()
    return UserProfile(
        id=None,
        slug=slug,
        display_name=display_name or DEFAULT_PROFILE_NAME,
        date_of_birth=getattr(settings, "USER_DATE_OF_BIRTH", None),
        height_cm=getattr(settings, "USER_HEIGHT_CM", None),
        goal_weight_kg=getattr(settings, "USER_GOAL_WEIGHT_KG", None),
        timezone=str(getattr(settings, "USER_TIMEZONE", "Europe/London") or "Europe/London"),
        is_default=True,
        is_active=True,
    )


def merge_profile_with_fallback(profile: UserProfile, fallback: UserProfile) -> UserProfile:
    return replace(
        profile,
        date_of_birth=profile.date_of_birth or fallback.date_of_birth,
        height_cm=profile.height_cm if profile.height_cm is not None else fallback.height_cm,
        goal_weight_kg=(
            profile.goal_weight_kg
            if profile.goal_weight_kg is not None
            else fallback.goal_weight_kg
        ),
        timezone=profile.timezone or fallback.timezone,
    )
