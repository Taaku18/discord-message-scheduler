"""
help.py

Implements the "help" command.
"""

from __future__ import annotations

import itertools
from typing import TYPE_CHECKING, Sequence, Any, Optional, Mapping, List

import discord
from discord.ext import commands

from .env import PREFIX, COLOUR

if TYPE_CHECKING:
    # noinspection PyProtectedMember
    from discord.ext.commands.help import Command, Cog  # type: ignore[reportPrivateImportUsage,reportMissingTypeStubs]
    from .bot import Bot


class HelpCmd(commands.DefaultHelpCommand):
    """A custom help command using embeds."""

    def __init__(self) -> None:
        kwargs = {
            "paginator": commands.Paginator(prefix=None, suffix=None),  # no prefix/suffix since we're using embeds
            "dm_help": None,  # length <1000 guild, >1000 in dm
            "dm_help_threshold": 1000,
            "commands_heading": "**Additional Commands:**",
            "command_attrs": {"hidden": True},  # don't show help command in help
        }
        super().__init__(**kwargs)

    def get_ending_note(self) -> str:
        """
        Overrides parent get_ending_note(), adds `` around command.
        """
        command_name = self.invoked_with
        return (
            f"Type `{PREFIX}{command_name} command` for more info on a command.\n"
            f"You can also type `{PREFIX}{command_name} category` for more info on a category."
        )

    # noinspection PyShadowingNames
    def add_indented_commands(
        self, commands: Sequence[Command[Any, ..., Any]], /, *, heading: str, max_size: Optional[int] = None
    ) -> None:
        """
        Overrides parent add_indented_commands(), adds `` around command name.
        """
        if not commands:
            return

        self.paginator.add_line(heading)
        max_size = max_size or self.get_max_size(commands)

        # noinspection PyProtectedMember
        get_width = discord.utils._string_width  # type: ignore  # dpy type issue
        for command in commands:
            name = f"`{command.qualified_name}`"
            width = max_size - (get_width(name) - len(name))
            entry = f'{self.indent * " "}{name:<{width}} {command.short_doc}'
            self.paginator.add_line(self.shorten_text(entry))

    async def send_pages(self) -> None:
        """
        A custom send_pages() that uses embeds.
        """
        destination = self.get_destination()
        total_pages = len(self.paginator.pages)

        # If the user sends help in guild but bot responds in DM, tells them to check DM
        if isinstance(destination, discord.User | discord.Member | discord.DMChannel) and not isinstance(
            self.context.channel, discord.DMChannel
        ):
            embed = discord.Embed(description="Check your DM.", colour=COLOUR)
            await self.context.channel.send(embed=embed)

        bot: Bot = self.context.bot  # type: ignore[reportAssignmentType]

        for i, page in enumerate(self.paginator.pages, start=1):
            embed = discord.Embed(description=page, colour=COLOUR)
            footer = f"Bot version: {bot.version}"
            if total_pages > 1:  # if more than 1 page, add a page no. footer
                footer += f" · Page {i} of {total_pages}"
            embed.set_footer(text=footer)
            await destination.send(embed=embed)

    async def send_bot_help(self, mapping: Mapping[Optional[Cog], List[Command[Any, ..., Any]]], /) -> None:
        """
        Overrides parent send_bot_help(), adds **** around category name.
        """
        ctx = self.context
        bot = ctx.bot

        if bot.description:
            # <description> portion
            self.paginator.add_line(bot.description, empty=True)

        no_category = f"\u200b{self.no_category}:"

        # noinspection PyShadowingNames
        def get_category(command, *, no_category=no_category):  # type: ignore  # dpy type issue
            cog = command.cog  # type: ignore  # dpy type issue
            return (
                "**"
                + (cog.qualified_name + ":" if cog is not None else no_category)  # type: ignore  # dpy type issue
                + "**"
            )  # type: ignore  # dpy type issue

        filtered = await self.filter_commands(
            bot.commands, sort=True, key=get_category  # type: ignore  # dpy type issue
        )
        max_size = self.get_max_size(filtered)
        to_iterate = itertools.groupby(  # type: ignore  # dpy type issue
            filtered, key=get_category  # type: ignore  # dpy type issue
        )

        # Now we can add the commands to the page.
        # noinspection PyShadowingNames
        for category, commands in to_iterate:  # type: ignore  # dpy type issue
            # noinspection PyShadowingNames
            commands = sorted(commands, key=lambda c: c.name) if self.sort_commands else list(commands)
            self.add_indented_commands(
                commands, heading=category, max_size=max_size  # type: ignore  # dpy type issue
            )

        note = self.get_ending_note()
        if note:
            self.paginator.add_line()
            self.paginator.add_line(note)

        await self.send_pages()

    async def send_error_message(self, error: str, /) -> None:
        """
        Uses embeds for send_error_message().
        """
        destination = self.get_destination()
        embed = discord.Embed(description=error, colour=COLOUR)
        await destination.send(embed=embed)

    def get_command_signature(self, command: Command[Any, ..., Any], /) -> str:
        """
        Overrides parent get_ending_note(), adds `` around command.
        """
        parent: Optional[Group[Any, ..., Any]] = command.parent  # type: ignore # the parent will be a Group
        entries = []
        while parent is not None:
            if not parent.signature or parent.invoke_without_command:  # type: ignore  # dpy type issue
                entries.append(parent.name)  # type: ignore  # dpy type issue
            else:
                entries.append(parent.name + " " + parent.signature)  # type: ignore  # dpy type issue
            parent = parent.parent  # type: ignore  # dpy type issue
        parent_sig = " ".join(reversed(entries))  # type: ignore  # dpy type issue

        if len(command.aliases) > 0:
            aliases = "|".join(command.aliases)
            fmt = f"[{command.name}|{aliases}]"
            if parent_sig:
                fmt = parent_sig + " " + fmt
            alias = fmt
        else:
            alias = command.name if not parent_sig else parent_sig + " " + command.name

        return "``" + f"{PREFIX}{alias} {command.signature}".strip() + "``"

    def add_command_formatting(self, command: Command[Any, ..., Any], /) -> None:
        """
        A slight modification to the parent add_command_formatting().
        """
        if command.description:
            self.paginator.add_line(command.description, empty=True)

        signature = self.get_command_signature(command)
        self.paginator.add_line("**Usage:**")
        self.paginator.add_line(signature, empty=True)

        if command.help:
            try:
                self.paginator.add_line(command.help, empty=True)
            except RuntimeError:
                for line in command.help.splitlines():
                    self.paginator.add_line(line)
                self.paginator.add_line()

        if self.show_parameter_descriptions:
            self.add_command_arguments(command)  # TODO: Need to inherit this method from parent
