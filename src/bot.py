"""
bot.py

The main Bot class.
"""
from __future__ import annotations

import logging
from typing import Any

import discord
from discord.ext import commands

from .env import *
from .help import HelpCmd

logger = logging.getLogger(__name__)


class Bot(commands.Bot):
    """
    The main class for the bot.
    """

    def __init__(self) -> None:
        # All intents excepted presence intent
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True

        # Set activity to "listening to [prefix]help"
        activity = discord.Activity(name=f"{PREFIX}help", type=discord.ActivityType.listening)

        super().__init__(
            command_prefix=commands.when_mentioned_or(PREFIX),
            intents=intents,
            activity=activity,
            help_command=HelpCmd(),
        )

    async def start(self, *args: Any, **kwargs: Any) -> None:
        """
        Start the bot using the TOKEN env.
        """
        await super().start(TOKEN, *args, **kwargs)

    async def setup_hook(self) -> None:
        """
        This is called on bot start.
        """

        if SYNC_SLASH_COMMANDS:
            logger.info("Syncing slash commands (this may take a while).")
            if not DEBUG_MODE:
                # Sync global slash commands
                await self.tree.sync()
                logger.info("Slash commands synced.")
            else:
                # Sync debug guilds slash commands
                for guild_id in DEBUG_GUILDS:
                    await self.tree.sync(guild=discord.Object(guild_id))
                    logger.info("Synced app command tree to debug guild %d.", guild_id)
        else:
            logger.info("Slash commands sync skipped.")

    # noinspection PyMethodMayBeStatic
    async def on_ready(self) -> None:
        """
        This is called when the bot is ready.
        """
        logger.info("[bold green]Bot is ready.[/bold green]", extra={"markup": True})
