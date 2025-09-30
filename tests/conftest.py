import sys
import os
import types
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/postgres")


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


if "pydantic" not in sys.modules:
    from pydantic_mock import Field, FieldInfo, SecretStr

    pydantic_module = types.ModuleType("pydantic")
    pydantic_module.Field = Field
    pydantic_module.FieldInfo = FieldInfo
    pydantic_module.SecretStr = SecretStr
    pydantic_module.__all__ = ["Field", "FieldInfo", "SecretStr"]
    pydantic_module.__file__ = __file__

    sys.modules["pydantic"] = pydantic_module


if "pydantic_settings" not in sys.modules:
    from pydantic_settings_mock import BaseSettings, SettingsConfigDict

    settings_module = types.ModuleType("pydantic_settings")
    settings_module.BaseSettings = BaseSettings
    settings_module.SettingsConfigDict = SettingsConfigDict
    settings_module.__all__ = ["BaseSettings", "SettingsConfigDict"]
    settings_module.__file__ = __file__

    sys.modules["pydantic_settings"] = settings_module


if "psycopg" not in sys.modules:
    psycopg = types.ModuleType("psycopg")
    rows_module = types.ModuleType("psycopg.rows")
    conninfo_module = types.ModuleType("psycopg.conninfo")
    types_module = types.ModuleType("psycopg.types")
    json_module = types.ModuleType("psycopg.types.json")
    sql_module = types.ModuleType("psycopg.sql")

    def _dict_row(*args, **kwargs):  # pragma: no cover - placeholder
        return {}

    def _make_conninfo(*args, **kwargs):  # pragma: no cover - placeholder
        return ""

    class _Json(dict):  # pragma: no cover - metadata container
        pass

    rows_module.dict_row = _dict_row
    conninfo_module.make_conninfo = _make_conninfo
    json_module.Json = _Json
    json_module.json = _Json

    class _Connection:  # pragma: no cover - placeholder connection type
        def cursor(self, *a, **k):
            return types.SimpleNamespace(
                __enter__=lambda s: s,
                __exit__=lambda s, *exc: None,
                execute=lambda *args, **kwargs: None,
                fetchone=lambda: None,
                fetchall=lambda: [],
            )
        
        def close(self): pass

    # Fake connect for "from psycopg import connect"
    def _fake_connect(*args, **kwargs):
        return _Connection()

    psycopg.Connection = _Connection
    psycopg.connect = _fake_connect
    psycopg.rows = rows_module
    psycopg.conninfo = conninfo_module
    psycopg.types = types_module
    psycopg.sql = sql_module

    def _sql_identity(value):  # pragma: no cover - placeholder
        return value

    sql_module.SQL = _sql_identity
    sql_module.Identifier = _sql_identity
    sql_module.Literal = _sql_identity

    # Add __file__ attributes so pytest’s import machinery doesn’t choke
    psycopg.__file__ = __file__
    rows_module.__file__ = __file__
    conninfo_module.__file__ = __file__
    types_module.__file__ = __file__
    json_module.__file__ = __file__
    sql_module.__file__ = __file__

    sys.modules["psycopg"] = psycopg
    sys.modules["psycopg.rows"] = rows_module
    sys.modules["psycopg.conninfo"] = conninfo_module
    sys.modules["psycopg.types"] = types_module
    sys.modules["psycopg.types.json"] = json_module
    sys.modules["psycopg.sql"] = sql_module



if "psycopg_pool" not in sys.modules:
    psycopg_pool_module = types.ModuleType("psycopg_pool")

    class ConnectionPool:  # pragma: no cover - stub implementation
        def __init__(self, *args, **kwargs):
            pass

        def close(self) -> None:
            pass

    psycopg_pool_module.ConnectionPool = ConnectionPool

    # add __file__ so pytest doesn’t complain
    psycopg_pool_module.__file__ = __file__

    sys.modules["psycopg_pool"] = psycopg_pool_module



