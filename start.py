"""
start.py

Entrypoint for the bot.
"""
from __future__ import annotations

__version__ = "1.0"

import asyncio
import logging
import sys

import uvloop

from src.bot import Bot

logger = logging.getLogger(__name__)


if __name__ == "__main__":
    bot = Bot()

    async def main() -> None:
        """
        The main runner for the bot.
        """
        async with bot:
            await bot.load_extension("cogs.scheduler")
            await bot.load_extension("cogs.general")
            logger.info("[green]Starting bot.[/green]", extra={"markup": True})
            await bot.start()

    # Start event loop
    try:
        if sys.version_info >= (3, 11):
            with asyncio.Runner(loop_factory=uvloop.new_event_loop) as runner:
                runner.run(main())
        else:
            uvloop.install()
            asyncio.run(main())

    except KeyboardInterrupt:
        pass
    logger.info("[red]Bot has stopped.[/red]", extra={"markup": True})
