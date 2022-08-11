"""
scheduler.py

Scheduler category and commands.
"""
from __future__ import annotations

import asyncio
import heapq
import logging
import re
import warnings
from math import ceil
from secrets import token_hex
from typing import TYPE_CHECKING, NamedTuple, Type, Literal, cast, TypeAlias, Any

import aiosqlite
import arrow
from packaging import version

import discord
from discord.ext import commands

from src.commands import Cog
from src.env import COLOUR, SCHEDULER_DATABASE_PATH, DEBUG_MODE, DEFAULT_TIMEZONE, TIME_LANG

if TYPE_CHECKING:
    from src.bot import Bot


logger = logging.getLogger(__name__)

DB_VERSION = 1
TIME_PARSE_METHOD: Literal["dateparser"] | Literal["dateutil"] = "dateparser"  # options: 'dateutil', 'dateparser'
MessageableGuildChannel: TypeAlias = discord.TextChannel | discord.VoiceChannel | discord.Thread


class SanitizedScheduleEvent(NamedTuple):
    """
    Represents a single scheduled message event after modal sanitization.
    """

    author: discord.Member
    channel: MessageableGuildChannel
    message: str
    time: arrow.Arrow
    repeat: float | None


class ScheduleEvent(NamedTuple):
    """
    Represents a single scheduled message event.
    """

    author: discord.Member
    channel: MessageableGuildChannel
    message: str
    time: arrow.Arrow
    repeat: float | None
    mention: bool

    @classmethod
    def from_sanitized(cls, event: SanitizedScheduleEvent, mention: bool) -> ScheduleEvent:
        """
        Converts a SanitizedScheduleEvent to ScheduleEvent.

        :param event: The sanitized event.
        :param mention: Whether mention is allowed.
        :return: The converted ScheduleEvent.
        """
        return cls(event.author, event.channel, event.message, event.time, event.repeat, mention)

    @classmethod
    def from_saved(
        cls, event: SavedScheduleEvent, author: discord.Member, channel: MessageableGuildChannel
    ) -> ScheduleEvent:
        """
        Converts a SanitizedScheduleEvent to ScheduleEvent by populating additional data.

        :param event: The sanitized event.
        :param author: The author of the event.
        :param channel: The channel of the event.
        :return: The converted ScheduleEvent.
        """
        return cls(
            author,
            channel,
            event.message,
            arrow.get(event.next_event_time),
            float(event.repeat) if event.repeat is not None else None,
            event.mention,
        )


class SavedScheduleEvent(NamedTuple):
    """
    Represents a single scheduled message event in DB format.
    """

    id: int
    message: str
    guild_id: int
    channel_id: int
    author_id: int
    next_event_time: int
    repeat: float | int | None
    canceled: bool
    mention: bool

    @classmethod
    def from_row(cls, row: aiosqlite.Row) -> SavedScheduleEvent:
        """
        Create a SavedScheduleEvent from a SQLite row.

        :param row: The row fetched from the database.
        :return: Created SavedScheduleEvent.
        """
        return cls(*row)

    def do_repeat(self, current_timestamp: int) -> SavedScheduleEvent:
        """
        Do an iteration of repeat.

        :return: New SavedScheduleEvent with updated next_event_time.
        """
        if self.repeat is None:
            raise ValueError("repeat cannot be None to do_repeat().")
        return SavedScheduleEvent(
            self.id,
            self.message,
            self.guild_id,
            self.channel_id,
            self.author_id,
            int(current_timestamp + self.repeat * 60),
            self.repeat,
            self.canceled,
            self.mention,
        )

    def __lt__(self, other: SavedScheduleEvent) -> bool:  # type: ignore[reportIncompatibleMethodOverride]
        """
        Use next_event_time as the comp.
        """
        return self.next_event_time < other.next_event_time


class ScheduleError(ValueError):
    """
    Base class of Scheduling error.
    """

    pass


class TooManyEvents(ScheduleError):
    """
    Base exception for user having too many events.
    """

    def __init__(self, limit: int) -> None:
        self.limit = limit


class TooManyChannelEvents(TooManyEvents):
    """
    The user created too many events in the channel.
    """

    pass


class TooManyGuildEvents(TooManyEvents):
    """
    The user created too many events in the guild.
    """

    pass


class TimeInPast(ScheduleError):
    """
    Raised when scheduler time is in the past.
    """

    def __init__(self, time: arrow.Arrow) -> None:
        self.time = time


class InvalidRepeat(ScheduleError):
    """
    Raised when scheduler repeat is longer than a year or shorter than an hour.
    """

    def __init__(self, reason: str) -> None:
        self.reason = reason


class BadTimezone(ScheduleError):
    """
    Raised the timezone is invalid.
    """

    def __init__(self, timezone: str | None) -> None:
        """
        :param timezone: The invalid timezone, if timezone is None then
                         it means the timezone is supplied at an invalid location.
        """
        self.timezone = timezone


class BadTimeString(ScheduleError):
    """
    Raised when the time cannot be parsed.
    """

    def __init__(self, time: str) -> None:
        self.time = time


if TYPE_CHECKING:  # TODO: find another way to fix type checking
    # Provides a stub for ScheduleModal, this will not run at runtime
    class ScheduleModal(discord.ui.Modal, title="Schedule Creator"):
        message: discord.ui.TextInput[ScheduleModal]
        time: discord.ui.TextInput[ScheduleModal]
        timezone: discord.ui.TextInput[ScheduleModal]
        repeat: discord.ui.TextInput[ScheduleModal]

        def __init__(self, scheduler: Scheduler, channel: MessageableGuildChannel) -> None:
            self.scheduler = scheduler
            self.channel = channel
            super().__init__()

        def sanitize_response(self, interaction: discord.Interaction) -> SanitizedScheduleEvent:
            ...

        @property
        def acceptable_formats(self) -> list[str]:
            return []

        async def on_submit(self, interaction: discord.Interaction) -> None:
            ...


