from typer.testing import CliRunner

from pete_e.cli import messenger


runner = CliRunner()


def _fake_tokens() -> dict[str, str]:
    return {
        "access_token": "scanner-fixture-access-" + ("a" * 32),
        "refresh_token": "scanner-fixture-refresh-" + ("b" * 32),
    }


def test_refresh_withings_does_not_print_token_material(monkeypatch, tmp_path):
    tokens = _fake_tokens()

    class FakeClient:
        def _refresh_access_token(self):
            return tokens

    monkeypatch.setattr(messenger, "WithingsClient", FakeClient)
    monkeypatch.setattr(messenger, "configured_withings_token_file", lambda: tmp_path / "tokens.json")

    result = runner.invoke(messenger.app, ["refresh-withings"])

    assert result.exit_code == 0
    assert tokens["access_token"] not in result.stdout
    assert tokens["refresh_token"] not in result.stdout
    assert "not displayed" in result.stdout


def test_withings_code_does_not_print_token_material(monkeypatch, tmp_path):
    tokens = _fake_tokens()

    class FakeClient:
        def _save_tokens(self, supplied_tokens):
            assert supplied_tokens == tokens

    monkeypatch.setattr(messenger.withings_oauth_helper, "exchange_code_for_tokens", lambda _code: tokens)
    monkeypatch.setattr(messenger, "WithingsClient", FakeClient)
    monkeypatch.setattr(messenger, "configured_withings_token_file", lambda: tmp_path / "tokens.json")

    result = runner.invoke(messenger.app, ["withings-code", "scanner-fixture-code"])

    assert result.exit_code == 0
    assert tokens["access_token"] not in result.stdout
    assert tokens["refresh_token"] not in result.stdout
    assert "not displayed" in result.stdout
