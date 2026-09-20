"""
Module: app.logging
Path: app/logging.py
Description: Application logging configuration and structured event helpers.
"""

import logging


def get_logger(name: str) -> logging.Logger:
    """Return a configured application logger."""
    return logging.getLogger(name)
