import json
import logging
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from reports.conftest import REQUEST

from financial_research.api.app import create_app
from financial_research.deployment.app import create_production_app
from financial_research.deployment.config import DeploymentConfig
from financial_research.deployment.logging import OperationalFormatter
from financial_research.reports.service import ReportWorkflowService

from .conftest import SECRETS

REPORT = "/v1/reports/equity-research"
BODY = REQUEST.model_dump(mode="json")
ACCESS = {"X-Demo-Access": SECRETS[1]}


def forbidden_factory():
    raise AssertionError("unauthorized or operational requests must not construct providers")


def test_production_serves_root_assets_liveness_readiness_version_and_preserves_api(
    production_env, compiled_frontend
):
    app = create_production_app(
        deployment_config=production_env,
        frontend_dir=compiled_frontend,
        agent_factory=forbidden_factory,
        tools_factory=forbidden_factory,
    )
    with TestClient(app) as client:
        for path in ("/", "/assets/test.js", "/assets/test.css", "/health", "/ready", "/version"):
            response = client.get(path)
            assert response.status_code == 200
            assert UUID(response.headers["X-Request-ID"]).version == 4
            assert all(secret not in response.text for secret in SECRETS)
        assert client.get("/health").json() == {"status": "ok", "service": "financial-research-fde"}
        assert client.get("/ready").json() == {
            "status": "ready",
            "environment": "production",
            "codes": [],
        }
        assert client.get("/version").json()["commit"] == production_env.commit
        assert client.get("/v1/not-real").status_code == 404
        assert client.get("/not-a-client-route").status_code == 404
        assert client.get("/assets/%2e%2e/.env").status_code == 404
        production_schema = client.get("/openapi.json").json()
    base_schema = create_app().openapi()
    assert set(production_schema["paths"]) == set(base_schema["paths"]) | {"/ready", "/version"}
    for path in base_schema["paths"]:
        assert production_schema["paths"][path] == base_schema["paths"][path]
    for name, definition in base_schema["components"]["schemas"].items():
        assert production_schema["components"]["schemas"][name] == definition


@pytest.mark.parametrize(
    "name",
    [
        "OPENAI_API_KEY",
        "OPENAI_MODEL",
        "OPENAI_TIMEOUT_SECONDS",
        "SEC_USER_AGENT",
        "DEMO_ACCESS_TOKEN",
    ],
)
def test_missing_production_configuration_fails_readiness_without_secret_values(
    production_env, compiled_frontend, monkeypatch, name
):
    monkeypatch.delenv(name)
    app = create_production_app(
        deployment_config=DeploymentConfig.from_env(),
        frontend_dir=compiled_frontend,
        agent_factory=forbidden_factory,
    )
    with TestClient(app) as client:
        response = client.get("/ready")
        assert client.get("/health").status_code == 200
    assert response.status_code == 503 and response.json()["status"] == "not_ready"
    assert all(secret not in response.text for secret in SECRETS)


@pytest.mark.parametrize("timeout", ["", "0", "-1", "NaN", "Infinity", "invalid"])
def test_invalid_timeout_is_not_ready(production_env, compiled_frontend, monkeypatch, timeout):
    monkeypatch.setenv("OPENAI_TIMEOUT_SECONDS", timeout)
    with TestClient(create_production_app(frontend_dir=compiled_frontend)) as client:
        response = client.get("/ready")
    assert response.status_code == 503
    assert "OPENAI_TIMEOUT_UNAVAILABLE" in response.json()["codes"]


@pytest.mark.parametrize("missing", ["index.html", "assets/test.js", "assets/test.css"])
def test_missing_compiled_asset_cannot_be_reported_ready(
    production_env, compiled_frontend, missing
):
    (compiled_frontend / missing).unlink()
    with TestClient(create_production_app(frontend_dir=compiled_frontend)) as client:
        assert client.get("/ready").status_code == 503
        assert client.get("/").status_code == 503
        assert client.get("/health").status_code == 200


def test_app_initialization_and_missing_dist_are_visible_readiness_failures(
    production_env, tmp_path
):
    app = create_production_app(frontend_dir=tmp_path / "missing")
    app.state.initialized = False
    with TestClient(app) as client:
        response = client.get("/ready")
    assert response.status_code == 503
    assert set(response.json()["codes"]) == {"APP_NOT_INITIALIZED", "FRONTEND_UNAVAILABLE"}
    assert str(tmp_path) not in response.text


@pytest.mark.parametrize("environment", ["development", "test"])
def test_development_and_test_modes_do_not_require_demo_access(
    production_env, compiled_frontend, report_agent_factory, monkeypatch, environment
):
    monkeypatch.setenv("APP_ENV", environment)
    monkeypatch.delenv("DEMO_ACCESS_TOKEN")
    app = create_production_app(
        frontend_dir=compiled_frontend, agent_factory=lambda: report_agent_factory()[0]
    )
    with TestClient(app) as client:
        assert client.get("/ready").status_code == 200
        response = client.post(REPORT, json=BODY)
    assert response.status_code == 200
    assert response.json()["report"]["status"] == "COMPLETED_WITH_WARNINGS"


