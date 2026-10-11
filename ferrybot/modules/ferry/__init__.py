from __future__ import annotations

import asyncio
from logging import getLogger
import re
from typing import TYPE_CHECKING

import discord

from ferrybot.modules import Module
from ferrybot.api import FerryAPI

from .commands import FerryCommand
from .modals import AccuseModal

if TYPE_CHECKING:
    from ferrybot.client import DiscordClient

LOGGER = getLogger(__name__)


class FerryModule(Module):
    def __init__(self, client: DiscordClient, api_client: FerryAPI) -> None:
        self.client = client
        self.command_group = FerryCommand(client.config, self)
        self.api_client = api_client
        client.tree.add_command(self.command_group, guild=client.guild)
        client.tree.context_menu(name="Accuse of Ferrying", guild=client.guild)(
            self.accuse_context_menu
        )

        if hasattr(client, "on_message"):
            raise RuntimeError(
                "Only one module can have on_message at the moment.",
            )
        else:
            client.on_message = self.on_message  # type: ignore[attr-defined]

        if hasattr(client, "on_reaction_add"):
            raise RuntimeError(
                "Only one module can have on_reaction_add at the moment.",
            )
        else:
            client.on_reaction_add = self.on_reaction_add  # type: ignore[attr-defined]

    @property
    def channel(self) -> discord.TextChannel:
        channel = self.client.get_channel(self.client.config.ferry.channel_id)
        assert isinstance(channel, discord.TextChannel)
        return channel

    async def on_ready(self, client: DiscordClient) -> None:
        user = await self.api_client.get_current_user()
        LOGGER.info(f"Authenticated to Ferry API as {user.username}")

    async def on_reaction_add(self, reaction: discord.Reaction, user: discord.User) -> None:
        pass

    async def on_message(self, message: discord.Message) -> None:
        assert self.client.user
        pattern = rf"\b{self.client.config.ferry.banned_word}\b"
        if message.author != self.client.user and re.match(
            pattern, message.content, flags=re.IGNORECASE
        ):
            LOGGER.info(f"{message.author.display_name} ferried in #{message.channel}")
            for emoji in self.client.config.ferry.emoji_reacts:
                asyncio.create_task(message.add_reaction(emoji))

            await self.command_group.publish_accusation(
                message.author,
                self.client.user,
                quote=message.content,
            )

    async def accuse_context_menu(
        self, interaction: discord.Interaction, member: discord.Member
    ) -> None:
        await interaction.response.send_modal(AccuseModal(self, criminal=member))
