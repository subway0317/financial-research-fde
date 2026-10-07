import json

from financial_research.api import openapi
from financial_research.api.app import create_app


def test_schema_export_is_deterministic_and_requires_no_provider_or_secrets(monkeypatch, capsys):
    def forbidden_factory():
        raise AssertionError("schema export must never construct research services")

    for name in ("OPENAI_API_KEY", "OPENAI_MODEL", "OPENAI_TIMEOUT_SECONDS", "SEC_USER_AGENT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(
        openapi,
        "create_app",
        lambda: create_app(tools_factory=forbidden_factory, agent_factory=forbidden_factory),
    )
    openapi.main()
    first = capsys.readouterr().out
    openapi.main()
    second = capsys.readouterr().out
    assert first == second
    assert json.loads(first) == create_app().openapi()


def test_report_openapi_documents_the_existing_safe_error_contract():
    schema = create_app().openapi()
    responses = schema["paths"]["/v1/reports/equity-research"]["post"]["responses"]
    for status in (422, 404, 502, 503, 500):
        assert responses[str(status)]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/ErrorResponse"
        }
    assert set(schema["components"]["schemas"]["ErrorResponse"]["properties"]) == {
        "error_code",
        "message",
        "request_id",
    }
