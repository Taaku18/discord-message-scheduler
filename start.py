"""
start.py

Entrypoint for the bot.
"""
from __future__ import annotations

import asyncio
import logging
import sys

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

    try:
        try:
            import uvloop
        except ModuleNotFoundError:
            logger.info("uvloop not installed.")
            asyncio.run(main())
        else:
            # Start event loop
            if sys.version_info >= (3, 11):
                # noinspection PyUnresolvedReferences
                with asyncio.Runner(loop_factory=uvloop.new_event_loop) as runner:
                    runner.run(main())
            else:
                uvloop.install()
                asyncio.run(main())
    except KeyboardInterrupt:
        pass
    logger.info("[red]Bot has stopped.[/red]", extra={"markup": True})
