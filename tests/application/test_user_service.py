from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from pete_e.application.exceptions import BadRequestError, ConflictError, NotFoundError
from pete_e.application.user_service import UserService
from pete_e.domain.auth import AuthUser, ROLE_OPERATOR, ROLE_OWNER, ROLE_READ_ONLY, StoredUser, UserSession
from pete_e.infrastructure.passwords import hash_password, hash_session_token, verify_password
from pete_e.infrastructure.passwords import totp_code


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
        self.revoked_user_id: int | None = None
        self.mfa_records: dict[int, dict] = {}

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

    def has_user_with_role(self, role):
        return any(role in stored.user.roles and stored.user.is_active for stored in self.users.values())

    def list_users(self):
        return [stored.user for stored in self.users.values()]

    def active_owner_count_excluding(self, user_id=None):
        return sum(
            1
            for stored in self.users.values()
            if stored.user.is_active and ROLE_OWNER in stored.user.roles and stored.user.id != user_id
        )

    def set_user_roles(self, user_id, roles):
        stored = self.users[user_id]
        user = replace(stored.user, roles=roles)
        self.users[user_id] = StoredUser(user=user, password_hash=stored.password_hash)
        return user

    def deactivate_user(self, user_id, when):
        stored = self.users[user_id]
        user = replace(stored.user, is_active=False, updated_at=when)
        self.users[user_id] = StoredUser(user=user, password_hash=stored.password_hash)
        return user

    def update_user_password(self, user_id, password_hash, when):
        stored = self.users[user_id]
        self.users[user_id] = StoredUser(user=stored.user, password_hash=password_hash)

    def revoke_user_sessions(self, user_id, when):
        self.revoked_user_id = user_id
        for token_hash, (session, session_user_id) in list(self.sessions.items()):
            if session_user_id == user_id and session.revoked_at is None:
                self.sessions[token_hash] = (replace(session, revoked_at=when), session_user_id)

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

    def set_user_mfa_state(self, user_id, *, secret, enabled, recovery_code_hashes, when):
        self.mfa_records[user_id] = {
            "secret": secret,
            "enabled": enabled,
            "recovery_code_hashes": list(recovery_code_hashes),
        }
        stored = self.users[user_id]
        user = replace(stored.user, mfa_enabled=enabled, updated_at=when)
        self.users[user_id] = StoredUser(user=user, password_hash=stored.password_hash)
        return user

    def get_user_mfa(self, user_id):
        record = self.mfa_records.get(user_id)
        if record is None:
            return None
        return dict(record)

    def replace_recovery_code_hashes(self, user_id, hashes, when):
        self.mfa_records[user_id]["recovery_code_hashes"] = list(hashes)


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


def test_create_user_rejects_duplicate_email() -> None:
    repo = FakeUserRepository()
    service = UserService(repo)

    service.create_user(username="owner", email="owner@example.com", password="password123")

    with pytest.raises(ConflictError):
        service.create_user(username="other", email="OWNER@example.com", password="password123")


def test_bootstrap_owner_creates_owner_when_none_exists() -> None:
    repo = FakeUserRepository()
    service = UserService(repo)

    user = service.bootstrap_owner(
        username="owner",
        email="owner@example.com",
        display_name="Owner",
        password="password123",
    )

    assert user.roles == (ROLE_OWNER,)
    assert repo.get_user_by_login("owner@example.com") is not None


def test_bootstrap_owner_rejects_existing_owner() -> None:
    repo = FakeUserRepository()
    service = UserService(repo)

    service.bootstrap_owner(username="owner", password="password123")

    with pytest.raises(ConflictError):
        service.bootstrap_owner(username="second-owner", password="password123")


def test_reset_owner_password_requires_owner_and_revokes_sessions() -> None:
    repo = FakeUserRepository()
    service = UserService(repo)
    owner = service.bootstrap_owner(username="owner", password="password123")
    old_hash = repo.get_user_by_login("owner").password_hash
    created = service.create_session(owner)

    reset_user = service.reset_owner_password(login="OWNER", password="new-password123")

    stored = repo.get_user_by_login("owner")
    assert reset_user == owner
    assert stored.password_hash != old_hash
    assert verify_password("new-password123", stored.password_hash)
    assert repo.revoked_user_id == owner.id
    assert service.validate_session_token(created.token) is None


def test_reset_owner_password_rejects_non_owner() -> None:
    repo = FakeUserRepository()
    service = UserService(repo)
    service.create_user(username="viewer", password="password123")
    old_hash = repo.get_user_by_login("viewer").password_hash

    with pytest.raises(BadRequestError):
        service.reset_owner_password(login="viewer", password="new-password123")

    assert repo.get_user_by_login("viewer").password_hash == old_hash
    assert repo.revoked_user_id is None

    with pytest.raises(NotFoundError):
        service.reset_owner_password(login="missing", password="new-password123")


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


def test_owner_can_manage_users_roles_and_deactivation() -> None:
    repo = FakeUserRepository()
    service = UserService(repo)
    owner = service.create_user(username="owner", password="password123", roles=[ROLE_OWNER])
    operator = service.create_user(username="operator", password="password123", roles=[ROLE_READ_ONLY])

    updated = service.set_user_roles(user_id=operator.id, roles=[ROLE_OPERATOR])
    deactivated = service.deactivate_user(user_id=operator.id)

    assert owner in service.list_users()
    assert updated.roles == (ROLE_OPERATOR,)
    assert deactivated.is_active is False
    assert repo.revoked_user_id == operator.id


def test_cannot_remove_or_deactivate_last_owner() -> None:
    repo = FakeUserRepository()
    service = UserService(repo)
    owner = service.create_user(username="owner", password="password123", roles=[ROLE_OWNER])

    with pytest.raises(BadRequestError):
        service.set_user_roles(user_id=owner.id, roles=[ROLE_READ_ONLY])
    with pytest.raises(BadRequestError):
        service.deactivate_user(user_id=owner.id)


def test_mfa_enrollment_confirmation_and_recovery_code() -> None:
    repo = FakeUserRepository()
    service = UserService(repo)
    user = service.create_user(username="operator", password="password123", roles=[ROLE_OPERATOR])

    enrollment = service.start_mfa_enrollment(user)
    enabled = service.confirm_mfa_enrollment(user, totp_code(enrollment["secret"]))

    assert enabled.mfa_enabled is True
    assert service.verify_mfa_code(enabled, totp_code(enrollment["secret"]))
    assert service.verify_mfa_code(enabled, enrollment["recovery_codes"][0])
    assert not service.verify_mfa_code(enabled, enrollment["recovery_codes"][0])


def test_mfa_rejects_read_only_enrollment_and_owner_can_reset() -> None:
    repo = FakeUserRepository()
    service = UserService(repo)
    viewer = service.create_user(username="viewer", password="password123", roles=[ROLE_READ_ONLY])

    with pytest.raises(BadRequestError):
        service.start_mfa_enrollment(viewer)

    operator = service.create_user(username="operator", password="password123", roles=[ROLE_OPERATOR])
    enrollment = service.start_mfa_enrollment(operator)
    enabled = service.confirm_mfa_enrollment(operator, totp_code(enrollment["secret"]))
    reset = service.disable_mfa(user_id=enabled.id)

    assert reset.mfa_enabled is False
