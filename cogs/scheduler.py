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
from secrets import token_hex
from typing import TYPE_CHECKING, NamedTuple, Type

import aiosqlite
import arrow
from dateutil import parser as du_parser
from packaging import version

import discord
from discord.ext import commands

from src.commands import Cog
from src.env import COLOUR, SCHEDULER_DATABASE_PATH, DEBUG_MODE, DEFAULT_TIMEZONE

if TYPE_CHECKING:
    from src.bot import Bot


logger = logging.getLogger(__name__)

DB_VERSION = 1


class SanitizedScheduleEvent(NamedTuple):
    """
    Represents a single scheduled message event after modal sanitization.
    """

    author: discord.User | discord.Member
    channel: discord.TextChannel
    message: str
    time: arrow.Arrow
    repeat: float | None


class ScheduleEvent(NamedTuple):
    """
    Represents a single scheduled message event.
    """

    author: discord.User | discord.Member
    channel: discord.TextChannel
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
        return cls(*(event + (mention,)))


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
        return SavedScheduleEvent(
            self.id,
            self.message,
            self.guild_id,
            self.channel_id,
            self.author_id,
            current_timestamp + self.repeat * 60,
            self.repeat,
            self.canceled,
            self.mention,
        )

    def __lt__(self, other: SavedScheduleEvent) -> bool:
        """
        Use next_event_time as the comp.
        """
        return self.next_event_time < other.next_event_time


class TimeInPast(ValueError):
    """
    Raised when scheduler time is in the past.
    """

    def __init__(self, time: arrow.Arrow) -> None:
        self.time = time