if "dropbox" not in sys.modules:
    dropbox_module = types.ModuleType("dropbox")
    exceptions_module = types.ModuleType("dropbox.exceptions")
    files_module = types.ModuleType("dropbox.files")

    class DropboxException(Exception):  # pragma: no cover - stub
        pass

    class AuthError(DropboxException):  # pragma: no cover - stub
        pass

    class FileMetadata:  # pragma: no cover - stub type
        def __init__(self, name: str = "stub", client_modified=None, path_display: str = "/stub"):
            from datetime import datetime, timezone
            self.name = name
            self.client_modified = client_modified or datetime.now(timezone.utc)
            self.path_display = path_display

    class ListFolderResult:  # pragma: no cover - stub type
        def __init__(self, entries=None, cursor="cursor", has_more=False):
            self.entries = entries or []
            self.has_more = has_more
            self.cursor = cursor

    class Dropbox:  # pragma: no cover - stub client
        def __init__(self, *args, **kwargs):
            pass

        def users_get_current_account(self):
            return types.SimpleNamespace(name=types.SimpleNamespace(display_name="Stub"))

    dropbox_module.Dropbox = Dropbox
    dropbox_module.exceptions = exceptions_module
    dropbox_module.files = files_module
    exceptions_module.AuthError = AuthError
    exceptions_module.DropboxException = DropboxException
    files_module.FileMetadata = FileMetadata
    files_module.ListFolderResult = ListFolderResult

    # Add __file__ attributes so pytest’s import/rewrite doesn’t choke
    dropbox_module.__file__ = __file__
    exceptions_module.__file__ = __file__
    files_module.__file__ = __file__

    sys.modules["dropbox"] = dropbox_module
    sys.modules["dropbox.exceptions"] = exceptions_module
    sys.modules["dropbox.files"] = files_module


if "tenacity" not in sys.modules:
    tenacity_module = types.ModuleType("tenacity")

    class RetryError(Exception):  # pragma: no cover - stub
        def __init__(self, last_attempt=None):
            super().__init__("Retry failed")
            self.last_attempt = last_attempt

    class RetryCallState:  # pragma: no cover - stub for logging hooks
        def __init__(self, attempt_number: int = 1, exception: Exception | None = None, sleep: float = 0.0):
            self.attempt_number = attempt_number
            self.outcome = types.SimpleNamespace(exception=lambda: exception)
            self.next_action = types.SimpleNamespace(sleep=sleep)

    class _WaitSpec:  # pragma: no cover - supports addition
        def __add__(self, other):
            return self

    class Retrying:  # pragma: no cover - simplistic retry shim
        def __init__(self, *, before_sleep=None, reraise=True, **kwargs):
            self._before_sleep = before_sleep
            self._reraise = reraise

        def __call__(self, func):
            try:
                return func()
            except Exception as exc:  # pragma: no cover - fallback path
                # Bind exc into the lambda so it's not lost after except scope
                attempt = types.SimpleNamespace(exception=lambda exc=exc: exc)
                if self._before_sleep:
                    state = RetryCallState(exception=exc)
                    self._before_sleep(state)
                if self._reraise:
                    raise RetryError(last_attempt=attempt) from exc
                raise

    def stop_after_attempt(*args, **kwargs):  # pragma: no cover - metadata only
        return None

    def wait_exponential(*args, **kwargs):  # pragma: no cover - metadata only
        return _WaitSpec()

    def wait_random(*args, **kwargs):  # pragma: no cover - metadata only
        return _WaitSpec()

    tenacity_module.RetryError = RetryError
    tenacity_module.RetryCallState = RetryCallState
    tenacity_module.Retrying = Retrying
    tenacity_module.stop_after_attempt = stop_after_attempt
    tenacity_module.wait_exponential = wait_exponential
    tenacity_module.wait_random = wait_random

    sys.modules["tenacity"] = tenacity_module


if "requests" not in sys.modules:
    requests_module = types.ModuleType("requests")
    exceptions_module = types.ModuleType("requests.exceptions")

    class RequestException(Exception):  # pragma: no cover - stub hierarchy
        pass

    class HTTPError(RequestException):  # pragma: no cover - mimics requests.HTTPError
        def __init__(self, message: str | None = None, *, response=None):
            super().__init__(message or "HTTP error")
            self.response = response

    class Response:  # pragma: no cover - basic response container
        def __init__(self, status_code: int = 200, json_data: dict | None = None):
            self.status_code = status_code
            self._json_data = json_data or {}

        def json(self):
            return self._json_data

        def raise_for_status(self):
            if self.status_code >= 400:
                raise HTTPError(f"HTTP {self.status_code}", response=self)

    def _fake_get(*args, **kwargs):  # pragma: no cover - patched in tests
        raise NotImplementedError

    def _fake_post(*args, **kwargs):  # pragma: no cover - patched in tests
        raise NotImplementedError

    requests_module.get = _fake_get
    requests_module.post = _fake_post
    requests_module.Response = Response
    requests_module.RequestException = RequestException
    requests_module.HTTPError = HTTPError
    requests_module.exceptions = exceptions_module
    exceptions_module.RequestException = RequestException
    exceptions_module.HTTPError = HTTPError

    # add __file__
    requests_module.__file__ = __file__
    exceptions_module.__file__ = __file__

    sys.modules["requests"] = requests_module
    sys.modules["requests.exceptions"] = exceptions_module