def get_schedule_modal(defaults: ScheduleModal | None = None) -> Type[ScheduleModal]:
    """
    This is a class factory to create ScheduleModal with defaults.

    :param defaults: A ScheduleModal object that will be used to populate default fields.
    :return: A class ScheduleModal with defaults.
    """
    message_default = defaults and defaults.message.value
    time_default = defaults and defaults.time.value
    timezone_default = defaults and defaults.timezone.value or DEFAULT_TIMEZONE
    repeat_default = defaults and defaults.repeat.value or "0"

    # noinspection PyShadowingNames
    class ScheduleModal(discord.ui.Modal, title="Schedule Creator"):
        """
        The scheduling modal to collect info for the schedule.
        """

        message: discord.ui.TextInput[ScheduleModal] = discord.ui.TextInput(
            label="Message",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=1000,
            default=message_default,
        )
        time: discord.ui.TextInput[ScheduleModal] = discord.ui.TextInput(
            label="Scheduled Time (MM/DD/YY HH:MM:SS)", required=True, max_length=100, default=time_default
        )
        timezone: discord.ui.TextInput[ScheduleModal] = discord.ui.TextInput(
            label="Timezone (UTC offset +/-HH:MM)", required=False, max_length=100, default=timezone_default
        )
        repeat: discord.ui.TextInput[ScheduleModal] = discord.ui.TextInput(
            label="Repeat every n minutes (0 to disable, min 60)",
            required=False,
            max_length=10,
            default=repeat_default,
        )

        def __init__(self, scheduler: Scheduler, channel: MessageableGuildChannel) -> None:
            """
            :param scheduler: The Scheduler object.
            :param channel: The MessageableGuildChannel for the scheduled message.
            """
            self.scheduler = scheduler
            self.channel = channel
            super().__init__()

        def sanitize_response(self, interaction: discord.Interaction) -> SanitizedScheduleEvent:
            """
            Sanitize the modal entries and raise appropriate errors.

            :param interaction: The interaction context.
            :raises ParseError: If the time cannot be understood.
            :raises TimeInPast: If the time is in the past.
            :raises UnknownTimezoneWarning: If the timezone is provided in the time.
            :raises InvalidRepeat: If repeat is longer than a year or shorter than an hour.
            :return: The sanitized ScheduleEvent.
            """

            logger.debug("Sanitizing schedule event.")
            if self.time.value is None or self.message.value is None:
                raise ValueError("time and message cannot be None here since they are non-optional.")

            if not isinstance(interaction.user, discord.Member):
                raise ValueError("interaction.user must be a Member (cannot be ran from DM).")

            if TIME_PARSE_METHOD == "dateutil":
                from dateutil import parser as du_parser

                try:
                    # parse the time
                    with warnings.catch_warnings():  # will raise exception is an unknown timezone is detected
                        # noinspection PyUnresolvedReferences
                        warnings.simplefilter(
                            "error", du_parser.UnknownTimezoneWarning  # type: ignore[reportGeneralTypeIssues]
                        )  # exists, but editor is weird
                        naive_time = du_parser.parse(self.time.value)
                except du_parser.UnknownTimezoneWarning as e:  # type: ignore[reportGeneralTypeIssues]
                    raise BadTimezone(None) from e
                except du_parser.ParserError as e:  # fails to parse time
                    raise BadTimeString(self.time.value) from e

                # apply the timezone
                if self.timezone.value:  # if user inputted a timezone
                    try:
                        time = arrow.get(naive_time, self.timezone.value)
                    except arrow.ParserError as e:  # fails to parse timezone
                        logger.debug("Failed to parse timezone.", exc_info=e)
                        raise BadTimezone(self.timezone.value) from e
                else:
                    time = arrow.get(naive_time)  # will use either tz from naive time or UTC
                del du_parser  # remove local variable

            else:  # dateparser method
                import dateparser as dp_parser

                try:
                    naive_time = dp_parser.parse(
                        self.time.value,
                        languages=TIME_LANG,
                        settings={
                            "TIMEZONE": self.timezone.value,
                            "RETURN_AS_TIMEZONE_AWARE": True,
                            "DEFAULT_LANGUAGES": TIME_LANG,
                        },  # type: ignore[reportGeneralTypeIssues]
                    )
                except Exception as e:
                    if e.__class__.__name__ == "UnknownTimeZoneError":  # invalid timezone
                        raise BadTimezone(self.timezone.value) from e
                    raise  # re-raise

                if naive_time is None:
                    raise BadTimeString(self.time.value)
                time = arrow.get(naive_time)
                del dp_parser  # remove local variable

            # check time is in the future
            now = arrow.utcnow()
            if time <= now:
                logger.debug("Time is in the past. Time: %s, now: %s", time, now)
                raise TimeInPast(time)

            if not self.repeat.value:
                repeat = None
            else:
                # check repeat is a number
                try:
                    repeat = round(float(self.repeat.value), 2)
                except ValueError:
                    repeat = None
                else:
                    # verify repeat is < year and > one hour
                    if repeat <= 0:
                        repeat = None
                    elif repeat > 60 * 24 * 365:
                        raise InvalidRepeat("Repeat cannot be longer than a year.")
                    elif repeat < (0.2 if DEBUG_MODE else 60):  # 12 seconds for debug mode, 60 min for production
                        if DEBUG_MODE:
                            raise InvalidRepeat("Repeat cannot be less than 12 seconds (debug mode is active).")
                        else:
                            raise InvalidRepeat("Repeat cannot be less than one hour.")

            return SanitizedScheduleEvent(interaction.user, self.channel, self.message.value, time, repeat)

        @property
        def acceptable_formats(self) -> list[str]:
            """
            :return: A list of acceptable time formats.
            """
            if TIME_PARSE_METHOD == "dateutil":
                return [
                    "- 1/30/2023 3:20am",
                    "- Jan 30 2023 3:20",
                    "- 2023-Jan-30 3h20m",
                    "- January 30th, 2023 at 03:20:00",
                ]
            else:
                return [
                    "- Just date: `2/24/2023` (Month/Day/Year), `December 12`, `nov 26 2023`",
                    "- Just time: `1:12am`, `midnight`, `13:42`, `7pm`",
                    "- Date and time: `02/24/23 19:31:03`",
                    "- Other date formats: `March 30 2023 4:10pm`",
                    "- Simple time: `tomorrow`, `next week`, `thursday at noon`",
                    "- Slightly complicated relative time: `in 1 day, 2 hours and 10 minutes`",
                    "- ISO 8601 format: `2023-08-11T01:59:41.981897`",
                ]

        async def on_submit(self, interaction: discord.Interaction) -> None:
            """
            Callback for modal submission.
            """
            try:
                event = self.sanitize_response(interaction)
            except BadTimezone as e:
                logger.debug("Bad timezone: %s.", e.timezone, exc_info=e)
                if e.timezone is None:
                    # Invalid timezone in dateutil.parser.parse
                    embed = discord.Embed(
                        description="Please don't include timezones in the **Scheduled Time** field.",
                        colour=COLOUR,
                    )
                else:
                    embed = discord.Embed(
                        description="I cannot understand this timezone. Try entering the "
                        "[TZ database name](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones) "
                        "of your timezone (case sensitive).",
                        colour=COLOUR,
                    )
            except TimeInPast as e:  # time is in the past
                logger.debug("Bad time: %s.", e.time, exc_info=e)
                timestamp = int(e.time.timestamp())
                embed = discord.Embed(
                    description=f"The time you inputted is **in the past** <t:{timestamp}> (<t:{timestamp}:R>). "
                    f"Double check the time is valid or try one of the formats below.",
                    colour=COLOUR,
                )
                embed.add_field(
                    name="Valid time formats:", value="\n".join(self.acceptable_formats) + "\n- And More..."
                )
            except InvalidRepeat as e:  # repeat is invalid
                logger.debug("Bad repeat %s.", self.repeat, exc_info=e)
                embed = discord.Embed(description=e.reason, colour=COLOUR)
            except BadTimeString as e:  # time parse error
                embed = discord.Embed(
                    description=f"I cannot understand the time **{discord.utils.escape_markdown(e.time)}**.",
                    colour=COLOUR,
                )
                embed.add_field(
                    name="Valid time formats:", value="\n".join(self.acceptable_formats) + "\n- And More..."
                )
            else:
                # Check if the message contains a mention and both author
                mentions = re.search(r"@(everyone|here|[!&]?[0-9]{17,20})", event.message)

                if mentions is not None:
                    logger.debug("Event has mention.")
                    perms_author = self.channel.permissions_for(event.author)
                    perms_bot = self.channel.permissions_for(self.channel.guild.me)

                    # This is a privileged mention (@everyone, @here, @role)
                    if mentions.group(1) in {"everyone", "here"} or mentions.group(1).startswith("&"):
                        # Bot will need permissions to ping as well
                        check = perms_author.mention_everyone and perms_bot.mention_everyone
                        logger.debug(
                            "Checking all mentions, author: %s bot: %s.",
                            perms_author.mention_everyone,
                            perms_bot.mention_everyone,
                        )
                    else:
                        check = perms_author.mention_everyone
                        logger.debug("Checking all mentions, author: %s.", perms_author.mention_everyone)

                    if check:  # if pinging is a possibility
                        logger.info("Sending mention approval form.")

                        embed = discord.Embed(
                            title="This scheduled message contains mentions",
                            description="Click **Yes** if the mentions should ping "
                            "its members, otherwise click **No**.\n\n"
                            "Alternatively, click **Edit** to revise your message.",
                            colour=COLOUR,
                        )
                        embed.add_field(name="Message", value=event.message, inline=False)
                        await interaction.response.send_message(
                            embed=embed, view=ScheduleMentionView(self, interaction.user, event), ephemeral=True
                        )
                        return

                logger.info("Saving event: no mention or no perms.")
                # Message has no mentions, or the bot or user cannot mention in this channel,
                # so don't bother asking
                await self.scheduler.save_event(interaction, ScheduleEvent.from_sanitized(event, False))
                return

            logger.info("Failed to save, sending edit form.")
            # If failed
            embed.set_footer(text='Click the "Edit" button below to edit your form.')
            await interaction.response.send_message(
                embed=embed, view=ScheduleEditView(self, interaction.user), ephemeral=True
            )

    return ScheduleModal


