"""Offline infrastructure smoke using fake credentials; never authorize research execution."""

import argparse
import json
import re
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

FAKE_CONFIG = {
    "APP_ENV": "production",
    "PORT": "10000",
    "OPENAI_API_KEY": "__OPENAI_SECRET_SENTINEL__",
    "OPENAI_MODEL": "synthetic-model",
    "OPENAI_TIMEOUT_SECONDS": "120",
    "SEC_USER_AGENT": "__SEC_SENTINEL__",
    "DEMO_ACCESS_TOKEN": "__DEMO_ACCESS_SENTINEL__",
    "LOG_LEVEL": "INFO",
    "MARKET_DATA_PROVIDER": "tiingo",
    "TIINGO_API_TOKEN": "__CI_FAKE_TIINGO_TOKEN__",
    "RENDER_GIT_COMMIT": "1234567890abcdef1234567890abcdef12345678",
}
SENTINELS = [
    FAKE_CONFIG[key]
    for key in ("OPENAI_API_KEY", "SEC_USER_AGENT", "DEMO_ACCESS_TOKEN", "TIINGO_API_TOKEN")
]
SENTINELS.append("__TIINGO_SECRET_SENTINEL__")
REPORT_BODY = json.dumps(
    {"ticker": "NVDA", "as_of_date": "2026-06-30", "response_language": "ENGLISH"}
).encode()
RESEARCH_PATHS = {"/v1/reports/equity-research", "/v1/agent/research", "/v1/research/quality"}


def docker(*args: str) -> str:
    result = subprocess.run(["docker", *args], capture_output=True, text=True, check=False)
    if result.returncode:
        # Docker output can contain configuration; report the operation without its contents.
        raise RuntimeError(f"Docker {args[0]} failed; inspect the local Docker installation.")
    return result.stdout.strip()


def fetch(base: str, path: str, *, code: str | None = None) -> tuple[int, bytes, dict[str, str]]:
    headers = {"Content-Type": "application/json"}
    if code is not None:
        if code == FAKE_CONFIG["DEMO_ACCESS_TOKEN"]:
            raise ValueError("Infrastructure smoke must never send valid research authorization.")
        headers["X-Demo-Access"] = code
    request = Request(
        base + path,
        data=REPORT_BODY if path in RESEARCH_PATHS else None,
        headers=headers,
        method="POST" if path.startswith("/v1/") else "GET",
    )
    try:
        with urlopen(request, timeout=5) as response:
            return response.status, response.read(), dict(response.headers)
    except HTTPError as response:
        return response.code, response.read(), dict(response.headers)


def wait_for_health(base: str, timeout_seconds: float = 45) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            if fetch(base, "/health")[0] == 200:
                return
        except (OSError, URLError):
            pass
        time.sleep(0.5)
    raise RuntimeError("Container did not become live before the bounded startup deadline.")


def verify_http(base: str, *, ready: bool) -> None:
    for path, expected in (
        ("/health", 200),
        ("/ready", 200 if ready else 503),
        ("/", 200),
        ("/version", 200),
    ):
        status, content, headers = fetch(base, path)
        if status != expected or not any(key.lower() == "x-request-id" for key in headers):
            raise RuntimeError(f"Container HTTP smoke failed for {path}.")
        if any(value.encode() in content for value in SENTINELS):
            raise RuntimeError("Container HTTP response leaked a sentinel; content redacted.")
        if path == "/":
            assets = re.findall(rb'(?:src|href)="(/assets/[^"<>]+)"', content)
            if not assets:
                raise RuntimeError("Compiled frontend asset references are missing.")
            for asset in assets:
                asset_status, asset_body, _ = fetch(base, asset.decode())
                if asset_status != 200 or any(value.encode() in asset_body for value in SENTINELS):
                    raise RuntimeError("Static asset smoke or sentinel scan failed.")
    if ready:
        for path in ("/v1/reports/equity-research", "/v1/agent/research", "/v1/research/quality"):
            for code in (None, "wrong-demo-code"):
                status, content, _ = fetch(base, path, code=code)
                if status != 401 or any(value.encode() in content for value in SENTINELS):
                    raise RuntimeError("Production access refusal failed.")
        if fetch(base, "/v1/not-real")[0] != 404:
            raise RuntimeError("Unknown API path was swallowed by frontend routing.")


IMAGE_CHECK = """
import importlib.util, os, pathlib, shutil
root = pathlib.Path('/app')
assert os.getuid() != 0 and not os.access(root, os.W_OK)
assert shutil.which('node') is None
assert importlib.util.find_spec('pytest') is None
for name in ('.env', '.venv', '.git', 'artifacts', 'frontend/node_modules', 'frontend/src'):
    assert not (root / name).exists()
assert not list(root.rglob('.env*'))
for file in root.rglob('*'):
    if file.is_file():
        data = file.read_bytes()
        names = ('OPENAI_API_KEY', 'SEC_USER_AGENT', 'DEMO_ACCESS_TOKEN', 'TIINGO_API_TOKEN')
        assert all(os.environ[name].encode() not in data for name in names)
        assert b'__TIINGO_SECRET_SENTINEL__' not in data
print('Runtime filesystem, user and secret boundary passed.')
"""


def run_container(image: str, *, missing: str | None = None) -> None:
    config = {key: value for key, value in FAKE_CONFIG.items() if key != missing}
    arguments = ["run", "--detach", "--rm", "--publish", "127.0.0.1::10000"]
    for key, value in config.items():
        arguments.extend(("--env", f"{key}={value}"))
    container = docker(*arguments, image)
    try:
        binding = docker("port", container, "10000/tcp")
        if not re.fullmatch(r"127\.0\.0\.1:[0-9]+", binding):
            raise RuntimeError("Unexpected container port mapping.")
        base = "http://" + binding
        wait_for_health(base)
        verify_http(base, ready=missing is None)
        if missing is None:
            print(docker("exec", container, "python", "-c", IMAGE_CHECK))
        logs = docker("logs", container)
        if any(secret in logs for secret in SENTINELS):
            raise RuntimeError("Container logs leaked a sentinel; content redacted.")
        events = [json.loads(line) for line in logs.splitlines() if line.startswith("{")]
        requests = [event for event in events if event.get("event") == "http_request"]
        if not requests or any(
            not {"request_id", "method", "path", "status_code", "duration_ms"} <= event.keys()
            for event in requests
        ):
            raise RuntimeError("Structured request logs are missing required fields.")
        label = "complete config" if missing is None else "missing " + missing
        print(f"Container smoke passed: {label}.")
    except Exception:
        logs = docker("logs", container)
        for secret in SENTINELS:
            logs = logs.replace(secret, "[REDACTED]")
        print(logs)
        raise
    finally:
        docker("stop", container)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="financial-research-fde:local")
    arguments = parser.parse_args()
    run_container(arguments.image)
    for missing in ("DEMO_ACCESS_TOKEN", "OPENAI_API_KEY", "TIINGO_API_TOKEN"):
        run_container(arguments.image, missing=missing)


if __name__ == "__main__":
    main()
