from pathlib import Path
from zoneinfo import ZoneInfo

import tomllib
from pydantic import BaseModel, ValidationError, validator
from pydantic_settings import BaseSettings


class ConfigError(Exception):
    """There was a problem with the config file."""


class DiscordConfig(BaseModel):
    token: str
    guild_id: int


class PubConfig(BaseModel):
    supplemental_emoji: str = "🍺"
    channel_id: int
    description: str
    weekday: int
    hour: int
    minute: int = 0
    web_url: str


class FerryConfig(BaseModel):
    api_url: str
    api_key: str
    channel_id: int
    banned_word: str
    emoji_reacts: str


class BotConfig(BaseSettings):
    timezone: ZoneInfo
    discord: DiscordConfig
    ferry: FerryConfig
    pub: PubConfig

    class Config:
        env_nested_delimiter = "__"

    @validator("timezone", pre=True)
    def parse_timezone(cls, val: str) -> ZoneInfo:  # noqa: N805
        return ZoneInfo(val)

    @classmethod
    def load_from_file(cls, path: Path) -> "BotConfig":  # noqa: ANN102
        try:
            with path.open("rb") as fh:
                data = tomllib.load(fh)
        except FileNotFoundError as e:
            raise ConfigError("Unable to find config file") from e
        except OSError as e:
            raise ConfigError("Unable to read config file.") from e
        except tomllib.TOMLDecodeError as e:
            raise ConfigError(f"Unable to parse TOML: {e}") from e

        try:
            return cls.model_validate(data)
        except ValidationError as e:
            raise ConfigError(f"Config file did not match schema: {e}") from e
