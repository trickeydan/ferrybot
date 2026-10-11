import asyncio
import logging

import discord
from discord import app_commands


from .api import FerryAPI
from .config import BotConfig
from .modules import MODULES, Module

LOGGER = logging.getLogger(__name__)


class DiscordClient(discord.Client):
    def __init__(self, config: BotConfig) -> None:
        super().__init__(intents=self.intents)

        self.config = config
        self.guild: discord.Object | discord.Guild = discord.Object(config.discord.guild_id)
        self.tree = app_commands.CommandTree(self)
        self.api_client = FerryAPI(self.config.ferry.api_url, self.config.ferry.api_key)

        self._modules: list[Module] = [module_cls(self, self.api_client) for module_cls in MODULES]
        LOGGER.info(f"Set up {len(self._modules)} modules")

    @property
    def intents(self) -> discord.Intents:
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        intents.guild_scheduled_events = True
        return intents

    async def setup_hook(self) -> None:
        # Sync the application command with Discord.
        LOGGER.info("Synchronising app commands")
        commands = await self.tree.sync(guild=self.guild)
        for command in commands:
            LOGGER.info(f"Registered /{command.name}")

    async def on_ready(self) -> None:
        LOGGER.info(f"Logged on as {self.user}!")

        if len(guilds := [guild async for guild in self.fetch_guilds()]) != 1:
            raise RuntimeError(
                f"Expected to connect to exactly 1 guild, found {len(guilds)}",
            )
        self.guild = guilds[0]
        LOGGER.info(f"Guild: {self.guild}")

        for module in self._modules:
            asyncio.create_task(module.on_ready(self))

    async def on_scheduled_event_create(
        self,
        event: discord.ScheduledEvent,
    ) -> None:
        LOGGER.info(f"Received create for scheduled event: {event.name}")
        for module in self._modules:
            asyncio.create_task(module.on_scheduled_event_create(self, event))

    async def on_scheduled_event_update(
        self,
        old_event: discord.ScheduledEvent,
        new_event: discord.ScheduledEvent,
    ) -> None:
        LOGGER.info(f"Received update for scheduled event: {old_event.name}")
        for module in self._modules:
            asyncio.create_task(module.on_scheduled_event_update(self, old_event, new_event))

    async def on_scheduled_event_user_add(
        self, event: discord.ScheduledEvent, user: discord.User
    ) -> None:
        LOGGER.info(f"{user} joined {event.name}")
        for module in self._modules:
            asyncio.create_task(module.on_scheduled_event_user_add(self, event, user))

    async def on_scheduled_event_user_remove(
        self, event: discord.ScheduledEvent, user: discord.User
    ) -> None:
        LOGGER.info(f"{user} left {event.name}")
        for module in self._modules:
            asyncio.create_task(module.on_scheduled_event_user_remove(self, event, user))
