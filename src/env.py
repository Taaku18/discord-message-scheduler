"""
env.py

Parse environment variables from .env file.
"""

from __future__ import annotations

import logging
import os
import time

from dotenv import load_dotenv

from discord import Colour

from .util import strtobool

__all__ = [
    "DEBUG_MODE",
    "TOKEN",
    "PREFIX",
    "COLOUR",
    "SCHEDULER_DATABASE_PATH",
    "PYPROJECT_TOML_PATH",
    "DEBUG_GUILDS",
    "SYNC_SLASH_COMMANDS",
    "DEFAULT_TIMEZONE",
    "TIME_LANG",
]

logger = logging.getLogger(__name__)

# Load envs
load_dotenv()

DEBUG_MODE = strtobool(os.getenv("DEBUG_MODE", "off"))
if DEBUG_MODE:
    logger.warning("[red]Debug mode is activated.[/red]", extra={"markup": True})

try:
    TOKEN = os.environ["TOKEN"]
except KeyError:
    logger.critical("[bold red]TOKEN not set.[/bold red]", extra={"markup": True})
    exit(1)

PREFIX = os.getenv("PREFIX", "=")

# Sets the embed colour, 0x749DA1 is teal
COLOUR = Colour(0x749DA1)

# Default is ../data/schedule.db
SCHEDULER_DATABASE_NAME = "schedule.db"
SCHEDULER_DATABASE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", SCHEDULER_DATABASE_NAME
)

PYPROJECT_TOML_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pyproject.toml")

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
        DEBUG_GUILDS: list[int] = [int(os.environ["DEBUG_GUILD"])]  # type: ignore[reportConstantRedefinition]
    except ValueError:
        logger.critical(
            "[bold red]DEBUG_GUILD must be a guild ID. "
            "Use DEBUG_GUILDS if you have multiple debug servers.[/bold red]",
            extra={"markup": True},
        )
        exit(1)
else:
    DEBUG_GUILDS = []  # type: ignore[reportConstantRedefinition]

SYNC_SLASH_COMMANDS = strtobool(os.getenv("SYNC_SLASH_COMMANDS", "on"))

# Get timezone env
original_tz = os.getenv("TZ")
_DEFAULT_TIMEZONE = "America/Vancouver"
DEFAULT_TIMEZONE = os.getenv("DEFAULT_TIMEZONE", original_tz or _DEFAULT_TIMEZONE)

try:
    # noinspection PyUnresolvedReferences
    from dateutil.tz import gettz

    # Set the TZ env to DEFAULT_TIMEZONE
    if gettz(DEFAULT_TIMEZONE) is not None and os.name != "nt":  # time.tzset() only support Unix systems
        os.environ["TZ"] = DEFAULT_TIMEZONE
        try:
            time.tzset()
        except Exception as e:
            logger.warning("Failed to set timezone.", exc_info=e)
            if original_tz is not None:  # reverts timezone
                os.environ["TZ"] = original_tz
except ModuleNotFoundError:
    pass  # dateutil is not used

try:
    # noinspection PyUnresolvedReferences
    import dateparser

    try:
        dateparser.parse(
            "now",
            languages=["en"],
            settings={
                "TIMEZONE": DEFAULT_TIMEZONE,
                "DEFAULT_LANGUAGES": ["en"],
            },  # type: ignore[reportArgumentType]
        )  # test the timezone by attempting to get "now"
    except Exception as e:
        logger.warning("Timezone may be invalid, reverting default timezone to %s.", _DEFAULT_TIMEZONE, exc_info=e)
        DEFAULT_TIMEZONE = _DEFAULT_TIMEZONE  # type: ignore[reportConstantRedefinition]
except ModuleNotFoundError:
    pass  # dateparser is not used


TIME_LANG = ["en"]
