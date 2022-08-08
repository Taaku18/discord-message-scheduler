"""
cog.py

A subclass of discord.py's command ext Cog.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from discord.ext.commands import Cog as _Cog

if TYPE_CHECKING:
    # noinspection PyProtectedMember
    from discord.ext.commands.cog import Context, BotT  # type: ignore[reportPrivateImportUsage]

__all__ = ["Cog"]

logger = logging.getLogger(__name__)


class Cog(_Cog):
    async def cog_before_invoke(self, ctx: Context[BotT]) -> None:
        logger.debug("User %s is running the %s command.", ctx.author, ctx.command)
        await super().cog_before_invoke(ctx)
