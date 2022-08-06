"""
logging.py

Configure the logging module for the bot and discord.py internals.
"""
from __future__ import annotations

import logging

from rich.logging import RichHandler
from rich.text import Text

import discord

from .env import DEBUG_MODE


# Configure root logging
formatter = logging.Formatter("[%(levelname)s] %(message)s")
handler = RichHandler(
    show_level=False,
    rich_tracebacks=True,
    tracebacks_show_locals=True,
    log_time_format=lambda dt: Text(dt.strftime("%X,%f")[:-3]),
    tracebacks_suppress=[discord],
)
handler.setFormatter(formatter)
logging.Logger.root.addHandler(handler)
# Set debug logging if debug mode is on
logging.Logger.root.setLevel(logging.DEBUG if DEBUG_MODE else logging.INFO)

# Configure Discord logging
logger_dc1 = logging.getLogger("discord")
logger_dc1.setLevel(logging.INFO)

logger_dc2 = logging.getLogger("discord.http")
logger_dc2.setLevel(logging.INFO)