if "rich" not in sys.modules:
    rich_module = types.ModuleType("rich")
    console_module = types.ModuleType("rich.console")
    table_module = types.ModuleType("rich.table")

    class Console:  # pragma: no cover - simple print shim
        def __init__(self, *args, **kwargs):
            pass

        def print(self, *args, **kwargs):
            pass

        def log(self, *args, **kwargs):  # pragma: no cover - message sink
            pass

    class Table:  # pragma: no cover - data holder used in CLI output
        def __init__(self, *args, **kwargs):
            self.rows = []

        def add_column(self, *args, **kwargs):
            pass

        def add_row(self, *args, **kwargs):
            self.rows.append(args)

    console_module.Console = Console
    table_module.Table = Table
    console_module.__file__ = __file__
    table_module.__file__ = __file__
    rich_module.console = console_module
    rich_module.table = table_module
    rich_module.__file__ = __file__

    sys.modules["rich"] = rich_module
    sys.modules["rich.console"] = console_module
    sys.modules["rich.table"] = table_module


if "typer" not in sys.modules:
    typer_module = types.ModuleType("typer")

    class Exit(Exception):
        def __init__(self, code: int = 0):
            super().__init__(code)
            self.exit_code = code

    class TyperApp:
        def __init__(self, *args, **kwargs):
            self._commands: dict[str, callable] = {}

        def command(self, name: str | None = None, **kwargs):
            def decorator(func):
                command_name = name or func.__name__.replace("_", "-")
                self._commands[command_name] = func
                return func
            return decorator

    def option(*args, **kwargs):
        return {"args": args, "kwargs": kwargs}

    def argument(*args, **kwargs):
        return {"args": args, "kwargs": kwargs}

    _echo_messages: list[str] = []

    def echo(message: object) -> None:
        _echo_messages.append(str(message))

    typer_module.Exit = Exit
    typer_module.Typer = TyperApp
    typer_module.Option = option
    typer_module.Argument = argument
    typer_module.echo = echo
    typer_module._echo_messages = _echo_messages

    class CliResult:
        def __init__(self, exit_code: int, stdout: str, exception: Exception | None = None):
            self.exit_code = exit_code
            self.stdout = stdout
            self.exception = exception

    class CliRunner:
        def invoke(self, app: TyperApp, args: list[str] | None = None, **kwargs):
            """
            Minimal stub of Click's CliRunner.invoke.
            Accepts extra kwargs (e.g. catch_exceptions) for compatibility.
            """
            args = list(args or [])
            if not args:
                raise ValueError("A command name is required")

            command_name = args[0]
            func = app._commands.get(command_name)
            if func is None:
                raise ValueError(f"Unknown command: {command_name}")

            kwargs_dict: dict[str, object] = {}
            idx = 1
            while idx < len(args):
                token = args[idx]
                if token.startswith("--"):
                    key = token.lstrip("-").replace("-", "_")
                    idx += 1
                    if idx >= len(args):
                        raise ValueError(f"Missing value for option {token}")
                    value_token = args[idx]
                    if value_token.lower() in {"true", "false"}:
                        value: object = value_token.lower() == "true"
                    else:
                        try:
                            value = int(value_token)
                        except ValueError:
                            try:
                                value = float(value_token)
                            except ValueError:
                                value = value_token
                    kwargs_dict[key] = value
                else:
                    kwargs_dict.setdefault("_args", []).append(token)
                idx += 1

            typer_module._echo_messages.clear()
            try:
                if "_args" in kwargs_dict:
                    positional = kwargs_dict.pop("_args")
                    result = func(*positional, **kwargs_dict)
                else:
                    result = func(**kwargs_dict)
            except Exit as exc:
                stdout = "\n".join(typer_module._echo_messages)
                if stdout:
                    stdout += "\n"
                return CliResult(exc.exit_code, stdout)
            except Exception as exc:
                stdout = "\n".join(typer_module._echo_messages)
                if stdout:
                    stdout += "\n"
                return CliResult(1, stdout, exception=exc)

            stdout = "\n".join(typer_module._echo_messages)
            if stdout:
                stdout += "\n"
            return CliResult(0, stdout, exception=None if result is None else result)

    testing_module = types.ModuleType("typer.testing")
    testing_module.CliRunner = CliRunner
    typer_module.testing = testing_module

    # add __file__ attributes
    typer_module.__file__ = __file__
    testing_module.__file__ = __file__

    sys.modules["typer"] = typer_module
    sys.modules["typer.testing"] = testing_module

    def option(*args, **kwargs):  # pragma: no cover - metadata only
        return {"args": args, "kwargs": kwargs}

    def argument(*args, **kwargs):  # pragma: no cover - metadata only
        return {"args": args, "kwargs": kwargs}

    _echo_messages: list[str] = []

    def echo(message: object) -> None:
        _echo_messages.append(str(message))

    typer_module.Exit = Exit
    typer_module.Typer = TyperApp
    typer_module.Option = option
    typer_module.Argument = argument
    typer_module.echo = echo
    typer_module._echo_messages = _echo_messages

    class CliResult:
        def __init__(self, exit_code: int, stdout: str, exception: Exception | None = None):
            self.exit_code = exit_code
            self.stdout = stdout
            self.exception = exception

    class CliRunner:
        def invoke(self, app: TyperApp, args: list[str] | None = None, **kwargs):
            """
            Minimal stub of Click's CliRunner.invoke.

            Accepts extra kwargs (e.g. catch_exceptions) for compatibility,
            but ignores them since our TyperApp stub doesn’t use them.
            """
            args = list(args or [])
            if not args:
                raise ValueError("A command name is required")

            command_name = args[0]
            func = app._commands.get(command_name)
            if func is None:
                raise ValueError(f"Unknown command: {command_name}")

            kwargs_dict: dict[str, object] = {}
            idx = 1
            while idx < len(args):
                token = args[idx]
                if token.startswith("--"):
                    key = token.lstrip("-").replace("-", "_")
                    idx += 1
                    if idx >= len(args):
                        raise ValueError(f"Missing value for option {token}")
                    value_token = args[idx]
                    if value_token.lower() in {"true", "false"}:
                        value: object = value_token.lower() == "true"
                    else:
                        try:
                            value = int(value_token)
                        except ValueError:
                            try:
                                value = float(value_token)
                            except ValueError:
                                value = value_token
                    kwargs_dict[key] = value
                else:
                    # Positional argument - store as-is using incremental key
                    kwargs_dict.setdefault("_args", []).append(token)
                idx += 1

            typer_module._echo_messages.clear()
            try:
                if "_args" in kwargs_dict:
                    positional = kwargs_dict.pop("_args")
                    result = func(*positional, **kwargs_dict)
                else:
                    result = func(**kwargs_dict)
            except Exit as exc:
                stdout = "\n".join(typer_module._echo_messages)
                if stdout:
                    stdout += "\n"
                return CliResult(exc.exit_code, stdout)
            except Exception as exc:  # pragma: no cover - diagnostic path
                stdout = "\n".join(typer_module._echo_messages)
                if stdout:
                    stdout += "\n"
                return CliResult(1, stdout, exception=exc)

            stdout = "\n".join(typer_module._echo_messages)
            if stdout:
                stdout += "\n"
            return CliResult(0, stdout, exception=None if result is None else result)


    testing_module = types.ModuleType("typer.testing")
    testing_module.CliRunner = CliRunner
    typer_module.testing = testing_module

    models_module = types.ModuleType("typer.models")
    models_module.Option = option
    models_module.Argument = argument
    models_module.__file__ = __file__
    typer_module.models = models_module

    sys.modules["typer"] = typer_module
    sys.modules["typer.testing"] = testing_module
    sys.modules["typer.models"] = models_module

