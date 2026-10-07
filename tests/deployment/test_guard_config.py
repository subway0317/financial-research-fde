import asyncio
import json
import logging
from threading import Event

import pytest

from financial_research.deployment.config import DeploymentConfig
from financial_research.deployment.guard import DemoBusyError, ResearchGuard
from financial_research.deployment.logging import OperationalFormatter
from financial_research.deployment.run import main

from .conftest import SECRETS


@pytest.mark.parametrize(
    "name,value",
    [
        ("APP_ENV", "invalid"),
        ("LOG_LEVEL", "TRACE"),
        ("PORT", "0"),
        ("PORT", "65536"),
        ("PORT", "not-a-port"),
    ],
)
def test_invalid_deployment_settings_fail_safely(production_env, monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError, match="Invalid deployment configuration") as error:
        DeploymentConfig.from_env()
    assert all(secret not in str(error.value) for secret in SECRETS)


def test_config_defaults_and_commit_allowlist(production_env, monkeypatch):
    for name in ("APP_ENV", "LOG_LEVEL", "PORT"):
        monkeypatch.delenv(name)
    monkeypatch.setenv("RENDER_GIT_COMMIT", SECRETS[0])
    settings = DeploymentConfig.from_env()
    assert (settings.environment, settings.log_level, settings.port) == (
        "production",
        "INFO",
        10000,
    )
    assert settings.commit == "unknown"
    assert all(secret not in repr(settings) for secret in SECRETS)


def test_production_runner_binds_render_port_with_one_worker(production_env, monkeypatch):
    from financial_research.deployment import run

    monkeypatch.setenv("PORT", "12345")
    launched = []
    monkeypatch.setattr(run, "configure_logging", lambda level: None)
    monkeypatch.setattr(run.uvicorn, "run", lambda app, **options: launched.append(options))
    main()
    assert launched == [
        {
            "host": "0.0.0.0",
            "port": 12345,
            "workers": 1,
            "access_log": False,
            "log_config": None,
        }
    ]


@pytest.mark.parametrize("error", [ValueError("synthetic"), asyncio.CancelledError()])
def test_guard_releases_after_exception_or_cancellation(error):
    guard = ResearchGuard()

    def failed():
        raise error

    with pytest.raises(type(error)):
        guard.run(failed)
    assert not guard.busy
    assert guard.run(lambda: "complete") == "complete"


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_canceling_frontend_wait_does_not_release_a_running_worker():
    guard = ResearchGuard()
    entered, release = Event(), Event()

    def held():
        entered.set()
        assert release.wait(10)

    task = asyncio.create_task(asyncio.to_thread(guard.run, held))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert guard.busy
        with pytest.raises(DemoBusyError):
            guard.run(lambda: "must not start")
    finally:
        release.set()
    async with asyncio.timeout(5):
        while guard.busy:
            await asyncio.sleep(0)
    assert guard.run(lambda: "next") == "next"


def test_json_logger_never_serializes_arbitrary_message_exception_or_headers():
    record = logging.LogRecord("synthetic", logging.ERROR, "", 0, " ".join(SECRETS), (), None)
    record.headers = {"X-Demo-Access": SECRETS[1]}
    record.exc_info = (ValueError, ValueError(SECRETS[0]), None)
    result = OperationalFormatter().format(record)
    assert set(json.loads(result)) == {"timestamp", "level", "event"}
    assert all(secret not in result for secret in SECRETS)
