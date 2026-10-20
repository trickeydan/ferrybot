import logging
from datetime import datetime, time, timedelta
from typing import TYPE_CHECKING

import discord
from discord import EventStatus
from discord.ext import tasks

from ferrybot.api import FerryAPI

from ..module import Module
from .commands import PubCommand
from .utils import event_is_pub, get_formatted_pub_name, get_pub_buttons_view

if TYPE_CHECKING:
    from ferrybot.client import DiscordClient


LOGGER = logging.getLogger(__name__)


class PubModule(Module):
    def __init__(self, client: "DiscordClient", api_client: FerryAPI) -> None:
        self.client = client
        self.api_client = api_client
        client.tree.add_command(PubCommand(client.config, api_client), guild=client.guild)

    async def setup_hook(self, client: "DiscordClient") -> None:
        if self.table_booking_reminder.is_running():
            return

        config = client.config
        reminder_minutes = (
            config.pub.hour * 60 + config.pub.minute - config.pub.booking_reminder_hours * 60
        )
        reminder_day_offset, reminder_minutes = divmod(reminder_minutes, 24 * 60)
        reminder_hour, reminder_minute = divmod(reminder_minutes, 60)
        reminder_weekday = (config.pub.weekday + reminder_day_offset) % 7
        self._reminder_weekday = reminder_weekday
        self.table_booking_reminder.change_interval(
            time=time(
                hour=reminder_hour,
                minute=reminder_minute,
                tzinfo=config.timezone,
            )
        )
        LOGGER.info(
            "Starting pub booking reminder for weekday %s at %02d:%02d (%s)",
            reminder_weekday,
            reminder_hour,
            reminder_minute,
            config.timezone,
        )
        self.table_booking_reminder.start()

    @tasks.loop(time=time(hour=0))
    async def table_booking_reminder(self) -> None:
        config = self.client.config
        now = datetime.now(tz=config.timezone)
        if now.weekday() != self._reminder_weekday:
            return

        if not isinstance(self.client.guild, discord.Guild):
            LOGGER.error("Cannot send pub booking reminder without a connected guild.")
            return

        pub_channel = self.client.get_channel(config.pub.channel_id)
        if not isinstance(pub_channel, discord.TextChannel):
            LOGGER.error("Cannot send pub booking reminder: pub channel was not found.")
            return

        events = await self.client.guild.fetch_scheduled_events()
        LOGGER.info("Checking %d scheduled events for pub booking reminders.", len(events))
        for event in events:
            if (
                not event_is_pub(event)
                or event.status is not EventStatus.scheduled
                or not timedelta(0)
                < event.start_time - now
                <= timedelta(hours=config.pub.booking_reminder_hours, minutes=30)
            ):
                continue

            pub_event = await self.api_client.get_pub_event_by_discord_id(event.id)
            if pub_event is None:
                LOGGER.error(
                    "Cannot send pub booking reminder: pub event was not found in the API."
                )
                continue
            if pub_event.booking is not None:
                LOGGER.info("Skipping pub booking reminder; a table is already booked.")
                continue

            expected_booker = pub_event.expected_booker
            if expected_booker is None or expected_booker.discord_id is None:
                LOGGER.info("Skipping pub booking reminder; expected booker has no Discord ID.")
                continue

            message = [
                "**No table has been booked for the pub in "
                f"about {config.pub.booking_reminder_hours} hours!**",
                "Could someone book one using `/pub booked`?",
            ]
            if pub_event.pub.booking_url is not None:
                message.append(f"Booking link: {pub_event.pub.booking_url}")
            message.append(f"<@{expected_booker.discord_id}>")

            await pub_channel.send(
                "\n".join(message),
                allowed_mentions=discord.AllowedMentions(
                    users=True,
                    roles=False,
                    everyone=False,
                ),
            )

    @table_booking_reminder.before_loop
    async def before_table_booking_reminder(self) -> None:
        await self.client.wait_until_ready()

    async def on_scheduled_event_create(
        self,
        client: "DiscordClient",
        event: discord.ScheduledEvent,
    ) -> None:
        creator = event.creator
        if not creator:
            return

        if event_is_pub(event):
            bot_user = self.client.user
            assert bot_user
            if creator.id != bot_user.id:
                LOGGER.warning("A pub event was manually created.")
                await event.delete(reason="Removing manually created pub event")
                await creator.send(
                    "I've deleted your manually created pub event. Please use /pub next."
                )
        else:
            assert isinstance(self.client.guild, discord.Guild)
            await creator.send(
                f'Hey, I just say that you created an event "{event.name}" for {self.client.guild.name}\n'
                "That event doesn't look like a pub event, but if it is I'm going to ignore it."
            )

    async def on_scheduled_event_update(
        self,
        client: "DiscordClient",
        old_event: discord.ScheduledEvent,
        new_event: discord.ScheduledEvent,
    ) -> None:
        if event_is_pub(old_event):
            await self.handle_pub_event_change(client, old_event, new_event)

    async def on_scheduled_event_user_add(
        self, client: "DiscordClient", event: discord.ScheduledEvent, user: discord.User
    ) -> None:
        if event_is_pub(event):
            pub_event = await self.api_client.get_pub_event_by_discord_id(event.id)
            if pub_event:
                person = await self.api_client.get_person_for_discord_member(user)
                await self.api_client.add_attendee_to_pub_event(pub_event.id, person.id)
                LOGGER.info(f"Added {person.display_name} to {pub_event}")

    async def on_scheduled_event_user_remove(
        self, client: "DiscordClient", event: discord.ScheduledEvent, user: discord.User
    ) -> None:
        if event_is_pub(event):
            pub_event = await self.api_client.get_pub_event_by_discord_id(event.id)
            if pub_event:
                person = await self.api_client.get_person_for_discord_member(user)
                pub_event = await self.api_client.remove_attendee_from_pub_event(
                    pub_event.id, person.id
                )

                if pub_event:
                    attendee_ids = {a.id for a in pub_event.attendees}
                    if person.id in attendee_ids:
                        await user.send(
                            f"You have removed your interest from the pub on {pub_event.timestamp}, but you are still registered on the pub system. Please log in and RSVP."
                        )
                    else:
                        LOGGER.info(f"Removed {person.display_name} from {pub_event}")

    async def handle_pub_event_change(
        self,
        client: "DiscordClient",
        old_event: discord.ScheduledEvent,
        new_event: discord.ScheduledEvent,
    ) -> None:
        self.pub_channel = client.get_channel(client.config.pub.channel_id)
        assert isinstance(self.pub_channel, discord.TextChannel)

        if old_event.status is not EventStatus.active and new_event.status is EventStatus.active:
            # The Pub has started.
            LOGGER.info("A pub event has started.")

            pub_event = await self.api_client.get_pub_event_by_discord_id(new_event.id)
            if not pub_event:
                LOGGER.error("Pub Event does not exist.")
                return
            pub = pub_event.pub
            formatted_pub_name = get_formatted_pub_name(pub, self.client.config)
            await self.pub_channel.send(
                "\n".join(
                    [
                        "**Pub-O-Clock**",
                        f"We are at {formatted_pub_name}",
                        "",
                        "Please let others know the table by using /pub table",
                    ],
                ),
                view=get_pub_buttons_view(pub),
            )

            if pub_event.announcements:
                header = [
                    "**📢 Pub Announcements 📢**",
                    "",
                ]
                await self.pub_channel.send(
                    "\n".join(header + [f"* {a}" for a in pub_event.announcements]),
                    view=get_pub_buttons_view(pub),
                )

        if (
            old_event.status is not EventStatus.completed
            and new_event.status is EventStatus.completed
        ):
            # The Pub has ended.
            LOGGER.info("A pub event has ended.")
            await self.pub_channel.send(
                "The pub is over. You are still not allowed to say that word.",
            )