class InvalidRepeat(ValueError):
    """
    Raised when scheduler repeat is longer than a year or shorter than an hour.
    """

    def __init__(self, reason: str) -> None:
        self.reason = reason


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

    class _ScheduleModal(discord.ui.Modal, title="Schedule Creator"):
        """
        The scheduling modal to collect info for the schedule.
        """

        message = discord.ui.TextInput(
            label="Message",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=1000,
            default=message_default,
        )
        time = discord.ui.TextInput(
            label="Scheduled Time (MM/DD/YY HH:MM:SS)", required=True, max_length=100, default=time_default
        )
        timezone = discord.ui.TextInput(
            label="Timezone (UTC offset +/-HH:MM)", required=False, max_length=100, default=timezone_default
        )
        repeat = discord.ui.TextInput(
            label="Repeat every n minutes (0 to disable, min 60)",
            required=False,
            max_length=10,
            default=repeat_default,
        )

        def __init__(self, scheduler: Scheduler, channel: discord.TextChannel):
            """
            :param scheduler: The Scheduler object.
            :param channel: The TextChannel for the scheduled message.
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

            # parse the time
            with warnings.catch_warnings():
                # noinspection PyUnresolvedReferences
                warnings.simplefilter("error", du_parser.UnknownTimezoneWarning)  # exists, but editor is weird
                naive_time = du_parser.parse(self.time.value)

            # apply the timezone
            if self.timezone.value:  # if user inputted a timezone
                time = arrow.get(naive_time, self.timezone.value)
            else:
                time = arrow.get(naive_time)  # will use either tz from naive time or UTC

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
            return [
                "- 1/30/2023 3:20am",
                "- Jan 30 2023 3:20",
                "- 2023-Jan-30 3h20m",
                "- January 30th, 2023 at 03:20:00",
            ]

        async def on_submit(self, interaction: discord.Interaction) -> None:
            """
            Callback for modal submission.
            """
            try:
                event = self.sanitize_response(interaction)
            except du_parser.UnknownTimezoneWarning:  # noqa
                embed = discord.Embed(
                    description="Please don't include timezones in the **Scheduled Time** field.", colour=COLOUR
                )
            except TimeInPast as e:  # time is in the past
                embed = discord.Embed(
                    description=f"The time you inputted is in the past (<t:{int(e.time.timestamp())}>). "
                    f"Double check the time is valid or try one of the formats below.",
                    colour=COLOUR,
                )
                embed.add_field(
                    name="Valid time formats:", value="\n".join(self.acceptable_formats) + "\n- And More..."
                )
            except InvalidRepeat as e:  # repeat is invalid
                embed = discord.Embed(description=e.reason, colour=COLOUR)
            except du_parser.ParserError:  # time parse error
                embed = discord.Embed(
                    description=f"I cannot understand the time **{discord.utils.escape_markdown(self.time.value)}**.",
                    colour=COLOUR,
                )
                embed.add_field(
                    name="Valid time formats:", value="\n".join(self.acceptable_formats) + "\n- And More..."
                )
            else:
                # Check if the message contains a mention and both author
                mentions = re.search(r"@(everyone|here|[!&]?[0-9]{17,20})", event.message)

                if mentions is not None:
                    perms_author = self.channel.permissions_for(event.author)
                    perms_bot = self.channel.permissions_for(self.channel.guild.me)

                    # This is a privileged mention (@everyone, @here, @role)
                    if mentions.group(1) in {"everyone", "here"} or mentions.group(1).startswith("&"):
                        # Bot will need permissions to ping as well
                        check = perms_author.mention_everyone and perms_bot.mention_everyone
                    else:
                        check = perms_author.mention_everyone
                    if check:  # if pinging is a possibility
                        embed = discord.Embed(
                            title="This scheduled message contains mentions",
                            description="Click **Yes** if the mentions should ping "
                            "its members, otherwise click **No**.\n\n"
                            "Alternatively, click **Edit** to revise your message.",
                            colour=COLOUR,
                        )
                        embed.add_field(name="Message", value=event.message, inline=False)
                        await interaction.response.send_message(
                            embed=embed, view=ScheduleMentionView(self, event), ephemeral=True
                        )
                        return

                # Message has no mentions, or the bot or user cannot mention in this channel,
                # so don't bother asking
                await self.scheduler.save_event(interaction, ScheduleEvent.from_sanitized(event, False))
                return

            # If failed
            embed.set_footer(text='Click the "Edit" button below to edit your form.')
            await interaction.response.send_message(embed=embed, view=ScheduleEditView(self), ephemeral=True)

    return _ScheduleModal


# The empty ScheduleModal with no defaults
ScheduleModal = get_schedule_modal()


class ScheduleView(discord.ui.View):
    """
    A single-button view for prefixed command to trigger the schedule modal.
    """

    def __init__(self, scheduler: Scheduler, channel: discord.TextChannel) -> None:
        """
        :param scheduler: The Scheduler object.
        :param channel: The TextChannel for the scheduled message.
        """
        self.scheduler = scheduler
        self.channel = channel
        super().__init__()

    # noinspection PyUnusedLocal
    @discord.ui.button(label="Create", style=discord.ButtonStyle.green)
    async def create(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        """
        The "Create" button for the view.
        """
        await interaction.response.send_modal(ScheduleModal(self.scheduler, self.channel))
        try:
            await interaction.message.edit(view=None)
        finally:  # Somehow fails to edit
            self.stop()


class ScheduleEditView(discord.ui.View):
    """
    A single-button view to allow the user to edit the schedule modal.
    """

    def __init__(self, last_schedule_modal: ScheduleModal) -> None:
        """
        :param last_schedule_modal: The previous ScheduleModal before the retry.
        """
        self.last_schedule_modal = last_schedule_modal
        super().__init__()

    # noinspection PyUnusedLocal
    @discord.ui.button(label="Edit", style=discord.ButtonStyle.green)
    async def edit(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        """
        The "Edit" button for the view.
        """
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

    def __init__(self, last_schedule_modal: ScheduleModal, event: SanitizedScheduleEvent) -> None:
        """
        :param last_schedule_modal: The previous ScheduleModal before the retry.
        :param event: The sanitized event from the last modal.
        """
        self.last_schedule_modal = last_schedule_modal
        self.event = event
        super().__init__()

    # noinspection PyUnusedLocal
    @discord.ui.button(label="Yes", style=discord.ButtonStyle.green)
    async def yes(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        """
        The "Yes" button for the view.
        """
        try:
            await self.last_schedule_modal.scheduler.save_event(
                interaction, ScheduleEvent.from_sanitized(self.event, True)
            )
        finally:
            self.stop()

    # noinspection PyUnusedLocal
    @discord.ui.button(label="No", style=discord.ButtonStyle.green)
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        """
        The "No" button for the view.
        """
        try:
            await self.last_schedule_modal.scheduler.save_event(
                interaction, ScheduleEvent.from_sanitized(self.event, False)
            )
        finally:
            self.stop()

    # noinspection PyUnusedLocal
    @discord.ui.button(label="Edit", style=discord.ButtonStyle.green)
    async def edit(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        """
        The "Edit" button for the view.
        """
        await interaction.response.send_modal(
            get_schedule_modal(self.last_schedule_modal)(
                self.last_schedule_modal.scheduler, self.last_schedule_modal.channel
            )
        )
        self.stop()


class Scheduler(Cog):
    """A general category for all my commands."""

    def __init__(self, bot: Bot) -> None:
        self.bot = bot
        self.db: aiosqlite.Connection | None = None
        self.schedule_heap: list[SavedScheduleEvent] = []
        self.heap_lock = asyncio.Lock()

    async def cog_load(self) -> None:
        """
        This is called when cog is loaded.
        """
        # Setup database
        await self.init_db()

        # Populate schedules from database
        schedules = []
        async with self.db.execute(
            r"""
            SELECT * 
                FROM Scheduler
                WHERE canceled!=1
                ORDER BY next_event_time
        """
        ) as cur:
            async for row in cur:
                schedules += [SavedScheduleEvent.from_row(row)]

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

    # Older versions don't support RETURNING in SQLite
    if version.parse(aiosqlite.sqlite_version) >= version.parse("3.35.0"):

        async def _insert_schedule(self, event: ScheduleEvent) -> SavedScheduleEvent:
            async with self.db.execute(
                r"""
                    INSERT INTO Scheduler (message, guild_id, channel_id, author_id, next_event_time, repeat, mention)
                        VALUES ($message, $guild_id, $channel_id, $author_id, $next_event_time, $repeat, $mention)
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
                event_db = SavedScheduleEvent.from_row(await cur.fetchone())

            await self.db.commit()
            return event_db

    else:

        async def _insert_schedule(self, event: ScheduleEvent) -> SavedScheduleEvent:
            async with self.db.execute(
                r"""
                    INSERT INTO Scheduler (message, guild_id, channel_id, author_id, next_event_time, repeat, mention)
                        VALUES ($message, $guild_id, $channel_id, $author_id, $next_event_time, $repeat, $mention)
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
                    event_db = SavedScheduleEvent.from_row(await cur2.fetchone())
            await self.db.commit()
            return event_db

    async def save_event(self, interaction: discord.Interaction, event: ScheduleEvent) -> None:
        """
        Saves the ScheduleEvent into database and adds to the event heap.

        :param interaction: The interaction context.
        :param event: The created SanitizedScheduleEvent object from the form.
        """
        try:
            await self._save_event(event)
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

        embed = discord.Embed(
            title="Scheduled Message Created",
            colour=COLOUR,
        )
        embed.add_field(name="Message", value=event.message, inline=False)
        embed.add_field(name="Channel", value=event.channel.mention, inline=True)
        if event.repeat is None:
            embed.add_field(name="Repeat", value=f"Disabled", inline=True)
        else:
            if event.repeat.is_integer():
                repeat_message = f"Every {int(event.repeat)} minute{'s' if event.repeat != 1 else ''}"
            else:
                repeat_message = f"Every {event.repeat:.2f} minute{'s' if event.repeat != 1 else ''}"
            embed.add_field(name="Repeat", value=repeat_message, inline=True)

        mentions = re.search(r"@(everyone|here|[!&]?[0-9]{17,20})", event.message)
        if mentions is not None:  # has mentions
            embed.add_field(name="Ping Enabled", value="Yes" if event.mention else "No", inline=True)
        embed.add_field(name="Time", value=f"<t:{int(event.time.timestamp())}>", inline=False)

        embed.set_footer(text=f"{event.author} has created a scheduled message.")
        await interaction.response.send_message(embed=embed)
        return

    async def _save_event(self, event: ScheduleEvent) -> None:
        """
        Saves the ScheduleEvent into database and adds to the event heap.

        :param event: The created ScheduleEvent object from the form.
        """
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
            if (await cur.fetchone())[0]:  # if canceled is true
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
        await channel.send(event.message, allowed_mentions=allowed_mentions)
        # TODO: add a "report abuse" feature/command, save all sent msg in a db table with the id
        return True

    async def scheduler_event_loop(self) -> None:
        """
        The main scheduler event loop, checks every second.
        """
        await self.bot.wait_until_ready()

        while not self.bot.is_closed():
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

            await asyncio.sleep(1)

    @commands.guild_only()
    @commands.hybrid_command()
    @discord.app_commands.describe(channel="The channel for the scheduled message.")
    async def schedule(self, ctx: commands.Context, channel: discord.TextChannel | None) -> None:
        """Schedules a message for the future.

        channel: The channel for the scheduled message.
        You must have **send messages** permissions in the target channel.
        """

        if channel is None:
            channel = ctx.channel

        # Check if the user has permission
        perms = channel.permissions_for(ctx.author)
        if not perms.read_messages or not perms.send_messages:
            embed = discord.Embed(
                description=f"You must have **send messages** permissions in {channel.mention}.", colour=COLOUR
            )
            await ctx.reply(embed=embed)
            return
        # Check if the bot has permission
        perms = channel.permissions_for(ctx.me)
        if not perms.read_messages or not perms.send_messages:
            embed = discord.Embed(description=f"I don't have permission in {channel.mention}.", colour=COLOUR)
            await ctx.reply(embed=embed)
            return

        # If prefixed command is used, send a button
        if ctx.interaction is None:
            embed = discord.Embed(
                description="Click the button below to create a scheduled message.", colour=COLOUR
            )
            await ctx.reply(embed=embed, view=ScheduleView(self, channel))
        else:
            # Otherwise, directly open the modal
            await ctx.interaction.response.send_modal(ScheduleModal(self, channel))


async def setup(bot: Bot) -> None:
    await bot.add_cog(Scheduler(bot))
