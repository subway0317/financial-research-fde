from pathlib import Path

import pytest
from reports.conftest import report_agent_factory as report_agent_factory

from financial_research.deployment.config import DeploymentConfig

SECRETS = ("__OPENAI_SECRET_SENTINEL__", "__DEMO_ACCESS_SENTINEL__", "__SEC_SENTINEL__")


@pytest.fixture
def production_env(monkeypatch):
    values = {
        "APP_ENV": "production",
        "LOG_LEVEL": "INFO",
        "PORT": "10000",
        "OPENAI_API_KEY": SECRETS[0],
        "OPENAI_MODEL": "synthetic-model",
        "OPENAI_TIMEOUT_SECONDS": "120",
        "SEC_USER_AGENT": SECRETS[2],
        "DEMO_ACCESS_TOKEN": SECRETS[1],
        "RENDER_GIT_COMMIT": "6dcd894ec763f6ddd04d98d71994f521440346f7",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    return DeploymentConfig.from_env()


@pytest.fixture
def compiled_frontend(tmp_path: Path) -> Path:
    directory = tmp_path / "frontend"
    assets = directory / "assets"
    assets.mkdir(parents=True)
    (directory / "index.html").write_text(
        '<html><link href="/assets/test.css"><script src="/assets/test.js"></script></html>'
    )
    (assets / "test.js").write_text('document.title = "Synthetic workspace";')
    (assets / "test.css").write_text("body { color: black; }")
    return directory
