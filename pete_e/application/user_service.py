"""Application service for browser user and session primitives."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from pete_e.application.exceptions import BadRequestError, ConflictError, NotFoundError
from pete_e.domain.auth import (
    AuthUser,
    CreatedSession,
    ROLE_OWNER,
    ROLE_OPERATOR,
    RoleName,
    StoredUser,
    UserSession,
    VALID_ROLES,
    normalize_roles,
)
from pete_e.infrastructure.passwords import (
    generate_session_token,
    generate_recovery_code,
    generate_totp_secret,
    hash_password,
    hash_session_token,
    recovery_code_hashes as build_recovery_code_hashes,
    verify_totp_code,
    verify_password,
)


class UserRepository(Protocol):
    def create_user(
        self,
        *,
        username: str,
        username_normalized: str,
        email: str | None,
        email_normalized: str | None,
        display_name: str | None,
        password_hash: str,
        roles: tuple[RoleName, ...],
    ) -> AuthUser:
        ...

    def get_user_by_login(self, login_normalized: str) -> StoredUser | None:
        ...

    def get_user_by_id(self, user_id: int) -> AuthUser | None:
        ...

    def list_users(self) -> list[AuthUser]:
        ...

    def has_user_with_role(self, role: RoleName) -> bool:
        ...

    def active_owner_count_excluding(self, user_id: int | None = None) -> int:
        ...

    def set_user_roles(self, user_id: int, roles: tuple[RoleName, ...]) -> AuthUser:
        ...

    def deactivate_user(self, user_id: int, when: datetime) -> AuthUser:
        ...

    def update_user_password(self, user_id: int, password_hash: str, when: datetime) -> None:
        ...

    def revoke_user_sessions(self, user_id: int, when: datetime) -> None:
        ...

    def record_successful_login(self, user_id: int, when: datetime) -> None:
        ...

    def create_session(
        self,
        *,
        user_id: int,
        token_hash: str,
        expires_at: datetime,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> UserSession:
        ...

    def get_user_for_active_session(self, token_hash: str, now: datetime) -> AuthUser | None:
        ...

    def touch_session(self, token_hash: str, when: datetime) -> None:
        ...

    def revoke_session(self, token_hash: str, when: datetime) -> None:
        ...

    def set_user_mfa_state(
        self,
        user_id: int,
        *,
        secret: str | None,
        enabled: bool,
        recovery_code_hashes: list[str],
        when: datetime,
    ) -> AuthUser:
        ...

    def get_user_mfa(self, user_id: int) -> dict[str, Any] | None:
        ...

    def replace_recovery_code_hashes(self, user_id: int, hashes: list[str], when: datetime) -> None:
        ...


def normalize_login(value: str) -> str:
    return str(value or "").strip().lower()


def _validate_password(password: str) -> None:
    if not isinstance(password, str) or len(password) < 8:
        raise BadRequestError(
            "password must be at least 8 characters",
            code="password_too_short",
        )


def _require_manageable_roles(roles: tuple[str, ...] | list[str] | None) -> tuple[RoleName, ...]:
    normalized = normalize_roles(roles)
    unknown = set(normalized) - set(VALID_ROLES)
    if unknown:
        raise BadRequestError("unknown role", code="unknown_role")
    return normalized


def _can_use_mfa(user: AuthUser) -> bool:
    return user.has_role(ROLE_OWNER) or user.has_role(ROLE_OPERATOR)


class UserService:
    def __init__(
        self,
        repository: UserRepository,
        *,
        session_ttl: timedelta = timedelta(hours=12),
    ) -> None:
        self.repository = repository
        self.session_ttl = session_ttl

    def create_user(
        self,
        *,
        username: str,
        password: str,
        email: str | None = None,
        display_name: str | None = None,
        roles: tuple[str, ...] | list[str] | None = None,
    ) -> AuthUser:
        username_clean = str(username or "").strip()
        username_normalized = normalize_login(username_clean)
        if not username_normalized:
            raise BadRequestError("username is required", code="username_required")
        _validate_password(password)

        email_clean = str(email).strip() if email is not None else None
        if email_clean == "":
            email_clean = None
        email_normalized = normalize_login(email_clean) if email_clean else None

        if self.repository.get_user_by_login(username_normalized) is not None:
            raise ConflictError("username already exists", code="user_already_exists")
        if email_normalized and self.repository.get_user_by_login(email_normalized) is not None:
            raise ConflictError("email already exists", code="user_already_exists")

        return self.repository.create_user(
            username=username_clean,
            username_normalized=username_normalized,
            email=email_clean,
            email_normalized=email_normalized,
            display_name=str(display_name).strip() if display_name else None,
            password_hash=hash_password(password),
            roles=_require_manageable_roles(roles),
        )

    def bootstrap_owner(
        self,
        *,
        username: str,
        password: str,
        email: str | None = None,
        display_name: str | None = None,
    ) -> AuthUser:
        if self.repository.has_user_with_role(ROLE_OWNER):
            raise ConflictError("an owner user already exists", code="owner_already_exists")

        return self.create_user(
            username=username,
            email=email,
            display_name=display_name,
            password=password,
            roles=(ROLE_OWNER,),
        )

    def reset_owner_password(self, *, login: str, password: str) -> AuthUser:
        login_normalized = normalize_login(login)
        if not login_normalized:
            raise BadRequestError("login is required", code="login_required")
        _validate_password(password)

        stored = self.repository.get_user_by_login(login_normalized)
        if stored is None or not stored.user.is_active:
            raise NotFoundError("owner user not found", code="owner_not_found")
        if not stored.user.is_owner:
            raise BadRequestError("target user is not an owner", code="target_not_owner")

        when = datetime.now(timezone.utc)
        self.repository.update_user_password(stored.user.id, hash_password(password), when)
        self.repository.revoke_user_sessions(stored.user.id, when)
        return stored.user

    def list_users(self) -> list[AuthUser]:
        loader = getattr(self.repository, "list_users", None)
        if not callable(loader):
            return []
        return list(loader())

    def set_user_roles(self, *, user_id: int, roles: tuple[str, ...] | list[str]) -> AuthUser:
        target = self.repository.get_user_by_id(user_id)
        if target is None:
            raise NotFoundError("user not found", code="user_not_found")
        normalized = _require_manageable_roles(roles)
        if target.is_owner and ROLE_OWNER not in normalized and self.repository.active_owner_count_excluding(user_id) < 1:
            raise BadRequestError("cannot remove the last active owner role", code="last_owner")
        return self.repository.set_user_roles(user_id, normalized)

    def deactivate_user(self, *, user_id: int) -> AuthUser:
        target = self.repository.get_user_by_id(user_id)
        if target is None:
            raise NotFoundError("user not found", code="user_not_found")
        if target.is_owner and self.repository.active_owner_count_excluding(user_id) < 1:
            raise BadRequestError("cannot deactivate the last active owner", code="last_owner")
        when = datetime.now(timezone.utc)
        user = self.repository.deactivate_user(user_id, when)
        self.repository.revoke_user_sessions(user_id, when)
        return user

    def authenticate_user(self, login: str, password: str) -> AuthUser | None:
        login_normalized = normalize_login(login)
        if not login_normalized:
            return None

        stored = self.repository.get_user_by_login(login_normalized)
        if stored is None or not stored.user.is_active:
            return None
        if not verify_password(password, stored.password_hash):
            return None

        self.repository.record_successful_login(stored.user.id, datetime.now(timezone.utc))
        return stored.user

    def user_requires_mfa(self, user: AuthUser) -> bool:
        return bool(getattr(user, "mfa_enabled", False))

    def verify_mfa_code(self, user: AuthUser, code: str) -> bool:
        if not self.user_requires_mfa(user):
            return True
        record = self.repository.get_user_mfa(user.id)
        if not record or not record.get("secret"):
            return False
        candidate = str(code or "").strip()
        if verify_totp_code(str(record["secret"]), candidate):
            return True

        hashes = list(record.get("recovery_code_hashes") or [])
        for index, encoded in enumerate(hashes):
            if verify_password(candidate, str(encoded)):
                remaining = [item for pos, item in enumerate(hashes) if pos != index]
                self.repository.replace_recovery_code_hashes(user.id, remaining, datetime.now(timezone.utc))
                return True
        return False

    def start_mfa_enrollment(self, user: AuthUser) -> dict[str, Any]:
        if not _can_use_mfa(user):
            raise BadRequestError("MFA enrollment is available to owner/operator users", code="mfa_not_allowed")
        secret = generate_totp_secret()
        recovery_codes = [generate_recovery_code() for _ in range(10)]
        updated = self.repository.set_user_mfa_state(
            user.id,
            secret=secret,
            enabled=False,
            recovery_code_hashes=build_recovery_code_hashes(recovery_codes),
            when=datetime.now(timezone.utc),
        )
        issuer = "Pete-Eebot"
        label = updated.email or updated.username
        return {
            "secret": secret,
            "otp_uri": f"otpauth://totp/{issuer}:{label}?secret={secret}&issuer={issuer}&algorithm=SHA1&digits=6&period=30",
            "recovery_codes": recovery_codes,
            "user": updated,
        }

    def confirm_mfa_enrollment(self, user: AuthUser, code: str) -> AuthUser:
        record = self.repository.get_user_mfa(user.id)
        if not record or not record.get("secret"):
            raise BadRequestError("MFA enrollment has not been started", code="mfa_not_started")
        if not verify_totp_code(str(record["secret"]), str(code or "")):
            raise BadRequestError("Invalid MFA code", code="invalid_mfa_code")
        return self.repository.set_user_mfa_state(
            user.id,
            secret=str(record["secret"]),
            enabled=True,
            recovery_code_hashes=list(record.get("recovery_code_hashes") or []),
            when=datetime.now(timezone.utc),
        )

    def disable_mfa(self, *, user_id: int) -> AuthUser:
        target = self.repository.get_user_by_id(user_id)
        if target is None:
            raise NotFoundError("user not found", code="user_not_found")
        return self.repository.set_user_mfa_state(
            user_id,
            secret=None,
            enabled=False,
            recovery_code_hashes=[],
            when=datetime.now(timezone.utc),
        )

    def create_session(
        self,
        user: AuthUser,
        *,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> CreatedSession:
        if not user.is_active:
            raise BadRequestError("cannot create a session for an inactive user", code="inactive_user")

        token = generate_session_token()
        now = datetime.now(timezone.utc)
        session = self.repository.create_session(
            user_id=user.id,
            token_hash=hash_session_token(token),
            expires_at=now + self.session_ttl,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        return CreatedSession(session=session, token=token)

    def validate_session_token(self, token: str) -> AuthUser | None:
        try:
            token_hash = hash_session_token(token)
        except ValueError:
            return None

        now = datetime.now(timezone.utc)
        user = self.repository.get_user_for_active_session(token_hash, now)
        if user is not None:
            self.repository.touch_session(token_hash, now)
        return user

    def revoke_session_token(self, token: str) -> None:
        self.repository.revoke_session(hash_session_token(token), datetime.now(timezone.utc))
