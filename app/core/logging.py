"""Configure application JSON logs and Uvicorn log levels."""

from datetime import datetime, timezone
import json
import logging


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps({
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }, ensure_ascii=False)


def configure_logging(level: str) -> None:
    app_logger = logging.getLogger("app")
    if not any(handler.name == "app-json" for handler in app_logger.handlers):
        handler = logging.StreamHandler()
        handler.name = "app-json"
        handler.setFormatter(JsonFormatter())
        app_logger.addHandler(handler)
    app_logger.propagate = False
    for name in ("app", "uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).setLevel(level)
