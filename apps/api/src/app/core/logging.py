"""Logging setup.

uvicorn only configures its own loggers, so without this our `app.*` loggers
stay silent in `docker compose logs api`. Called once from create_app(); the
taskiq worker CLI configures logging itself.
"""

import logging


def configure_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(level=level)