# The empty ScheduleModal with no defaults
ScheduleModal = get_schedule_modal()


class ScheduleView(discord.ui.View):
    """
    A single-button view for prefixed command to trigger the schedule modal.
    """

    def __init__(
        self, scheduler: Scheduler, author: discord.User | discord.Member, channel: MessageableGuildChannel
    ) -> None:
        """
        :param scheduler: The Scheduler object.
        :param author: The user who created this interaction.
        :param channel: The MessageableGuildChannel for the scheduled message.
        """
        self.scheduler = scheduler
        self.author = author
        self.channel = channel
        super().__init__()

    # noinspection PyUnusedLocal
    @discord.ui.button(label="Create", style=discord.ButtonStyle.green)
    async def create(self, interaction: discord.Interaction, button: discord.ui.Button[ScheduleView]) -> None:
        """
        The "Create" button for the view.
        """
        if interaction.user.id != self.author.id:
            logger.debug("Button clicked by a non-author.")
            return

        logger.info("Creating a schedule modal from schedule view.")
        await interaction.response.send_modal(ScheduleModal(self.scheduler, self.channel))
        if interaction.message:
            try:
                await interaction.message.edit(view=None)
            finally:  # Somehow fails to edit
                self.stop()


class ScheduleEditView(discord.ui.View):
    """
    A single-button view to allow the user to edit the schedule modal.
    """

    def __init__(self, last_schedule_modal: ScheduleModal, author: discord.User | discord.Member) -> None:
        """
        :param last_schedule_modal: The previous ScheduleModal before the retry.
        :param author: The user who created this interaction.
        """
        self.last_schedule_modal = last_schedule_modal
        self.author = author
        super().__init__()

    # noinspection PyUnusedLocal
    @discord.ui.button(label="Edit", style=discord.ButtonStyle.green)
    async def edit(self, interaction: discord.Interaction, button: discord.ui.Button[ScheduleEditView]) -> None:
        """
        The "Edit" button for the view.
        """
        if interaction.user.id != self.author.id:
            logger.debug("Button clicked by a non-author.")
            return

        logger.info("Creating a schedule modal from edit schedule view.")
        await interaction.response.send_modal(
            get_schedule_modal(self.last_schedule_modal)(
                self.last_schedule_modal.scheduler, self.last_schedule_modal.channel
            )
        )
        self.stop()


class ScheduleMentionView(discord.ui.View):
    """
    A single-button view to ask if the user wishes to mention in their scheduled message.
    """

    def __init__(
        self,
        last_schedule_modal: ScheduleModal,
        author: discord.User | discord.Member,
        event: SanitizedScheduleEvent,
    ) -> None:
        """
        :param last_schedule_modal: The previous ScheduleModal before the retry.
        :param author: The user who created this interaction.
        :param event: The sanitized event from the last modal.
        """
        self.last_schedule_modal = last_schedule_modal
        self.author = author
        self.event = event
        super().__init__()

    # noinspection PyUnusedLocal
    @discord.ui.button(label="Yes", style=discord.ButtonStyle.green)
    async def yes(self, interaction: discord.Interaction, button: discord.ui.Button[ScheduleMentionView]) -> None:
        """
        The "Yes" button for the view.
        """
        if interaction.user.id != self.author.id:
            logger.debug("Button clicked by a non-author.")
            return

        logger.info("Saving schedule event with mention.")
        try:
            await self.last_schedule_modal.scheduler.save_event(
                interaction, ScheduleEvent.from_sanitized(self.event, True)
            )
        finally:
            self.stop()

    # noinspection PyUnusedLocal
    @discord.ui.button(label="No", style=discord.ButtonStyle.green)
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button[ScheduleMentionView]) -> None:
        """
        The "No" button for the view.
        """
        if interaction.user.id != self.author.id:
            logger.debug("Button clicked by a non-author.")
            return

        logger.info("Saving schedule event without mention.")
        try:
            await self.last_schedule_modal.scheduler.save_event(
                interaction, ScheduleEvent.from_sanitized(self.event, False)
            )
        finally:
            self.stop()

    # noinspection PyUnusedLocal
    @discord.ui.button(label="Edit", style=discord.ButtonStyle.green)
    async def edit(self, interaction: discord.Interaction, button: discord.ui.Button[ScheduleMentionView]) -> None:
        """
        The "Edit" button for the view.
        """
        if interaction.user.id != self.author.id:
            logger.debug("Button clicked by a non-author.")
            return

        logger.info("Edit schedule modal from mention view.")
        await interaction.response.send_modal(
            get_schedule_modal(self.last_schedule_modal)(
                self.last_schedule_modal.scheduler, self.last_schedule_modal.channel
            )
        )
        self.stop()