@pytest.mark.parametrize(
    "path", [REPORT, "/v1/agent/research", "/v1/research/company-snapshot", "/v1/research/quality"]
)
@pytest.mark.parametrize("headers", [{}, {"X-Demo-Access": "wrong"}])
def test_all_public_research_paths_refuse_invalid_access_before_body_or_factories(
    production_env, compiled_frontend, path, headers, caplog
):
    app = create_production_app(
        frontend_dir=compiled_frontend,
        agent_factory=forbidden_factory,
        tools_factory=forbidden_factory,
    )
    with TestClient(app) as client, caplog.at_level(logging.INFO):
        response = client.post(path, content="not valid JSON", headers=headers)
    assert response.status_code == 401
    assert response.json()["error_code"] == "DEMO_ACCESS_REQUIRED"
    assert response.json()["request_id"] == response.headers["X-Request-ID"]
    assert all(secret not in response.text and secret not in caplog.text for secret in SECRETS)


def test_token_in_url_or_body_does_not_authorize(production_env, compiled_frontend):
    app = create_production_app(frontend_dir=compiled_frontend, agent_factory=forbidden_factory)
    with TestClient(app) as client:
        assert client.post(REPORT, params={"token": SECRETS[1]}, json=BODY).status_code == 401
        assert client.post(REPORT, json={**BODY, "demo_access": SECRETS[1]}).status_code == 401


def test_authorized_production_report_keeps_semantics_and_remains_stateless(
    production_env, compiled_frontend, report_agent_factory, tmp_path, monkeypatch, caplog
):
    monkeypatch.chdir(tmp_path)
    app = create_production_app(
        frontend_dir=compiled_frontend, agent_factory=lambda: report_agent_factory()[0]
    )
    with TestClient(app) as client, caplog.at_level(logging.INFO):
        response = client.post(REPORT, json=BODY, headers=ACCESS)
        invalid = client.post(REPORT, json={**BODY, "demo_access": SECRETS[1]}, headers=ACCESS)
    assert response.status_code == 200 and invalid.status_code == 422
    result = response.json()
    assert result["manifest_summary"]["planner_call_count"] == 0
    assert result["manifest_summary"]["synthesis_call_count"] == 1
    assert result["report"]["status"] == "COMPLETED_WITH_WARNINGS"
    assert result["report"]["report_version"] == "research-report-v1"
    assert not (tmp_path / "artifacts").exists()
    completed = next(
        record for record in caplog.records if getattr(record, "event", "") == "report_completed"
    )
    assert completed.request_id == response.headers["X-Request-ID"]
    assert completed.report_id == result["report"]["report_id"]
    assert completed.run_id == result["report"]["run_id"]
    assert all(secret not in response.text and secret not in caplog.text for secret in SECRETS)


def test_concurrent_report_and_agent_are_refused_while_operations_stay_available(
    production_env, compiled_frontend, report_agent_factory, monkeypatch
):
    entered, release = Event(), Event()
    original = ReportWorkflowService.run

    def held(service, body):
        entered.set()
        assert release.wait(10)
        return original(service, body)

    monkeypatch.setattr(ReportWorkflowService, "run", held)
    app = create_production_app(
        frontend_dir=compiled_frontend, agent_factory=lambda: report_agent_factory()[0]
    )
    with TestClient(app) as client, ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(client.post, REPORT, json=BODY, headers=ACCESS)
        try:
            assert entered.wait(5)
            for path in (REPORT, "/v1/agent/research"):
                response = client.post(path, json=BODY, headers=ACCESS)
                assert response.status_code == 429 and response.json()["error_code"] == "DEMO_BUSY"
            for path in ("/health", "/ready", "/"):
                assert client.get(path).status_code == 200
        finally:
            release.set()
        assert first.result(timeout=5).status_code == 200
        assert client.post(REPORT, json=BODY, headers=ACCESS).status_code == 200


def test_failed_research_releases_slot_and_retains_sanitized_error(
    production_env, compiled_frontend, report_agent_factory, monkeypatch
):
    original = ReportWorkflowService.run
    calls = 0

    def fail_once(service, body):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ValueError(SECRETS[0] + SECRETS[1])
        return original(service, body)

    monkeypatch.setattr(ReportWorkflowService, "run", fail_once)
    app = create_production_app(
        frontend_dir=compiled_frontend, agent_factory=lambda: report_agent_factory()[0]
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        failed = client.post(REPORT, json=BODY, headers=ACCESS)
        assert failed.status_code == 500 and all(secret not in failed.text for secret in SECRETS)
        assert not app.state.research_guard.busy
        assert client.post(REPORT, json=BODY, headers=ACCESS).status_code == 200


def test_request_log_correlation_and_unknown_paths_are_safe(
    production_env, compiled_frontend, caplog
):
    app = create_production_app(frontend_dir=compiled_frontend)
    with TestClient(app) as client, caplog.at_level(logging.INFO):
        response = client.get("/health", headers={"X-Request-ID": SECRETS[0], **ACCESS})
        client.get("/" + SECRETS[1], params={"secret": SECRETS[0]}, headers=ACCESS)
    logs = [record for record in caplog.records if getattr(record, "event", "") == "http_request"]
    assert logs[0].request_id == response.headers["X-Request-ID"]
    assert logs[0].method == "GET" and logs[0].path == "/health"
    assert logs[0].status_code == 200 and logs[0].duration_ms >= 0
    assert logs[1].path == "unmatched"
    assert all(
        secret not in OperationalFormatter().format(record)
        for secret in SECRETS
        for record in caplog.records
    )
    serialized = json.loads(OperationalFormatter().format(logs[0]))
    assert serialized["request_id"] == response.headers["X-Request-ID"]
    assert serialized["timestamp"] and serialized["level"] == "INFO"
