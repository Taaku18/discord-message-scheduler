"""
env.py

Parse environment variables from .env file.
"""
from __future__ import annotations

import logging
import os
from distutils.util import strtobool

from dotenv import load_dotenv

from discord import Colour

__all__ = ["DEBUG_MODE", "TOKEN", "PREFIX", "COLOUR", "SCHEDULER_DATABASE_PATH", "DEBUG_GUILDS"]

logger = logging.getLogger(__name__)

# Load envs
load_dotenv()

DEBUG_MODE = strtobool(os.getenv("DEBUG_MODE", "off"))
if DEBUG_MODE:
    logger.warning("[red]Debug mode is activated.[/red]", extra={"markup": True})

TOKEN = os.getenv("TOKEN")
if not TOKEN:
    logger.critical("[bold red]TOKEN not set.[/bold red]", extra={"markup": True})
    exit(1)

PREFIX = os.getenv("PREFIX", "=")

# Sets the embed colour, 0x749DA1 is teal
COLOUR = Colour(0x749DA1)

SCHEDULER_DATABASE_NAME = "schedule.sqlite"
# Path is ../DATABASE_NAME
SCHEDULER_DATABASE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), SCHEDULER_DATABASE_NAME
)

# Configure debug servers
if "DEBUG_GUILDS" in os.environ:
    if "DEBUG_GUILD" in os.environ:
        logger.critical(
            "[bold red]DEBUG_GUILD and DEBUG_GUILDS cannot be both set.[/bold red]", extra={"markup": True}
        )
        exit(1)
    try:
        DEBUG_GUILDS = list(map(int, os.environ["DEBUG_GUILDS"].split(",")))
    except ValueError:
        logger.critical(
            "[bold red]DEBUG_GUILDS must be a comma-separated list of guild IDs.[/bold red]",
            extra={"markup": True},
        )
        exit(1)
elif "DEBUG_GUILD" in os.environ:
    try:
        DEBUG_GUILDS = [int(os.environ["DEBUG_GUILD"])]
    except ValueError:
        logger.critical(
            "[bold red]DEBUG_GUILD must be a guild ID. "
            "Use DEBUG_GUILDS if you have multiple debug servers.[/bold red]",
            extra={"markup": True},
        )
        exit(1)
else:
    DEBUG_GUILDS = []