class ScheduleListView(discord.ui.View):
    """
    A view that paginates /list by LIMIT_PER_PAGE using buttons.
    """

    LIMIT_PER_PAGE = 10

    def __init__(
        self, scheduler: Scheduler, author: discord.User | discord.Member, channel: MessageableGuildChannel | None
    ) -> None:
        """
        :param scheduler: The Scheduler object.
        :param author: The user who created this interaction.
        :param channel: The MessageableGuildChannel if listing a specific channel.
        """
        self.scheduler = scheduler
        self.author = author
        self.current_page = 0
        self.channel = channel
        self.responded = False

        if self.channel is None:
            self.raw_query = r"""
                SELECT *
                    FROM Scheduler
                    WHERE canceled=0
                        AND author_id=$author_id
                        AND guild_id=$guild_id
                    ORDER BY next_event_time
                    LIMIT {limit}
                    OFFSET {offset}
            """
            self.raw_count_query = r"""
                SELECT count(*)
                    FROM Scheduler
                    WHERE canceled=0
                        AND author_id=$author_id
                        AND guild_id=$guild_id
            """
        else:
            self.raw_query = r"""
                SELECT *
                    FROM Scheduler
                    WHERE canceled=0
                        AND author_id=$author_id
                        AND channel_id=$channel_id
                        AND guild_id=$guild_id
                    ORDER BY next_event_time
                    LIMIT {limit}
                    OFFSET {offset}
            """
            self.raw_count_query = r"""
                SELECT count(*)
                    FROM Scheduler
                    WHERE canceled=0
                        AND author_id=$author_id
                        AND channel_id=$channel_id
                        AND guild_id=$guild_id
            """
        super().__init__()

    async def render(self, interaction: discord.Interaction | commands.Context[Bot]) -> None:
        """
        Render the view onto the interaction/context.
        """
        if interaction.guild is None:
            raise ValueError("Guild shouldn't be None here.")  # TODO: support DM command - list all schedules

        logger.info(
            "Rendering list view for %s at %s, page idx: %d.", self.author, self.channel, self.current_page
        )

        author = interaction.author if isinstance(interaction, commands.Context) else interaction.user
        params = {
            "author_id": author.id,
            "channel_id": self.channel.id if self.channel is not None else None,
            "guild_id": interaction.guild.id,
        }

        # Get the total row count
        async with self.scheduler.db.execute(self.raw_count_query, params) as cur:
            row = await cur.fetchone()

        if row is None:
            raise ValueError("Something went wrong with the DB.")
        total_count: int = row[0]
        logger.debug("Found %d schedule events.", total_count)

        if total_count == 0:  # no scheduled messages
            logger.debug("No schedules found.")
            if self.channel is None:
                embed = discord.Embed(description="You have no scheduled messages.", colour=COLOUR)
            else:
                embed = discord.Embed(
                    description=f"You have no scheduled messages in {self.channel.mention}.", colour=COLOUR
                )

            if isinstance(interaction, commands.Context):
                await interaction.reply(embed=embed)
            else:
                await interaction.response.send_message(embed=embed)
            return

        start_index = self.current_page * self.LIMIT_PER_PAGE
        if start_index >= total_count:  # if the index is beyond the total count, goto last page
            self.current_page = ceil(total_count / self.LIMIT_PER_PAGE) - 1  # get last page
            start_index = self.current_page * self.LIMIT_PER_PAGE

        logger.debug("Querying schedule from %d with limit of %d.", start_index, self.LIMIT_PER_PAGE)
        # Populate schedules from database
        schedules: list[SavedScheduleEvent] = []
        async with self.scheduler.db.execute(
            self.raw_query.format(limit=self.LIMIT_PER_PAGE, offset=start_index),
            params,
        ) as cur:
            async for row in cur:
                schedules += [SavedScheduleEvent.from_row(row)]

        if self.channel is None:
            title = f"{author}'s Scheduled Messages"
        else:
            title = f"{author}'s Scheduled Messages in {self.channel}"

        description = ""  # format the schedule description, limit 2000 character
        for schedule in schedules:
            timestamp = int(schedule.next_event_time)
            description += f"**ID: {schedule.id}** <t:{timestamp}> (<t:{timestamp}:R>)"
            if self.channel is None:
                description += f" <#{schedule.channel_id}>"

            if schedule.repeat is not None:
                repeat = float(schedule.repeat)
                if repeat.is_integer():
                    description += f" every {int(repeat)} minute{'s' if repeat != 1 else ''}"
                else:
                    description += f" every {repeat:.2f} minute{'s' if repeat != 1 else ''}"

            description += ":\n"

            text = discord.utils.escape_markdown(schedule.message.replace("\n", ""))
            if len(text) > 100:  # 100 characters of preview text, 2000 char limit / 10 per page - 100 meta text
                text = text[: 100 - 3].rstrip() + "..."
            description += f"> {text}\n\n"

        embed = discord.Embed(title=title, description=description, colour=COLOUR)

        kwargs: dict[str, Any] = {}
        if total_count > self.LIMIT_PER_PAGE:  # more than one page
            kwargs["view"] = self
            embed.set_footer(text=f"Page {self.current_page + 1} of {ceil(total_count / self.LIMIT_PER_PAGE)}")

        if self.responded:
            if isinstance(interaction, commands.Context):
                raise ValueError("Should only be interaction here (from button click).")
            await interaction.response.edit_message(embed=embed, **kwargs)
        else:
            if isinstance(interaction, commands.Context):
                await interaction.reply(embed=embed, **kwargs)
            else:
                await interaction.response.send_message(embed=embed, **kwargs)
            self.responded = True

    # noinspection PyUnusedLocal
    @discord.ui.button(style=discord.ButtonStyle.green, emoji="⏪")
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button[ScheduleListView]) -> None:
        """
        The "Back" button for the view.
        """
        if interaction.user.id != self.author.id:
            logger.debug("Button clicked by a non-author.")
            return

        self.current_page -= 1
        if self.current_page < 0:
            self.current_page = 0
        await self.render(interaction)

    # noinspection PyUnusedLocal
    @discord.ui.button(style=discord.ButtonStyle.green, emoji="⏩")
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button[ScheduleListView]) -> None:
        """
        The "Next" button for the view.
        """
        if interaction.user.id != self.author.id:
            logger.debug("Button clicked by a non-author.")
            return

        self.current_page += 1
        await self.render(interaction)


