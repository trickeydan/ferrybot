import logging
from typing import TYPE_CHECKING

import discord
from discord import EventStatus

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
            pub = await self.api_client.get_pub(pub_event.pub)
            if not pub:
                LOGGER.error("Pub does not exist.")
                return

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