_DEFAULT_ENV = {
    "USER_DATE_OF_BIRTH": "1990-01-01",
    "USER_HEIGHT_CM": "180",
    "USER_GOAL_WEIGHT_KG": "80",
    "TELEGRAM_TOKEN": "dummy",
    "TELEGRAM_CHAT_ID": "123456",
    "WITHINGS_CLIENT_ID": "",
    "WITHINGS_CLIENT_SECRET": "",
    "WITHINGS_REDIRECT_URI": "",
    "WITHINGS_REFRESH_TOKEN": "",
    "WGER_API_KEY": "dummy",
    "DROPBOX_HEALTH_METRICS_DIR": "/health",
    "DROPBOX_WORKOUTS_DIR": "/workouts",
    "DROPBOX_APP_KEY": "",
    "DROPBOX_APP_SECRET": "",
    "DROPBOX_REFRESH_TOKEN": "",
    "APPLE_MAX_STALE_DAYS": "3",
    "WITHINGS_ALERT_REAUTH": "true",
    "POSTGRES_USER": "postgres",
    "POSTGRES_PASSWORD": "postgres",
    "POSTGRES_HOST": "localhost",
    "POSTGRES_DB": "postgres",
    "DATABASE_URL": "postgresql://postgres:postgres@localhost:5432/postgres",
}

for _key, _value in _DEFAULT_ENV.items():
    os.environ.setdefault(_key, _value)


def pytest_configure():
    """Ensure environment variables are populated for settings initialisation."""

    for key, value in _DEFAULT_ENV.items():
        os.environ.setdefault(key, value)
