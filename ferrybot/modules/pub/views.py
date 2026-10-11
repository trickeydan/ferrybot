import asyncio

import discord

from ferrybot.api import PubSchema


class PubSelector(discord.ui.Select):
    def __init__(self, pubs: list[PubSchema], prompt: str) -> None:
        self._pubs = pubs
        self.prompt = prompt

        self.selected = asyncio.Event()
        self.pub: PubSchema | None = None

        options = [discord.SelectOption(label=pub.name, emoji=pub.emoji) for pub in pubs]

        super().__init__(
            placeholder="Choose a pub...",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        self.pub = discord.utils.find(
            lambda p: p.name == self.values[0],
            self._pubs,
        )
        if self.pub:
            await interaction.response.edit_message(
                content=f"{self.prompt}\n {self.pub.emoji} {self.pub.name} has been selected",  # noqa: E501
                view=None,
            )
        self.selected.set()


class PubView(discord.ui.View):
    def __init__(self, pubs: list[PubSchema], prompt: str) -> None:
        super().__init__()

        self.pub_selector = PubSelector(pubs, prompt)
        self.add_item(self.pub_selector)

    async def wait_until_complete(self) -> PubSchema:
        await self.pub_selector.selected.wait()
        if self.pub_selector.pub is not None:
            return self.pub_selector.pub
        else:
            raise RuntimeError("No pub was selected.")
