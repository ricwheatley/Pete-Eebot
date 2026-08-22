"""Authentication and authorization domain primitives."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Literal

RoleName = Literal["owner", "operator", "read_only"]
PrincipalKind = Literal["browser_user", "machine"]
AuthenticationScheme = Literal["session", "api_key", "cli", "system"]

ROLE_OWNER: RoleName = "owner"
ROLE_OPERATOR: RoleName = "operator"
ROLE_READ_ONLY: RoleName = "read_only"
VALID_ROLES: tuple[RoleName, ...] = (ROLE_OWNER, ROLE_OPERATOR, ROLE_READ_ONLY)
PROFILE_READ_ALL_SCOPE = "profiles:read:any"
PROFILE_MANAGE_ALL_SCOPE = "profiles:manage:any"


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
    mfa_enabled: bool = False

    def has_role(self, role: RoleName | str) -> bool:
        return normalize_role(str(role)) in self.roles

    @property
    def is_owner(self) -> bool:
        return ROLE_OWNER in self.roles

    @property
    def can_operate(self) -> bool:
        return bool({ROLE_OWNER, ROLE_OPERATOR}.intersection(self.roles))


@dataclass(frozen=True, slots=True)
class AuthenticatedPrincipal:
    """Explicit actor context passed across profile-sensitive boundaries."""

    kind: PrincipalKind
    auth_scheme: AuthenticationScheme
    user: AuthUser | None = None
    machine_client_id: str | None = None
    scopes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.kind not in {"browser_user", "machine"}:
            raise ValueError(f"Unknown principal kind: {self.kind!r}")
        if self.kind == "browser_user":
            if self.user is None or self.machine_client_id is not None:
                raise ValueError("A browser principal requires exactly one AuthUser")
            if self.auth_scheme != "session":
                raise ValueError("A browser principal must use session authentication")
            if not self.user.is_active:
                raise ValueError("A browser principal requires an active AuthUser")
            return

        if self.user is not None or not str(self.machine_client_id or "").strip():
            raise ValueError("A machine principal requires a machine_client_id and no AuthUser")
        if self.auth_scheme == "session":
            raise ValueError("A machine principal cannot use session authentication")

    @classmethod
    def for_user(cls, user: AuthUser) -> AuthenticatedPrincipal:
        return cls(kind="browser_user", auth_scheme="session", user=user)

    @classmethod
    def for_machine(
        cls,
        machine_client_id: str,
        *,
        auth_scheme: AuthenticationScheme,
        scopes: Iterable[str] = (),
    ) -> AuthenticatedPrincipal:
        return cls(
            kind="machine",
            auth_scheme=auth_scheme,
            machine_client_id=str(machine_client_id).strip(),
            scopes=tuple(dict.fromkeys(str(scope).strip() for scope in scopes if str(scope).strip())),
        )

    @property
    def is_owner(self) -> bool:
        return bool(self.user and self.user.is_owner)

    def has_scope(self, scope: str) -> bool:
        return str(scope) in self.scopes

    @property
    def can_read_all_profiles(self) -> bool:
        return self.is_owner or self.has_scope(PROFILE_READ_ALL_SCOPE)

    @property
    def can_manage_profiles(self) -> bool:
        return self.is_owner or self.has_scope(PROFILE_MANAGE_ALL_SCOPE)

    @property
    def actor_id(self) -> str:
        if self.user is not None:
            return f"user:{self.user.id}"
        return f"machine:{self.machine_client_id}"

    def audit_fields(self) -> dict[str, object]:
        fields: dict[str, object] = {
            "principal_kind": self.kind,
            "auth_scheme": self.auth_scheme,
            "actor_id": self.actor_id,
        }
        if self.user is not None:
            fields.update({"user_id": self.user.id, "roles": list(self.user.roles)})
        else:
            fields.update({"machine_client_id": self.machine_client_id, "scopes": list(self.scopes)})
        return fields


def trusted_profile_reader(
    machine_client_id: str,
    *,
    auth_scheme: AuthenticationScheme = "system",
) -> AuthenticatedPrincipal:
    """Build a named trusted local/machine actor with global profile-read scope."""

    return AuthenticatedPrincipal.for_machine(
        machine_client_id,
        auth_scheme=auth_scheme,
        scopes=(PROFILE_READ_ALL_SCOPE,),
    )


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
