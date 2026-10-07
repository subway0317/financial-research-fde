import importlib.util
from pathlib import Path
from urllib.error import URLError

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def smoke():
    spec = importlib.util.spec_from_file_location(
        "container_smoke", ROOT / "scripts/container_smoke.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_container_build_context_and_runtime_boundaries_are_declared():
    ignored = (ROOT / ".dockerignore").read_text().splitlines()
    assert {
        ".env",
        ".env.*",
        ".venv",
        ".git",
        "artifacts",
        "frontend/node_modules",
        "frontend/dist",
    } <= set(ignored)
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert "FROM node:24-bookworm-slim AS frontend-build" in dockerfile
    assert "FROM python:3.14-slim-bookworm AS runtime" in dockerfile
    runtime = dockerfile.split("AS runtime", 1)[1]
    assert "USER 10001:10001" in runtime
    assert "pip install --no-cache-dir ." in runtime
    assert 'CMD ["python", "-m", "financial_research.deployment.run"]' in runtime
    assert "COPY --from=frontend-build /build/frontend/dist/" in runtime
    assert "node_modules" not in runtime and "[dev]" not in runtime
    assert all(
        key not in dockerfile for key in ("OPENAI_API_KEY", "SEC_USER_AGENT", "DEMO_ACCESS_TOKEN")
    )


def test_render_blueprint_and_canonical_ci_remain_bounded():
    blueprint = (ROOT / "render.yaml").read_text()
    for required in (
        "runtime: docker",
        "numInstances: 1",
        "healthCheckPath: /ready",
        "autoDeployTrigger: checksPass",
    ):
        assert required in blueprint
    for secret in ("OPENAI_API_KEY", "OPENAI_MODEL", "SEC_USER_AGENT", "DEMO_ACCESS_TOKEN"):
        assert f"- key: {secret}\n        sync: false" in blueprint
    workflow = (ROOT / ".github/workflows/ci.yml").read_text()
    assert 'python-version: ["3.12", "3.14"]' in workflow
    assert 'python-version: "3.14"' in workflow.split("  frontend:", 1)[1]
    assert "docker build" in workflow and "scripts/container_smoke.py" in workflow


def test_infrastructure_smoke_cannot_send_valid_research_authorization(smoke):
    with pytest.raises(ValueError, match="never send valid research authorization"):
        smoke.fetch(
            "http://127.0.0.1",
            "/v1/reports/equity-research",
            code=smoke.FAKE_CONFIG["DEMO_ACCESS_TOKEN"],
        )


def test_container_cleanup_even_when_smoke_fails(smoke, monkeypatch):
    calls = []

    def docker(*args):
        calls.append(args)
        return {"run": "synthetic-container", "port": "127.0.0.1:10000", "logs": ""}.get(
            args[0], ""
        )

    def failed(*args):
        raise RuntimeError("synthetic boot failure")

    monkeypatch.setattr(smoke, "docker", docker)
    monkeypatch.setattr(smoke, "wait_for_health", failed)
    with pytest.raises(RuntimeError, match="synthetic boot failure"):
        smoke.run_container("synthetic-image")
    assert calls[-1] == ("stop", "synthetic-container")


def test_startup_retry_is_bounded_without_blind_long_sleep(smoke, monkeypatch):
    clock = iter([0, 0, 1, 2])
    monkeypatch.setattr(smoke.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(smoke.time, "sleep", lambda duration: None)
    monkeypatch.setattr(smoke, "fetch", lambda *args: (_ for _ in ()).throw(URLError("offline")))
    with pytest.raises(RuntimeError, match="bounded startup deadline"):
        smoke.wait_for_health("http://127.0.0.1", timeout_seconds=2)
