from __future__ import annotations

from http import HTTPStatus
from logging import getLogger
import re
import typing
from uuid import UUID
import discord
import httpx

from ferrybot.api import AccusationSchema

if typing.TYPE_CHECKING:
    from ferrybot.modules.ferry import FerryModule

LOGGER = getLogger(__name__)


class RatifyButton(discord.ui.Button):
    def __init__(self, *args, ferry_module: FerryModule, **kwargs):
        super().__init__(*args, **kwargs)
        self._api_client = ferry_module.api_client  # type: ignore[has-type]
        self._ferry_module = ferry_module

    def get_accusation_id(self) -> UUID | None:
        if ma := re.match(r"button:ratify:(.*)", self.custom_id or ""):
            return UUID(ma.group(1))
        return None

    async def callback(self, interaction: discord.Interaction) -> None:
        accusation_id = self.get_accusation_id()

        try:
            accusation = await self._api_client.get_accusation(accusation_id or UUID(int=0))
            suspect = await self._api_client.get_person(accusation.suspect.id)
            ratifier = await self._api_client.get_person_for_discord_member(interaction.user)
        except httpx.HTTPStatusError as exc:
            LOGGER.exception(exc)
            await interaction.response.send_message(
                "An error occurred during ratification", ephemeral=True
            )
            return

        if accusation.created_by.id == ratifier.id:
            await interaction.response.send_message(
                "You cannot ratify an accusation that you made!", ephemeral=True
            )
            return

        if accusation.suspect.id == ratifier.id:
            await interaction.response.send_message(
                "You cannot ratify an accusation made against you!", ephemeral=True
            )
            return

        try:
            assert accusation_id is not None
            ratification = await self._api_client.create_ratification(accusation_id, ratifier.id)
            await interaction.response.edit_message(view=None)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == HTTPStatus.CONFLICT:
                await interaction.response.edit_message(view=None)
                await interaction.followup.send(
                    "That accusation has already been ratified.",
                    ephemeral=True,
                )
            else:
                LOGGER.exception(exc)
                await interaction.response.send_message(
                    "An error occurred during ratification", ephemeral=True
                )
            return

        lines = [
            f"The accusation has been ratified by {interaction.user.mention}",
            "",
            f"{suspect.get_display_for_message()} has been sentenced to {ratification.consequence.content}",
        ]
        await interaction.followup.send("\n".join(lines))

        leaderboard = await self._ferry_module.command_group.get_leaderboard()  # type: ignore[has-type]
        await self._ferry_module.channel.send(leaderboard)


class RatifyAccusationView(discord.ui.View):
    def __init__(self, ferry_module: FerryModule, accusation: AccusationSchema):
        super().__init__(timeout=None)

        self.add_item(
            RatifyButton(
                ferry_module=ferry_module,
                label="Ratify",
                style=discord.ButtonStyle.primary,
                custom_id=f"button:ratify:{accusation.id}",
            )
        )
