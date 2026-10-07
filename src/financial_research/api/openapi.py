"""Export canonical OpenAPI to stdout without a server, credentials or provider calls."""

import json

from financial_research.api.app import create_app


def main() -> None:
    print(json.dumps(create_app().openapi(), sort_keys=True, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