class Scheduler(Cog):
    """A general category for all my commands."""

    PER_CHANNEL_LIMIT = 50
    PER_GUILD_LIMIT = 250

    def __init__(self, bot: Bot) -> None:
        self.bot = bot
        self.db: aiosqlite.Connection = cast(aiosqlite.Connection, None)
        self.schedule_heap: list[SavedScheduleEvent] = []
        self.heap_lock = asyncio.Lock()

    async def cog_load(self) -> None:
        """
        This is called when cog is loaded.
        """
        logger.info("Loading scheduler cog.")
        # Setup database
        await self.init_db()

        logger.debug("Populating schedules.")
        # Populate schedules from database
        schedules: list[SavedScheduleEvent] = []
        async with self.db.execute(
            r"""
            SELECT *
                FROM Scheduler
                WHERE canceled=0
                ORDER BY next_event_time
        """
        ) as cur:
            async for row in cur:
                schedules += [SavedScheduleEvent.from_row(row)]

        logger.info("Populated %d schedules.", len(schedules))

        async with self.heap_lock:
            self.schedule_heap = schedules
            heapq.heapify(self.schedule_heap)

        # Start the scheduler loop
        asyncio.create_task(self.scheduler_event_loop())

    async def cog_unload(self) -> None:
        """
        This is called when cog is unloaded.
        """
        # Close SQLite database
        logger.debug("Closing DB connection.")
        await self.db.close()

    async def _update_to_version_0(self) -> None:
        """
        Update DB to version 0.

        Changes:
          - Create the Scheduler table
          - Add 3 indices to Scheduler
        """
        logger.info("[orange]Updating DB version to 0[/orange]", extra={"markup": True})
        async with self.db.execute(
            r"""
                CREATE TABLE Scheduler (
                    id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
                    message VARCHAR(1000) NOT NULL,
                    guild_id DECIMAL(22,0) NOT NULL,
                    channel_id DECIMAL(22,0) NOT NULL,
                    author_id DECIMAL(22,0) NOT NULL,
                    next_event_time INTEGER,
                    repeat DOUBLE,
                    canceled BOOLEAN NOT NULL DEFAULT 0 CHECK (canceled IN (0, 1))
                )
            """
        ):
            pass

        async with self.db.execute(
            r"""
                CREATE INDEX IF NOT EXISTS idx_scheduler_time ON Scheduler (next_event_time)
            """
        ):
            pass

        async with self.db.execute(
            r"""
                CREATE INDEX IF NOT EXISTS idx_scheduler_guild_author ON Scheduler (guild_id, author_id)
            """
        ):
            pass

        async with self.db.execute(
            r"""
                CREATE INDEX IF NOT EXISTS idx_scheduler_canceled ON Scheduler (canceled)
            """
        ):
            pass

    async def _update_to_version_1(self) -> None:
        """
        Update DB to version 1.

        Changes:
          - Add version=1 row to Meta table
          - Add mention column to Scheduler
        """
        logger.info("[orange]Updating DB version to 1[/orange]", extra={"markup": True})
        async with self.db.execute(
            r"""
            INSERT INTO Meta(name, value)
            VALUES ('version', 1)
        """
        ):
            pass

        async with self.db.execute(
            r"""
            ALTER TABLE Scheduler
            ADD COLUMN mention BOOLEAN NOT NULL DEFAULT 0 CHECK (canceled IN (0, 1))
        """
        ):
            pass

    async def init_db(self) -> None:
        """
        Initiates the SQLite database.
        """
        logger.debug("Initiating DB connection.")
        self.db = await aiosqlite.connect(SCHEDULER_DATABASE_PATH)

        # Checks if the meta table exists
        async with self.db.execute(
            r"""
            SELECT name
                FROM sqlite_master
                WHERE type='table'
                    AND name='Meta'
        """
        ) as cur:
            meta_exists = (await cur.fetchone()) is not None

        # If the meta table does not exist, this is means this is the initial database commit
        # or DB version is 0
        if not meta_exists:
            # Create the meta table
            async with self.db.execute(
                r"""
                CREATE TABLE Meta (
                    name VARCHAR(10) PRIMARY KEY NOT NULL,
                    value INTEGER NOT NULL
                )
            """
            ):
                pass

            # Checks if the scheduler table exists
            async with self.db.execute(
                r"""
                    SELECT name
                        FROM sqlite_master
                        WHERE type='table'
                            AND name='Scheduler'
                """
            ) as cur:
                scheduler_exists = (await cur.fetchone()) is not None

            # It's the initial DB commit, this will update to version 0
            if not scheduler_exists:
                await self._update_to_version_0()
            await self._update_to_version_1()

        await self.db.commit()  # commit the changes

    logger.info("Using SQLite version %s.", aiosqlite.sqlite_version)
    # Older versions don't support RETURNING in SQLite
    if version.parse(aiosqlite.sqlite_version) >= version.parse("3.35.0"):

        async def _insert_schedule(self, event: ScheduleEvent) -> SavedScheduleEvent:
            """
            Insert a schedule event into DB SQLite version >= 3.35.0.

            When modifying this method, be sure to update the < 3.35.0 sister method as well.

            :param event: The ScheduleEvent of the event.
            :return: The saved SavedScheduleEvent.
            """
            async with self.db.execute(
                r"""
                    INSERT INTO Scheduler (message, guild_id, channel_id,
                                           author_id, next_event_time, repeat, mention)
                        VALUES ($message, $guild_id, $channel_id, $author_id,
                                $next_event_time, $repeat, $mention)
                        RETURNING *
                """,
                {
                    "message": event.message,
                    "guild_id": event.channel.guild.id,
                    "channel_id": event.channel.id,
                    "author_id": event.author.id,
                    "next_event_time": int(event.time.timestamp()),
                    "repeat": event.repeat,
                    "mention": int(event.mention),
                },
            ) as cur:
                row = await cur.fetchone()
                if row is None:
                    raise ValueError("Something went wrong with SQLite, row should not be None.")
                event_db = SavedScheduleEvent.from_row(row)

            await self.db.commit()
            return event_db

        async def _delete_schedule(
            self, event_id: int, author_id: int, guild_id: int
        ) -> SavedScheduleEvent | None:
            """
            Delete a schedule event into DB SQLite version >= 3.35.0.

            When modifying this method, be sure to update the < 3.35.0 sister method as well.

            :param event_id: The ID of the event.
            :param author_id: The author ID of the event.
            :param guild_id: The guild ID of the event.
            :return: The deleted saved SavedScheduleEvent.
            """

            logger.debug("Deleting event ID %d.", event_id)
            async with self.db.execute(
                r"""
                    UPDATE Scheduler
                        SET canceled=1
                        WHERE canceled=0
                            AND id=$id
                            AND author_id=$author_id
                            AND guild_id=$guild_id
                        RETURNING *
                """,
                {
                    "id": event_id,
                    "author_id": author_id,
                    "guild_id": guild_id,
                },
            ) as cur:
                row = await cur.fetchone()
                if row is None:
                    return None
                event_db = SavedScheduleEvent.from_row(row)

            await self.db.commit()
            logger.info("Deleted event ID %d.", event_id)
            return event_db

    else:

        async def _insert_schedule(self, event: ScheduleEvent) -> SavedScheduleEvent:
            """
            Insert a schedule event into DB SQLite version < 3.35.0.

            When modifying this method, be sure to update the >= 3.35.0 sister method as well.

            :param event: The ScheduleEvent of the event.
            :return: The saved SavedScheduleEvent.
            """

            logger.debug("Inserting %s into DB.", event)
            async with self.db.execute(
                r"""
                    INSERT INTO Scheduler (message, guild_id, channel_id,
                                           author_id, next_event_time, repeat, mention)
                        VALUES ($message, $guild_id, $channel_id, $author_id,
                                $next_event_time, $repeat, $mention)
                """,
                {
                    "message": event.message,
                    "guild_id": event.channel.guild.id,
                    "channel_id": event.channel.id,
                    "author_id": event.author.id,
                    "next_event_time": int(event.time.timestamp()),
                    "repeat": event.repeat,
                    "mention": int(event.mention),
                },
            ) as cur:
                async with self.db.execute(
                    r"""
                    SELECT *
                        FROM Scheduler
                        WHERE id=$id
                        LIMIT 1
                """,
                    {"id": cur.lastrowid},
                ) as cur2:
                    row = await cur2.fetchone()
                    if row is None:
                        raise ValueError("Something went wrong with SQLite, row should not be None.")
                    event_db = SavedScheduleEvent.from_row(row)
            await self.db.commit()
            return event_db

        async def _delete_schedule(
            self, event_id: int, author_id: int, guild_id: int
        ) -> SavedScheduleEvent | None:
            """
            Delete a schedule event into DB SQLite version < 3.35.0.

            When modifying this method, be sure to update the >= 3.35.0 sister method as well.

            :param event_id: The ID of the event.
            :param author_id: The author ID of the event.
            :param guild_id: The guild ID of the event.
            :return: The deleted saved SavedScheduleEvent.
            """

            logger.debug("Deleting event ID %d.", event_id)

            async with self.db.execute(
                r"""
                    SELECT *
                        FROM Scheduler
                        WHERE canceled=0
                            AND id=$id
                            AND author_id=$author_id
                            AND guild_id=$guild_id
                        LIMIT 1
                """,
                {
                    "id": event_id,
                    "author_id": author_id,
                    "guild_id": guild_id,
                },
            ) as cur:
                row = await cur.fetchone()
                if row is None:
                    return None
                event_db = SavedScheduleEvent.from_row(row)

            async with self.db.execute(
                r"""
                    UPDATE Scheduler
                        SET canceled=1
                        WHERE canceled=0
                            AND id=$id
                            AND author_id=$author_id
                            AND guild_id=$guild_id
                """,
                {
                    "id": event_id,
                    "author_id": author_id,
                    "guild_id": guild_id,
                },
            ):
                pass

            await self.db.commit()
            logger.info("Deleted event ID %d.", event_id)
            return event_db

    @staticmethod
    def _make_info_embed(event: SavedScheduleEvent) -> discord.Embed:
        """
        Create an "info" embed for the event. Used in ScheduleEvent creation and show.

        :param event: The SavedScheduleEvent for the info embed.
        :return: A generated info embed.
        """
        embed = discord.Embed(
            colour=COLOUR,
        )
        embed.add_field(name="Message", value=event.message, inline=False)
        embed.add_field(name="Channel", value=f"<#{event.channel_id}>", inline=True)
        if event.repeat is None:
            embed.add_field(name="Repeat", value=f"Disabled", inline=True)
        else:
            repeat = float(event.repeat)

            if repeat.is_integer():
                repeat_message = f"Every {int(repeat)} minute{'s' if repeat != 1 else ''}"
            else:
                repeat_message = f"Every {repeat:.2f} minute{'s' if repeat != 1 else ''}"
            embed.add_field(name="Repeat", value=repeat_message, inline=True)

        mentions = re.search(r"@(everyone|here|[!&]?[0-9]{17,20})", event.message)
        if mentions is not None:  # has mentions
            embed.add_field(name="Ping Enabled", value="Yes" if event.mention else "No", inline=True)
        timestamp = int(event.next_event_time)
        embed.add_field(name="Time", value=f"<t:{timestamp}> (<t:{timestamp}:R>)", inline=False)
        return embed

    async def save_event(self, interaction: discord.Interaction, event: ScheduleEvent) -> None:
        """
        Saves the ScheduleEvent into database and adds to the event heap.

        :param interaction: The interaction context.
        :param event: The ScheduleEvent to save.
        """
        try:
            event_db = await self._save_event(event)
        except TooManyEvents as e:
            # The user has too many scheduled messages in this channel/guild
            if isinstance(e, TooManyChannelEvents):
                embed = discord.Embed(
                    description=f"You cannot created any more scheduled messages "
                    f"in {event.channel.mention} (max {e.limit}).",
                    colour=COLOUR,
                )
            else:
                embed = discord.Embed(
                    description=f"You cannot created any more scheduled messages "
                    f"in this server (max {e.limit}).",
                    colour=COLOUR,
                )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        except Exception as e:
            # Something unexpected went wrong
            err_code = token_hex(5)
            logger.error("Something went wrong while saving event. Code: %s.", err_code, exc_info=e)
            embed = discord.Embed(
                description="An unexpected error occurred, try again later. "
                f"Please report this to the bot author with error code `{err_code}`.",
                colour=COLOUR,
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        embed = self._make_info_embed(event_db)
        embed.title = f"Scheduled Message Created (Event ID #{event_db.id})"
        embed.set_footer(text=f"{event.author} has created a scheduled message.")
        await interaction.response.send_message(embed=embed)
        return

    async def _save_event(self, event: ScheduleEvent) -> SavedScheduleEvent:
        """
        Saves the ScheduleEvent into database and adds to the event heap.

        :param event: The created ScheduleEvent object from the form.
        """

        # Check is below limit TODO: Add constraints to DB
        async with self.db.execute(
            r"""
            SELECT count(*)
                FROM Scheduler
                WHERE canceled=0
                    AND author_id=$author_id
                    AND guild_id=$guild_id
                    AND channel_id=$channel_id
        """,
            {"author_id": event.author.id, "guild_id": event.channel.guild.id, "channel_id": event.channel.id},
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            raise ValueError("Row shouldn't be None here.")
        count_channel = row[0]

        if count_channel >= self.PER_CHANNEL_LIMIT:
            logger.info(
                "Failed to create event, user has too many events %s/%s.", count_channel, self.PER_CHANNEL_LIMIT
            )
            raise TooManyChannelEvents(self.PER_CHANNEL_LIMIT)

        async with self.db.execute(
            r"""
            SELECT count(*)
                FROM Scheduler
                WHERE canceled=0
                    AND author_id=$author_id
                    AND guild_id=$guild_id
        """,
            {"author_id": event.author.id, "guild_id": event.channel.guild.id},
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            raise ValueError("Row shouldn't be None here.")
        count_guild = row[0]

        if count_guild >= self.PER_GUILD_LIMIT:
            logger.info(
                "Failed to create event, user has too many guild events %s/%s.",
                count_channel,
                self.PER_GUILD_LIMIT,
            )
            raise TooManyGuildEvents(self.PER_GUILD_LIMIT)

        # Inserts into database
        event_db = await self._insert_schedule(event)

        logger.info("Added schedule into database with ID %d.", event_db.id)
        logger.info(
            "Message (preview): %s\nGuild: %s\nChannel: %s\nAuthor: %s\nRepeat: %s\nMention: %s\nTime: %s",
            event.message[:80],
            event.channel.guild,
            event.channel,
            event.author,
            event.repeat,
            event.mention,
            event.time,
        )

        # Add the event into the schedule heap
        async with self.heap_lock:
            heapq.heappush(self.schedule_heap, event_db)
        return event_db

    async def send_scheduled_message(self, event: SavedScheduleEvent) -> bool:
        """
        Sends a scheduled event message.

        :param event: A SavedScheduleEvent fetched from the database.
        :return: True if send was successful, False otherwise.
        """

        # Check if the event was canceled
        async with self.db.execute(
            r"""
            SELECT canceled
                FROM Scheduler
                WHERE id=$id
        """,
            {"id": event.id},
        ) as cur:
            row = await cur.fetchone()
            if row is None:
                logger.error("Row should not be None, why was this deleted?")
                return False

            if row[0]:  # if canceled is true
                logger.warning("Event with ID %d was canceled.", event.id)
                return False

        # Check if bot is still in guild
        guild = self.bot.get_guild(event.guild_id)
        if not guild:
            logger.warning("Event with ID %d guild not found.", event.id)
            return False

        # Check if channel still exists
        channel = guild.get_channel_or_thread(event.channel_id)
        if not channel:
            logger.warning("Event with ID %d channel not found.", event.id)
            return False
        if not hasattr(channel, "send"):
            logger.warning("Event with ID %d channel is not a messageable channel.", event.id)
            return False

        # Check if user is still in guild
        author = guild.get_member(event.author_id)
        if not author:
            try:
                author = await guild.fetch_member(event.author_id)
            except discord.NotFound:
                logger.warning("Event with ID %d author not found.", event.id)
                return False

        # Check if the still user has permission
        perms_author = channel.permissions_for(author)
        if not perms_author.read_messages or not perms_author.send_messages:
            logger.warning("Event with ID %d author doesn't have perms.", event.id)
            return False

        # Check if the bot still has permission
        perms_bot = channel.permissions_for(guild.me)
        if not perms_bot.read_messages or not perms_bot.send_messages:
            logger.warning("Event with ID %d bot doesn't have perms.", event.id)
            return False

        if event.mention and perms_author.mention_everyone:  # if mentions is enabled and author still has perms
            allowed_mentions = discord.AllowedMentions.all()
        else:
            if event.mention:
                logger.debug(
                    "Event with ID %s mention disabled due to author doesn't have mention_everyone permission.",
                    event.id,
                )
            allowed_mentions = discord.AllowedMentions.none()
        # channel has .send since invalid channel typed are filtered above with hasattr(channel, 'send')
        await channel.send(  # type: ignore[reportGeneralTypeIssues]
            event.message, allowed_mentions=allowed_mentions
        )
        # TODO: add a "report abuse" feature/command, save all sent msg in a db table with the id
        return True

    async def _scheduler_event_loop(self) -> None:
        """
        Internal iteration of the scheduler event loop.
        """
        should_sleep = False
        while not should_sleep:
            should_sleep = True

            if self.schedule_heap:
                async with self.heap_lock:  # pop the next event from heap
                    next_event = heapq.heappop(self.schedule_heap)

                now = arrow.utcnow().timestamp()
                # Time has past
                if next_event.next_event_time < now:
                    should_sleep = False
                    try:
                        # Attempt to send the message
                        success = await self.send_scheduled_message(next_event)
                    except Exception as e:
                        # Something unexpected went wrong
                        logger.error(
                            "Something went wrong while sending the scheduled message with event ID %d.",
                            next_event.id,
                            exc_info=e,
                        )
                        success = False

                    if not success or next_event.repeat is None:
                        # If the message failed to send or the message isn't on repeat, then cancel the schedule
                        async with self.db.execute(
                            r"""
                                UPDATE Scheduler
                                    SET canceled=1
                                    WHERE id=$id
                            """,
                            {"id": next_event.id},
                        ):
                            pass
                        await self.db.commit()
                        logger.info("Canceled %s because it failed.", next_event)

                    else:
                        # Otherwise, update the next_event_time
                        new_event = next_event.do_repeat(int(now))
                        async with self.db.execute(
                            r"""
                                UPDATE Scheduler
                                    SET next_event_time=$next_event_time
                                    WHERE id=$id
                            """,
                            {"next_event_time": new_event.next_event_time, "id": next_event.id},
                        ):
                            pass
                        await self.db.commit()
                        # re-add the updated event
                        async with self.heap_lock:
                            heapq.heappush(self.schedule_heap, new_event)
                else:
                    # re-add the original event when the time isn't up yet
                    async with self.heap_lock:
                        heapq.heappush(self.schedule_heap, next_event)

    async def scheduler_event_loop(self) -> None:
        """
        The main scheduler event loop, checks every second.
        """
        await self.bot.wait_until_ready()

        while not self.bot.is_closed():
            try:
                await self._scheduler_event_loop()
            except Exception as e:
                logger.error("An uncaught error was raised during scheduled event loop.", exc_info=e)
            await asyncio.sleep(1)

    async def _schedule_create(self, ctx: commands.Context[Bot], channel: MessageableGuildChannel | None) -> None:
        """
        Internal callback for /schedule create, schedule, and schedule create to create a scheduled message.
        """
        logger.debug("%s is trying to create a schedule.", ctx.author)

        if channel is None:
            if not isinstance(ctx.channel, MessageableGuildChannel):
                raise ValueError("Where else was this command ran?")

            channel = ctx.channel

        if not isinstance(ctx.author, discord.Member):
            raise ValueError("How does a non-member run this command?")

        if not isinstance(ctx.me, discord.Member):
            raise ValueError("Why am I not a member?")

        # Check if the user has permission
        perms = channel.permissions_for(ctx.author)
        if not perms.read_messages or not perms.send_messages:
            logger.debug("Author has no send or read messages perms for create.")
            embed = discord.Embed(
                description=f"You must have **send messages** permissions in {channel.mention}.", colour=COLOUR
            )
            await ctx.reply(embed=embed)
            return
        # Check if the bot has permission
        perms = channel.permissions_for(ctx.me)
        if not perms.read_messages or not perms.send_messages:
            logger.debug("Bot has no send or read messages perms for create.")
            embed = discord.Embed(description=f"I don't have permission in {channel.mention}.", colour=COLOUR)
            await ctx.reply(embed=embed)
            return

        # If prefixed command is used, send a button
        if ctx.interaction is None:
            embed = discord.Embed(
                description="Click the button below to create a scheduled message.", colour=COLOUR
            )
            await ctx.reply(embed=embed, view=ScheduleView(self, ctx.author, channel))
        else:
            # Otherwise, directly open the modal
            await ctx.interaction.response.send_modal(ScheduleModal(self, channel))

    @commands.guild_only()
    @commands.hybrid_group(ignore_extra=False)
    async def schedule(
        self,
        ctx: commands.Context[Bot],
        *,
        channel: MessageableGuildChannel = None,  # type: ignore[reportGeneralTypeIssues]
    ) -> None:
        """Schedules a message for the future.
        `channel` - The channel for the scheduled message.

        You must have **send messages** permissions in the target channel.
        """
        await self._schedule_create(ctx, channel)

    @commands.guild_only()
    @schedule.command(name="create", ignore_extra=False, hidden=True)
    @discord.app_commands.describe(channel="The channel for the scheduled message.")
    async def schedule_create(
        self,
        ctx: commands.Context[Bot],
        *,
        channel: MessageableGuildChannel = None,  # type: ignore[reportGeneralTypeIssues]
    ) -> None:
        """Schedules a message for the future.
        `channel` - The channel for the scheduled message.

        You must have **send messages** permissions in the target channel.
        """
        await self._schedule_create(ctx, channel)

    @commands.guild_only()
    @schedule.command(name="list", ignore_extra=False)
    @discord.app_commands.describe(channel="The channel to list scheduled messages.")
    async def schedule_list(
        self,
        ctx: commands.Context[Bot],
        *,
        channel: MessageableGuildChannel = None,  # type: ignore[reportGeneralTypeIssues]
    ) -> None:
        """List your scheduled messages.
        `channel` - The channel to list scheduled messages.
        """
        logger.debug("%s is trying to list a schedule.", ctx.author)

        await ScheduleListView(self, ctx.author, channel).render(ctx)

    @commands.guild_only()
    @schedule.command(name="show", aliases=["view"])
    @discord.app_commands.describe(event_id="The event ID of the scheduled message (see `/list`).")
    async def schedule_show(self, ctx: commands.Context[Bot], event_id: int) -> None:
        """Show related info of a scheduled message event.
        `event_id` - The event ID of the scheduled message (see `/list`).
        """

        logger.debug("%s is trying to show schedule %d.", ctx.author, event_id)

        if not ctx.guild:
            raise ValueError("Shouldn't be None here.")

        # TODO: support DM without guild check
        async with self.db.execute(
            r"""
                SELECT *
                    FROM Scheduler
                    WHERE canceled=0
                        AND id=$id
                        AND author_id=$author_id
                        AND guild_id=$guild_id
                    LIMIT 1
            """,
            {"id": event_id, "author_id": ctx.author.id, "guild_id": ctx.guild.id},
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            logger.debug("No scheduled messages found.")
            embed = discord.Embed(
                description=f"You do not have a scheduled message with Event ID #{event_id}.", colour=COLOUR
            )
            await ctx.reply(embed=embed)
            return

        event = SavedScheduleEvent.from_row(row)

        embed = self._make_info_embed(event)
        embed.title = f"Event ID #{event.id}"
        await ctx.reply(embed=embed)
        return

    @commands.guild_only()
    @schedule.command(name="delete", aliases=["remove"])
    @discord.app_commands.describe(event_id="The event ID of the scheduled message (see `/list`).")
    async def schedule_delete(self, ctx: commands.Context[Bot], event_id: int) -> None:
        """Delete a previously scheduled message event.
        `event_id` - The event ID of the scheduled message (see `/list`).
        """
        logger.debug("%s is trying to delete schedule %d.", ctx.author, event_id)

        if not ctx.guild:
            raise ValueError("Shouldn't be None here.")

        removed_event = await self._delete_schedule(event_id, ctx.author.id, ctx.guild.id)
        if removed_event is None:
            embed = discord.Embed(
                description=f"You **do not** have a scheduled message with Event ID #{event_id}.", colour=COLOUR
            )
        else:
            embed = discord.Embed(
                description=f"Successfully deleted scheduled message with Event ID #{event_id}.", colour=COLOUR
            )
        await ctx.reply(embed=embed, ephemeral=ctx.interaction is not None)  # don't show for slash commands
        return


async def setup(bot: Bot) -> None:
    await bot.add_cog(Scheduler(bot))
