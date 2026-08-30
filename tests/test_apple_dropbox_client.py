from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, List, Optional
from types import SimpleNamespace
from dropbox.exceptions import DropboxException
from dropbox.files import FileMetadata
from pydantic import SecretStr
import pytest

from pete_e.infrastructure import apple_dropbox_client
from pete_e.infrastructure.apple_dropbox_client import AppleDropboxClient


def _s02_sentinel(*parts: str) -> str:
    return "-".join(("s02", "generated", *parts))


def _make_file(path: str, modified: datetime) -> FileMetadata:
    name = path.split("/")[-1]
    return FileMetadata(name=name, path_display=path, client_modified=modified)
    """Perform make file."""


class FakeDropbox:
    def __init__(
        self,
        initial_results: Iterable[object],
        incremental_results: Optional[Iterable[object]] = None,
        incremental_exception: Optional[DropboxException] = None,
    ) -> None:
        self._initial_results: List[object] = list(initial_results)
        self._incremental_results: List[object] = list(incremental_results or [])
        self._incremental_exception = incremental_exception
        self.list_calls = 0
        self.continue_calls = 0
        self._initial_index = 0
        self._incremental_index = 0
        self._serving_initial = False
        """Initialize this object."""

    def files_list_folder(self, folder_path: str, recursive: bool = False) -> object:
        del folder_path, recursive
        if self._initial_index >= len(self._initial_results):
            raise AssertionError("No initial results remaining")
        self.list_calls += 1
        self._serving_initial = True
        result = self._initial_results[self._initial_index]
        self._initial_index += 1
        if not result.has_more:
            self._serving_initial = False
        return result
        """Perform files list folder."""

    def files_list_folder_continue(self, cursor: str) -> object:
        del cursor
        self.continue_calls += 1
        if self._serving_initial:
            if self._initial_index >= len(self._initial_results):
                raise AssertionError("No continuation results remaining for initial listing")
            result = self._initial_results[self._initial_index]
            self._initial_index += 1
            if not result.has_more:
                self._serving_initial = False
            return result

        if self._incremental_exception is not None:
            raise self._incremental_exception

        if self._incremental_index >= len(self._incremental_results):
            return SimpleNamespace(entries=[], cursor="", has_more=False)

        result = self._incremental_results[self._incremental_index]
        self._incremental_index += 1
        return result
        """Perform files list folder continue."""
    """Represent FakeDropbox."""


def _build_client(fake_dbx: FakeDropbox) -> AppleDropboxClient:
    client = AppleDropboxClient.__new__(AppleDropboxClient)
    client.dbx = fake_dbx
    client.health_metrics_path = "/metrics"
    client.workouts_path = "/workouts"
    client._request_timeout = 30.0
    client._account_display_name = None
    client._folder_cursors = {}
    client._folder_latest_sync = {}
    return client
    """Perform build client."""


