"""Structured JSON logging for the service, uvicorn and libraries."""

import logging
import sys

import structlog

from app import config

_SILENCED = ("uvicorn.access",)


def configure_logging(settings: config.LoggingSettings) -> None:
    """Routes structlog and stdlib logging through one JSON pipeline.

    Context variables bound per request or job (``request_id``, ``job_id``)
    are merged into every line. Access logs are silenced because the request
    middleware logs each request with its status and duration.

    Args:
        settings: Level and output format.
    """
    shared: list[structlog.typing.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]
    renderer: structlog.typing.Processor = (
        structlog.processors.JSONRenderer()
        if settings.json_output
        else structlog.dev.ConsoleRenderer()
    )
    structlog.configure(
        processors=[
            *shared,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.processors.format_exc_info,
                renderer,
            ],
        )
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(settings.level)
    for name in ("uvicorn", "uvicorn.error"):
        logging.getLogger(name).handlers.clear()
        logging.getLogger(name).propagate = True
    for name in _SILENCED:
        logging.getLogger(name).setLevel(logging.WARNING)
