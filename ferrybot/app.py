import argparse
import asyncio
from logging import getLogger
from pathlib import Path

import discord

from .client import DiscordClient
from .config import BotConfig, ConfigError

LOGGER = getLogger(__name__)


async def run(client: DiscordClient, token: str) -> None:
    LOGGER.info("Starting client.")
    async with client:
        await client.login(token)
        await client.connect()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--config", type=str, default="config.toml")
    return parser.parse_args()


def app() -> None:
    args = parse_args()
    discord.utils.setup_logging()

    try:
        LOGGER.info(f"Loading {args.config}")
        config = BotConfig.load_from_file(Path(args.config))
    except ConfigError as e:
        LOGGER.error("The config file was not valid")
        LOGGER.error(str(e))
        return

    try:
        client = DiscordClient(config)
        asyncio.run(run(client, config.discord.token))
    except KeyboardInterrupt:
        pass
