from __future__ import annotations

from logging import getLogger
from typing import TYPE_CHECKING

import discord
from discord.app_commands import Group, command, describe
import httpx

from ferrybot.config import BotConfig
from ferrybot.modules.ferry.views import RatifyAccusationView

from .modals import AccuseModal

LOGGER = getLogger(__name__)

if TYPE_CHECKING:
    from . import FerryModule


class FerryCommand(Group):
    def __init__(self, config: BotConfig, module: FerryModule) -> None:
        super().__init__(name="ferry", description="Interact with ferries.")
        self.config = config
        self.ferry_module = module

    async def get_leaderboard(self) -> str:
        people = await self.ferry_module.api_client.get_leaderboard()  # type: ignore[has-type]
        content = [
            f"{person.get_display_for_message()} {person.ferry_sequence}" for person in people
        ]
        return "\n".join(["Bad people:"] + content)

    async def publish_accusation(
        self,
        criminal: discord.User | discord.Member,
        accuser: discord.User | discord.ClientUser | discord.Member,
        quote: str,
    ) -> None:
        try:
            person_criminal = await self.ferry_module.api_client.get_person_for_discord_member(  # type: ignore[has-type]
                criminal
            )
            person_accuser = await self.ferry_module.api_client.get_person_for_discord_member(  # type: ignore[has-type]
                accuser
            )
        except httpx.HTTPStatusError as exc:
            LOGGER.exception(exc)
            return

        accusation = await self.ferry_module.api_client.create_accusation(  # type: ignore[has-type]
            created_by=person_accuser.id,
            suspect=person_criminal.id,
            quote=quote,
        )
        lines = [
            f"{criminal.mention} has been accused of a heinous crime by {accuser.mention}",
        ]
        if quote:
            lines.extend(["", f"> {quote}"])

        lines.extend(
            ["", f"If you agree that {criminal.mention} is guilty please ratify the accusation."]
        )

        view = RatifyAccusationView(self.ferry_module, accusation)

        # Publish the accusation
        await self.ferry_module.channel.send("\n".join(lines), view=view)

    @command(description="Accuse somebody of ferrying.")  # type: ignore[arg-type]
    @describe(member="The criminal you are accusing.")
    async def accuse(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
    ) -> None:
        LOGGER.info(f"{interaction.user} used /ferry accuse")

        if interaction.user == member:
            await interaction.response.send_message("Who watches the watchman?", ephemeral=True)
            return

        await interaction.response.send_modal(AccuseModal(self.ferry_module, criminal=member))

    @command(description="Get the current scoreboard")
    async def scoreboard(self, interaction: discord.Interaction) -> None:
        LOGGER.info(f"{interaction.user} used /ferry scoreboard")
        leaderboard = await self.get_leaderboard()
        await interaction.response.send_message(leaderboard, ephemeral=True)
