"""Application service for browser user and session primitives."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Protocol

from pete_e.application.exceptions import BadRequestError, ConflictError
from pete_e.domain.auth import AuthUser, CreatedSession, RoleName, StoredUser, UserSession, normalize_roles
from pete_e.infrastructure.passwords import (
    generate_session_token,
    hash_password,
    hash_session_token,
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


def normalize_login(value: str) -> str:
    return str(value or "").strip().lower()


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
        if not isinstance(password, str) or len(password) < 8:
            raise BadRequestError(
                "password must be at least 8 characters",
                code="password_too_short",
            )

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
            roles=normalize_roles(roles),
        )

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