def test_constructor_unwraps_credentials_only_for_dropbox_sdk(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    sentinels = {
        "app_key": _s02_sentinel("dropbox", "app", "key"),
        "app_secret": _s02_sentinel("dropbox", "app", "secret"),
        "oauth2_refresh_token": _s02_sentinel("dropbox", "refresh"),
    }
    fake_settings = SimpleNamespace(
        DROPBOX_APP_KEY=SecretStr(sentinels["app_key"]),
        DROPBOX_APP_SECRET=SecretStr(sentinels["app_secret"]),
        DROPBOX_REFRESH_TOKEN=SecretStr(sentinels["oauth2_refresh_token"]),
        DROPBOX_HEALTH_METRICS_DIR="health",
        DROPBOX_WORKOUTS_DIR="workouts",
    )
    captured: dict[str, Any] = {}

    class CapturingDropbox:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

        def users_get_current_account(self) -> SimpleNamespace:
            return SimpleNamespace(
                name=SimpleNamespace(display_name="S02 Test Account"),
                email="s02@example.invalid",
            )

    monkeypatch.setattr(apple_dropbox_client, "settings", fake_settings)
    monkeypatch.setattr(apple_dropbox_client.dropbox, "Dropbox", CapturingDropbox)

    client = AppleDropboxClient(request_timeout=12.5)

    assert captured == {**sentinels, "timeout": 12.5}
    assert client.health_metrics_path == "/health"
    assert client.workouts_path == "/workouts"
    assert all(sentinel not in caplog.text for sentinel in sentinels.values())


@pytest.mark.parametrize(
    "empty_field",
    ("DROPBOX_APP_KEY", "DROPBOX_APP_SECRET", "DROPBOX_REFRESH_TOKEN"),
)
def test_constructor_rejects_empty_secret_credentials_before_sdk_call(
    monkeypatch: pytest.MonkeyPatch,
    empty_field: str,
) -> None:
    credential_values = {
        "DROPBOX_APP_KEY": SecretStr(_s02_sentinel("dropbox", "app", "key")),
        "DROPBOX_APP_SECRET": SecretStr(
            _s02_sentinel("dropbox", "app", "secret")
        ),
        "DROPBOX_REFRESH_TOKEN": SecretStr(_s02_sentinel("dropbox", "refresh")),
    }
    credential_values[empty_field] = SecretStr("")
    fake_settings = SimpleNamespace(
        **credential_values,
        DROPBOX_HEALTH_METRICS_DIR="health",
        DROPBOX_WORKOUTS_DIR="workouts",
    )
    sdk_calls = 0

    def unexpected_dropbox(**kwargs: Any) -> None:
        del kwargs
        nonlocal sdk_calls
        sdk_calls += 1

    monkeypatch.setattr(apple_dropbox_client, "settings", fake_settings)
    monkeypatch.setattr(apple_dropbox_client.dropbox, "Dropbox", unexpected_dropbox)

    with pytest.raises(
        ValueError,
        match="^Dropbox app key, secret, and refresh token must be set in config\\.$",
    ):
        AppleDropboxClient()

    assert sdk_calls == 0


def test_find_new_export_files_uses_incremental_listing() -> None:
    folder = "/metrics"
    first_mod = datetime(2024, 1, 2, tzinfo=timezone.utc)
    second_mod = datetime(2024, 1, 3, tzinfo=timezone.utc)

    initial_listing = [
        SimpleNamespace(
            entries=[_make_file(f"{folder}/HealthAutoExport-20240102.json", first_mod)],
            cursor="cursor-initial",
            has_more=False,
        )
    ]
    incremental_listing = [
        SimpleNamespace(
            entries=[_make_file(f"{folder}/HealthAutoExport-20240103.json", second_mod)],
            cursor="cursor-incremental",
            has_more=False,
        )
    ]
    fake_dbx = FakeDropbox(initial_listing, incremental_listing)
    client = _build_client(fake_dbx)

    since = datetime(2024, 1, 1, tzinfo=timezone.utc)
    first_run = client.find_new_export_files(folder, since)

    assert first_run == [(first_mod, f"{folder}/HealthAutoExport-20240102.json")]
    assert fake_dbx.list_calls == 1
    assert fake_dbx.continue_calls == 0
    assert client._folder_cursors[folder] == "cursor-initial"
    assert client._folder_latest_sync[folder] == first_mod

    second_run = client.find_new_export_files(folder, client._folder_latest_sync[folder])

    assert second_run == [(second_mod, f"{folder}/HealthAutoExport-20240103.json")]
    assert fake_dbx.list_calls == 1  # no additional full scans
    assert fake_dbx.continue_calls == 1
    assert client._folder_cursors[folder] == "cursor-incremental"
    assert client._folder_latest_sync[folder] == second_mod
    """Perform test find new export files uses incremental listing."""


def test_find_new_export_files_falls_back_on_cursor_error() -> None:
    folder = "/metrics"
    previous_sync = datetime(2024, 1, 2, tzinfo=timezone.utc)
    new_mod = datetime(2024, 1, 4, tzinfo=timezone.utc)

    fallback_listing = [
        SimpleNamespace(
            entries=[_make_file(f"{folder}/HealthAutoExport-20240104.json", new_mod)],
            cursor="cursor-refreshed",
            has_more=False,
        )
    ]

    fake_dbx = FakeDropbox(
        fallback_listing,
        incremental_results=[],
        incremental_exception=DropboxException("cursor invalid"),
    )
    client = _build_client(fake_dbx)
    client._folder_cursors[folder] = "stale-cursor"
    client._folder_latest_sync[folder] = previous_sync

    result = client.find_new_export_files(folder, previous_sync)

    assert result == [(new_mod, f"{folder}/HealthAutoExport-20240104.json")]
    assert fake_dbx.continue_calls == 1
    assert fake_dbx.list_calls == 1
    assert client._folder_cursors[folder] == "cursor-refreshed"
    assert client._folder_latest_sync[folder] == new_mod
    """Perform test find new export files falls back on cursor error."""
