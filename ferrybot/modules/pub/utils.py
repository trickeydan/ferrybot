import discord

from ferrybot.api import PubSchema
from ferrybot.config import BotConfig


def event_is_pub(event: discord.ScheduledEvent) -> bool:
    return "Pub" in event.name


def get_pub_buttons_view(pub: PubSchema) -> discord.ui.View:
    view = discord.ui.View()
    view.add_item(discord.ui.Button(label="Map", url=str(pub.map_url)))
    if pub.menu_url:
        view.add_item(discord.ui.Button(label="Menu", url=str(pub.menu_url)))
    return view


def get_formatted_pub_name(pub: PubSchema, config: BotConfig) -> str:
    return f"{pub.emoji} **{pub.name}** {config.pub.supplemental_emoji}"
