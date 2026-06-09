import pete_e.cli.status as status
import pete_e.cli.messenger as messenger
from pete_e.cli.messenger import app
from pete_e.cli.status import CheckResult
from pete_e.infrastructure.ollama_client import OllamaModelMissingError
from typer.testing import CliRunner


runner = CliRunner()


def test_status_cli_all_ok(monkeypatch):
    """CLI exits with code 0 when all dependencies are healthy."""
    def stub(*, timeout=status.DEFAULT_TIMEOUT_SECONDS, checks=None):
        return [
            CheckResult("DB", True, "3ms"),
            CheckResult("Dropbox", True, "demo@account"),
            CheckResult("Withings", True, "scale reachable"),
            CheckResult("Telegram", True, "@peteeebot chat configured"),
            CheckResult("Wger", True, "wger.de (api-key)"),
            CheckResult("LLM", True, "qwen2.5:1.5b OK"),
        ]

    monkeypatch.setattr(status, "run_status_checks", stub)
    monkeypatch.setattr(messenger, "run_status_checks", stub)

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    assert "DB" in result.stdout
    assert "Dropbox" in result.stdout
    assert "Withings" in result.stdout
    assert "Telegram" in result.stdout
    assert "Wger" in result.stdout
    assert "LLM" in result.stdout
    assert "OK" in result.stdout


def test_status_cli_failure_propagates(monkeypatch):
    """CLI exits with non-zero when any dependency fails."""
    captured = {}

    def fake_checks(*, timeout, checks=None):
        captured["timeout"] = timeout
        return [
            CheckResult("DB", False, "connection refused"),
            CheckResult("Dropbox", True, "demo"),
            CheckResult("Withings", True, "scale reachable"),
            CheckResult("Telegram", True, "@peteeebot chat configured"),
            CheckResult("Wger", True, "wger.de (api-key)"),
            CheckResult("LLM", True, "disabled"),
        ]

    monkeypatch.setattr(status, "run_status_checks", fake_checks)
    monkeypatch.setattr(messenger, "run_status_checks", fake_checks)

    result = runner.invoke(app, ["status", "--timeout", "2.5"])

    assert result.exit_code == 1
    assert "FAIL" in result.stdout
    assert "connection refused" in result.stdout
    assert captured["timeout"] == 2.5


def test_llm_status_disabled_does_not_call_ollama(monkeypatch):
    monkeypatch.setattr(status.settings, "PETEEEBOT_LLM_ENABLED", False, raising=False)

    def fail_if_called(**kwargs):
        raise AssertionError("Ollama client should not be created when LLM is disabled")

    monkeypatch.setattr(status, "OllamaChatClient", fail_if_called)

    result = status.check_llm(timeout=1.5)

    assert result == CheckResult("LLM", True, "disabled")


def test_llm_status_enabled_pings_ollama(monkeypatch):
    calls = {}
    monkeypatch.setattr(status.settings, "PETEEEBOT_LLM_ENABLED", True, raising=False)
    monkeypatch.setattr(status.settings, "PETEEEBOT_LLM_BASE_URL", "http://ollama.test:11434", raising=False)
    monkeypatch.setattr(status.settings, "PETEEEBOT_LLM_MODEL", "qwen2.5:1.5b", raising=False)

    class _FakeOllamaClient:
        def __init__(self, *, base_url: str, model: str, timeout_seconds: float) -> None:
            calls["base_url"] = base_url
            calls["model"] = model
            calls["timeout_seconds"] = timeout_seconds

        def ping(self) -> str:
            return "qwen2.5:1.5b OK"

    monkeypatch.setattr(status, "OllamaChatClient", _FakeOllamaClient)

    result = status.check_llm(timeout=2.5)

    assert result == CheckResult("LLM", True, "qwen2.5:1.5b OK")
    assert calls == {
        "base_url": "http://ollama.test:11434",
        "model": "qwen2.5:1.5b",
        "timeout_seconds": 2.5,
    }


def test_llm_status_enabled_failure_returns_failed_result(monkeypatch):
    monkeypatch.setattr(status.settings, "PETEEEBOT_LLM_ENABLED", True, raising=False)

    class _FailingOllamaClient:
        def __init__(self, **kwargs) -> None:
            pass

        def ping(self) -> str:
            raise RuntimeError("ollama unavailable")

    monkeypatch.setattr(status, "OllamaChatClient", _FailingOllamaClient)

    result = status.check_llm(timeout=2.5)

    assert result == CheckResult("LLM", False, "ollama unavailable")


def test_llm_status_missing_model_reports_clear_failure(monkeypatch):
    monkeypatch.setattr(status.settings, "PETEEEBOT_LLM_ENABLED", True, raising=False)

    class _MissingModelOllamaClient:
        def __init__(self, **kwargs) -> None:
            pass

        def ping(self) -> str:
            raise OllamaModelMissingError(
                "configured model missing: qwen2.5:1.5b (available: llama3.2)"
            )

    monkeypatch.setattr(status, "OllamaChatClient", _MissingModelOllamaClient)

    result = status.check_llm(timeout=2.5)

    assert result == CheckResult(
        "LLM",
        False,
        "configured model missing: qwen2.5:1.5b (available: llama3.2)",
    )
