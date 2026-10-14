from datetime import datetime, timedelta
from logging import getLogger

import discord
from discord.app_commands import Group, command, describe

from ferrybot.config import BotConfig

from .utils import event_is_pub, get_formatted_pub_name, get_pub_buttons_view
from .views import PubView
from ferrybot.api import (
    FerryAPI,
    PubBookingAlreadyExistsError,
    PubEventTombstoneAlreadyExistsError,
    PubSchema,
)

LOGGER = getLogger(__name__)


class PubCommand(Group):
    def __init__(self, config: BotConfig, api_client: FerryAPI) -> None:
        self.config = config
        self.api_client = api_client
        super().__init__(name="pub", description="Manage the pub event")

    async def _choose_pub(
        self,
        interaction: discord.Interaction,
        prompt: str,
    ) -> PubSchema:
        view = PubView(await self.api_client.get_pubs(), prompt)
        await interaction.response.send_message(
            prompt,
            view=view,
            ephemeral=True,
        )
        pub = await view.wait_until_complete()
        LOGGER.info(f"{interaction.user} chose {pub.name}")
        return pub

    def _get_next_pub_time(self) -> datetime:
        now = datetime.now(tz=self.config.timezone)

        today = now.date()
        if today.weekday() < self.config.pub.weekday or (
            today.weekday() == self.config.pub.weekday
            and (now.hour, now.minute) < (self.config.pub.hour, self.config.pub.minute)  # noqa: E501,W503
        ):
            # The pub has not yet happened
            monday = today - timedelta(days=today.weekday())
        else:
            # The pub has already started or happened, look at next week
            monday = today + timedelta(days=7 - today.weekday())
        pubday = monday + timedelta(days=self.config.pub.weekday)

        return datetime(
            pubday.year,
            pubday.month,
            pubday.day,
            self.config.pub.hour,
            self.config.pub.minute,
            tzinfo=self.config.timezone,
        )

    def _get_next_pub_scheduled_event(
        self, guild: discord.Guild, *, ignore_time: bool = False
    ) -> discord.ScheduledEvent | None:
        pub_time = self._get_next_pub_time()
        for event in sorted(guild.scheduled_events, key=lambda se: se.start_time):
            if (
                event_is_pub(event)
                and (ignore_time or event.start_time == pub_time)
                and event.status in {discord.EventStatus.scheduled, discord.EventStatus.active}
            ):
                return event
        return None

    async def _create_pub_event(
        self,
        guild: discord.Guild,
        pub: PubSchema,
        start_time: datetime,
        *,
        user: discord.User | discord.Member,
        title: str = "Pub",
    ) -> discord.ScheduledEvent:
        LOGGER.info(f"Creating scheduled event at {start_time}")
        scheduled_event = await guild.create_scheduled_event(
            name=f"{pub.emoji} {title} {self.config.pub.supplemental_emoji}",
            start_time=start_time,
            end_time=start_time + timedelta(hours=3),
            entity_type=discord.EntityType.external,
            privacy_level=discord.PrivacyLevel.guild_only,
            location=pub.name,
            description=self.config.pub.description,
            reason=f"{user} used the /pub next command",
        )
        person = await self.api_client.get_person_for_discord_member(user)
        await self.api_client.create_pub_event(
            timestamp=start_time,
            pub_id=pub.id,
            created_by=person.id,
            scheduled_event_id=scheduled_event.id,
        )
        return scheduled_event

    @command(description="Select the pub for next week.")  # type: ignore[arg-type]
    async def next(self, interaction: discord.Interaction) -> None:  # noqa: A003
        LOGGER.info(f"{interaction.user} used /pub next")
        assert interaction.guild is not None

        if self._get_next_pub_scheduled_event(interaction.guild):
            LOGGER.info("A pub event already exists.")
            await interaction.response.send_message(
                "A pub event already exists.",
                ephemeral=True,
            )
            return

        pub_time = self._get_next_pub_time()

        pub = await self._choose_pub(
            interaction,
            f"Please choose the pub for {pub_time}",
        )

        pub_channel = interaction.guild.get_channel(self.config.pub.channel_id)
        assert isinstance(pub_channel, discord.TextChannel)

        scheduled_event = await self._create_pub_event(
            interaction.guild,
            pub,
            pub_time,
            user=interaction.user,
        )

        pub_event = await self.api_client.get_pub_event_by_discord_id(scheduled_event.id)

        if not pub_event:
            await interaction.followup.send(
                "Something went wrong when creating the event", ephemeral=True
            )
            return

        def _get_display(attendee) -> str:
            if attendee.discord_id:
                return f"<@{attendee.discord_id}>"
            else:
                return attendee.display_name

        attendee_mentions = " ,".join(_get_display(a) for a in pub_event.attendees)
        tombstone_mentions = " ,".join(_get_display(a) for a in pub_event.tombstoned_attendees)

        pub_channel = interaction.guild.get_channel(self.config.pub.channel_id)
        assert isinstance(pub_channel, discord.TextChannel)

        LOGGER.info(f"Posting pub info in {pub_channel}")
        formatted_pub_name = get_formatted_pub_name(pub, self.config)
        message = [
            "**Pub Next Week**",
            f"The next pub will be <t:{int(pub_time.timestamp())}:R>",
            f"It will be held at {formatted_pub_name}",
            "",
            "If you are coming, please mark 🔔 interest on the event!",
        ]

        if attendee_mentions:
            message += [
                "",
                f"The following people have opted-in via AutoPub: {attendee_mentions}",
            ]

        if tombstone_mentions:
            message += [
                "",
                f"The following people have opted-out of AutoPub: {tombstone_mentions}",
            ]

        await pub_channel.send(
            "\n".join(message),
            view=get_pub_buttons_view(pub),
        )

    @command(description="Get the people attending the next pub event")
    async def attendees(self, interaction: discord.Interaction) -> None:
        assert interaction.guild

        event = self._get_next_pub_scheduled_event(interaction.guild, ignore_time=True)
        if event is None:
            LOGGER.info("No pub exists.")
            await interaction.response.send_message(
                "There doesn't appear to be a pub at this time.",
                ephemeral=True,
            )
            return

        pub_event = await self.api_client.get_pub_event_by_discord_id(event.id)
        if pub_event is None:
            await interaction.response.send_message(
                "Unable to find the current pub event in the database.",
                ephemeral=True,
            )
            return

        count = len(pub_event.attendees)

        message = [f"There are {count} people coming to the pub on {pub_event.timestamp}:"]

        message += [
            f"<@{attendee.discord_id}>" if attendee.discord_id else attendee.display_name
            for attendee in pub_event.attendees
        ]

        await interaction.response.send_message(
            "\n".join(message),
            ephemeral=True,
        )

    @command(description="Change the venue for a pub event")  # type: ignore[arg-type]
    async def change(self, interaction: discord.Interaction) -> None:  # noqa: A003
        LOGGER.info(f"{interaction.user} used /pub change")
        assert interaction.guild is not None

        scheduled_event = self._get_next_pub_scheduled_event(interaction.guild)
        if not scheduled_event:
            LOGGER.info("No upcoming pub event.")
            await interaction.response.send_message(
                "There is no upcoming pub event. Use /pub next",
                ephemeral=True,
            )
            return

        original_pub_event = await self.api_client.get_pub_event_by_discord_id(scheduled_event.id)
        if original_pub_event is None:
            await interaction.response.send_message(
                "The pub event is incorrectly registered. Cannot update.",
                ephemeral=True,
            )
            return

        local_pub_time = scheduled_event.start_time.astimezone(self.config.timezone)
        pub = await self._choose_pub(
            interaction,
            f"Please choose the new pub for {local_pub_time}",
        )

        if pub.id == original_pub_event.pub.id:
            await interaction.followup.send(
                f"The pub is already at {pub.name}.",
                ephemeral=True,
            )
            return

        pub_event = await self.api_client.update_pub_event(original_pub_event.id, pub_id=pub.id)

        await scheduled_event.edit(location=pub.name)

        pub_channel = interaction.guild.get_channel(self.config.pub.channel_id)
        assert isinstance(pub_channel, discord.TextChannel)

        LOGGER.info(f"Posting updated pub info in {pub_channel}")
        formatted_pub_name = get_formatted_pub_name(pub, self.config)

        if original_pub_event is not None:
            tags = " ".join(
                f"<@{attendee.discord_id}>"
                for attendee in pub_event.attendees
                if attendee.discord_id
            )
        else:
            # Nobody to tag if we don't have a pub event.
            tags = ""

        if scheduled_event.start_time < datetime.now(tz=self.config.timezone):
            content = "\n".join(
                [
                    "**Pub has moved!**",
                    f"The pub at will be at {formatted_pub_name} instead!",
                    "",
                    tags,
                ],
            )
        else:
            content = "\n".join(
                [
                    "**New Location of Next Pub**",
                    f"The next pub will be <t:{int(scheduled_event.start_time.timestamp())}:R>",
                    f"It will be held at {formatted_pub_name} instead of the previous location.",
                    "",
                    tags,
                ],
            )

        await pub_channel.send(
            content,
            view=get_pub_buttons_view(pub),
        )

    @command(description="Update the table number for the current pub event")
    @describe(
        table_number="The table number",
    )
    async def table(self, interaction: discord.Interaction, table_number: int) -> None:
        assert interaction.guild
        if table_number <= 0:
            await interaction.response.send_message(
                "Sorry, the table number must exist in this dimension.",
                ephemeral=True,
            )
            return

        event = self._get_next_pub_scheduled_event(interaction.guild, ignore_time=True)
        if event is None:
            LOGGER.info("No pub exists.")
            await interaction.response.send_message(
                "There doesn't appear to be a pub at this time.",
                ephemeral=True,
            )
            return

        pub_event = await self.api_client.get_pub_event_by_discord_id(event.id)
        if pub_event is None:
            await interaction.response.send_message(
                "Cannot set the table number. Unable to find the current pub event in the database.",
                ephemeral=True,
            )
            return

        pub = pub_event.pub
        await self.api_client.update_table_for_pub_event(pub_event.id, table_number)

        await interaction.response.send_message(
            f"Set table number to {table_number}, thanks.",
            ephemeral=True,
        )

        await event.edit(location=f"{pub.name} - Table {table_number}")

        pub_channel = interaction.guild.get_channel(self.config.pub.channel_id)
        assert isinstance(pub_channel, discord.TextChannel)

        LOGGER.info(f"Posting pub table info in {pub_channel}")
        formatted_pub_name = f"{pub.emoji} **{pub.name}** {self.config.pub.supplemental_emoji}"
        await pub_channel.send(
            "\n".join(
                [
                    "**Pub Table**",
                    f"We are at table {table_number} in {formatted_pub_name}",
                ],
            ),
            view=get_pub_buttons_view(pub),
        )

    @command(description="Announce that you've booked a table for the next pub event")
    @describe(
        table_size="The table size",
    )
    async def booked(self, interaction: discord.Interaction, table_size: int) -> None:
        assert interaction.guild
        if table_size <= 0:
            await interaction.response.send_message(
                "Sorry, the table size must be at least 1.",
                ephemeral=True,
            )
            return

        event = self._get_next_pub_scheduled_event(interaction.guild, ignore_time=True)
        if event is None:
            LOGGER.info("No pub exists.")
            await interaction.response.send_message(
                "There doesn't appear to be a pub at this time.",
                ephemeral=True,
            )
            return

        pub_event = await self.api_client.get_pub_event_by_discord_id(event.id)
        if pub_event is None:
            await interaction.response.send_message(
                "Cannot mark the table as booked. Unable to find the current pub event in the database.",
                ephemeral=True,
            )
            return

        pub = pub_event.pub
        person = await self.api_client.get_person_for_discord_member(interaction.user)

        try:
            await self.api_client.create_pub_booking(pub_event.id, table_size, person.id)
        except PubBookingAlreadyExistsError:
            await interaction.response.send_message(
                "A table has already been booked for this pub event.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            f"Thanks for booking a table for {table_size}.",
            ephemeral=True,
        )

        pub_channel = interaction.guild.get_channel(self.config.pub.channel_id)
        assert isinstance(pub_channel, discord.TextChannel)

        LOGGER.info(f"Posting pub booked info in {pub_channel}")
        formatted_pub_name = f"{pub.emoji} **{pub.name}** {self.config.pub.supplemental_emoji}"
        await pub_channel.send(
            "\n".join(
                [
                    "**Pub is booked!**",
                    f"We are booked for {table_size} people in {formatted_pub_name}",
                ],
            ),
            view=get_pub_buttons_view(pub),
        )

    @command(description="Get info on how to use the /pub command.")  # type: ignore[arg-type]
    async def help(self, interaction: discord.Interaction) -> None:  # noqa: A003
        LOGGER.info(f"{interaction.user} used /pub next")
        assert interaction.guild is not None

        await interaction.response.send_message(
            "\n".join(
                [
                    "I manage the pub events, and keep data up to date between systems.",
                    "Please don't edit the pub events manually, it confuses me!",
                    "Some people have auto opt-in for pub events, so use me to notify people of changes",
                    "",
                    "**Commands**",
                    "/pub next - create the next pub event, if needed",
                    "/pub booked <table_size> - announce that you've booked a table for the next pub",
                    "/pub table <table_no> - add the table number and let others know",
                    "/pub attendees - get the people coming to the next pub, including AutoPub attendees",
                    "/pub change - move the location of the pub and ping all attendees.",
                    "/pub link - get a link to the website",
                    "/pub autoskip - if autopubbed, you can use this to opt-out of the next pub event",
                ],
            ),
            ephemeral=True,
        )

    @command(description="Get a link to the web service")  # type: ignore[arg-type]
    async def link(self, interaction: discord.Interaction) -> None:  # noqa: A003
        LOGGER.info(f"{interaction.user} used /pub link")
        assert interaction.guild is not None

        await interaction.response.send_message(
            "Here you go:\n" + self.config.pub.web_url, ephemeral=True
        )

    @command(description="If autopubbed, you can use this to opt-out of the next pub event")
    async def autoskip(self, interaction: discord.Interaction) -> None:
        assert interaction.guild

        person = await self.api_client.get_person_for_discord_member(interaction.user)

        try:
            tombstone = await self.api_client.create_pub_event_tombstone(person.id)
        except PubEventTombstoneAlreadyExistsError:
            await interaction.response.send_message(
                "You have already opted out of the next pub event",
                ephemeral=True,
            )
            return

        if tombstone.pub_event is None:
            # No next pub event scheduled yet - tombstone will be linked when one is created
            await interaction.response.send_message(
                "You've opted out of the next scheduled pub. Your preference will be applied when an event is created.",
                ephemeral=True,
            )
        else:
            # Next pub event exists - tombstone is linked and RSVP updated
            await interaction.response.send_message(
                "You've opted out of the next scheduled pub event.",
                ephemeral=True,
            )
