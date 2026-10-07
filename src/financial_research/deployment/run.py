"""Single-worker production launch; port is validated before binding."""

import uvicorn

from financial_research.deployment.app import create_production_app
from financial_research.deployment.config import DeploymentConfig
from financial_research.deployment.logging import configure_logging


def main() -> None:
    config = DeploymentConfig.from_env()
    configure_logging(config.log_level)
    uvicorn.run(
        create_production_app(deployment_config=config),
        host="0.0.0.0",
        port=config.port,
        workers=1,
        access_log=False,
        log_config=None,
    )


if __name__ == "__main__":
    main()
