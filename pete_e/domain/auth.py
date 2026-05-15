"""Authentication and authorization domain primitives."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Literal

RoleName = Literal["owner", "operator", "read_only"]

ROLE_OWNER: RoleName = "owner"
ROLE_OPERATOR: RoleName = "operator"
ROLE_READ_ONLY: RoleName = "read_only"
VALID_ROLES: tuple[RoleName, ...] = (ROLE_OWNER, ROLE_OPERATOR, ROLE_READ_ONLY)


def normalize_role(role: str) -> RoleName:
    candidate = str(role or "").strip().lower()
    if candidate not in VALID_ROLES:
        raise ValueError(f"Unknown role: {role!r}")
    return candidate  # type: ignore[return-value]


def normalize_roles(roles: Iterable[str] | None) -> tuple[RoleName, ...]:
    normalized = tuple(dict.fromkeys(normalize_role(role) for role in (roles or (ROLE_READ_ONLY,))))
    return normalized or (ROLE_READ_ONLY,)


@dataclass(frozen=True, slots=True)
class AuthUser:
    id: int
    username: str
    email: str | None
    display_name: str | None
    roles: tuple[RoleName, ...]
    is_active: bool
    created_at: datetime | None = None
    updated_at: datetime | None = None
    last_login_at: datetime | None = None

    def has_role(self, role: RoleName | str) -> bool:
        return normalize_role(str(role)) in self.roles

    @property
    def is_owner(self) -> bool:
        return ROLE_OWNER in self.roles

    @property
    def can_operate(self) -> bool:
        return bool({ROLE_OWNER, ROLE_OPERATOR}.intersection(self.roles))


@dataclass(frozen=True, slots=True)
class StoredUser:
    user: AuthUser
    password_hash: str


@dataclass(frozen=True, slots=True)
class UserSession:
    id: int
    user_id: int
    created_at: datetime
    expires_at: datetime
    last_seen_at: datetime | None = None
    revoked_at: datetime | None = None
    ip_address: str | None = None
    user_agent: str | None = None


@dataclass(frozen=True, slots=True)
class CreatedSession:
    session: UserSession
    token: str
