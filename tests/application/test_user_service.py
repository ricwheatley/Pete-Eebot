from __future__ import annotations

from datetime import datetime, timezone

import pytest

from pete_e.application.exceptions import ConflictError
from pete_e.application.user_service import UserService
from pete_e.domain.auth import AuthUser, ROLE_OPERATOR, ROLE_OWNER, ROLE_READ_ONLY, StoredUser, UserSession
from pete_e.infrastructure.passwords import hash_password, hash_session_token, verify_password


class FakeUserRepository:
    def __init__(self) -> None:
        self.users: dict[int, StoredUser] = {}
        self.login_index: dict[str, int] = {}
        self.sessions: dict[str, tuple[UserSession, int]] = {}
        self.next_user_id = 1
        self.next_session_id = 1
        self.last_login_user_id: int | None = None
        self.touched_token_hash: str | None = None
        self.revoked_token_hash: str | None = None

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
            id=self.next_user_id,
            username=username,
            email=email,
            display_name=display_name,
            roles=roles,
            is_active=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        self.next_user_id += 1
        stored = StoredUser(user=user, password_hash=password_hash)
        self.users[user.id] = stored
        self.login_index[username_normalized] = user.id
        if email_normalized:
            self.login_index[email_normalized] = user.id
        return user

    def get_user_by_login(self, login_normalized):
        user_id = self.login_index.get(login_normalized)
        if user_id is None:
            return None
        return self.users[user_id]

    def get_user_by_id(self, user_id):
        stored = self.users.get(user_id)
        return None if stored is None else stored.user

    def record_successful_login(self, user_id, when):
        self.last_login_user_id = user_id

    def create_session(self, *, user_id, token_hash, expires_at, ip_address=None, user_agent=None):
        session = UserSession(
            id=self.next_session_id,
            user_id=user_id,
            created_at=datetime.now(timezone.utc),
            expires_at=expires_at,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        self.next_session_id += 1
        self.sessions[token_hash] = (session, user_id)
        return session

    def get_user_for_active_session(self, token_hash, now):
        record = self.sessions.get(token_hash)
        if record is None:
            return None
        session, user_id = record
        if session.revoked_at is not None or session.expires_at <= now:
            return None
        return self.users[user_id].user

    def touch_session(self, token_hash, when):
        self.touched_token_hash = token_hash

    def revoke_session(self, token_hash, when):
        self.revoked_token_hash = token_hash


def test_password_hash_round_trip_and_wrong_password_rejection() -> None:
    encoded = hash_password("correct horse battery staple", iterations=1_000, salt=b"fixed-salt-12345")

    assert encoded.startswith("pbkdf2_sha256$1000$")
    assert verify_password("correct horse battery staple", encoded)
    assert not verify_password("wrong password", encoded)


def test_create_user_normalizes_identity_hashes_password_and_assigns_role() -> None:
    repo = FakeUserRepository()
    service = UserService(repo)

    user = service.create_user(
        username=" Pete ",
        email="PETE@example.com ",
        display_name="Pete",
        password="correct horse battery staple",
        roles=[ROLE_OWNER],
    )

    stored = repo.get_user_by_login("pete")
    assert user.username == "Pete"
    assert user.email == "PETE@example.com"
    assert user.roles == (ROLE_OWNER,)
    assert stored is not None
    assert stored.password_hash != "correct horse battery staple"
    assert verify_password("correct horse battery staple", stored.password_hash)
    assert repo.get_user_by_login("pete@example.com") == stored


def test_create_user_defaults_to_read_only_and_rejects_duplicate_login() -> None:
    repo = FakeUserRepository()
    service = UserService(repo)

    user = service.create_user(username="viewer", password="password123")

    assert user.roles == (ROLE_READ_ONLY,)
    with pytest.raises(ConflictError):
        service.create_user(username="VIEWER", password="password123")


def test_authenticate_user_accepts_username_or_email_and_records_login() -> None:
    repo = FakeUserRepository()
    service = UserService(repo)
    user = service.create_user(
        username="operator",
        email="operator@example.com",
        password="password123",
        roles=[ROLE_OPERATOR],
    )

    assert service.authenticate_user("operator@example.com", "password123") == user
    assert service.authenticate_user("operator", "wrong") is None
    assert repo.last_login_user_id == user.id


def test_session_token_is_returned_once_and_stored_as_hash() -> None:
    repo = FakeUserRepository()
    service = UserService(repo)
    user = service.create_user(username="owner", password="password123", roles=[ROLE_OWNER])

    created = service.create_session(user, ip_address="127.0.0.1", user_agent="pytest")
    token_hash = hash_session_token(created.token)

    assert created.token
    assert created.session.user_id == user.id
    assert token_hash in repo.sessions
    assert created.token not in repo.sessions
    assert service.validate_session_token(created.token) == user
    assert repo.touched_token_hash == token_hash

    service.revoke_session_token(created.token)
    assert repo.revoked_token_hash == token_hash
