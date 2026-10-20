from datetime import datetime
from logging import getLogger
from typing import Any
from uuid import UUID
import discord
import httpx
from pydantic import BaseModel, TypeAdapter, HttpUrl, validator

LOGGER = getLogger(__name__)


class UserSchema(BaseModel):
    username: str


class PersonSchema(BaseModel):
    id: UUID
    display_name: str
    discord_id: int | None
    created_at: datetime
    updated_at: datetime

    def get_display_for_message(self) -> str:
        if self.discord_id:
            return f"<@{self.discord_id}>"
        return self.display_name


class PersonWithScoreSchema(PersonSchema):
    current_score: float
    ferry_sequence: str


class PersonLinkSchema(BaseModel):
    id: UUID
    display_name: str


class PersonLinkWithDiscordSchema(PersonLinkSchema):
    discord_id: int | None


class ConsequenceLinkSchema(BaseModel):
    id: UUID
    content: str


class RatificationSchema(BaseModel):
    id: UUID
    consequence: ConsequenceLinkSchema
    created_by: PersonLinkSchema
    created_at: datetime
    updated_at: datetime


class AccusationSchema(BaseModel):
    id: UUID
    quote: str
    suspect: PersonLinkSchema
    created_by: PersonLinkSchema
    ratification: RatificationSchema | None
    created_at: datetime
    updated_at: datetime


class PubSchema(BaseModel):
    id: UUID
    name: str
    emoji: str
    menu_url: HttpUrl | None = None
    map_url: HttpUrl
    booking_url: HttpUrl | None = None

    @validator("menu_url", pre=True)
    def parse_menu_url(cls, val: str) -> str | None:
        return val if val else None

    @validator("booking_url", pre=True)
    def parse_booking_url(cls, val: str) -> str | None:
        return val if val else None


class PubLinkSchema(BaseModel):
    id: UUID
    name: str


class PubTableSchema(BaseModel):
    id: UUID
    pub: PubLinkSchema
    number: int


class PubBookingSchema(BaseModel):
    id: UUID
    table_size: int
    created_by: UUID


class PubBookingCreateSchema(BaseModel):
    table_size: int
    created_by: UUID


class PubBookingAlreadyExistsError(Exception):
    pass


class PubEventSchema(BaseModel):
    id: UUID
    timestamp: datetime
    pub: PubSchema
    discord_id: int | None
    table: PubTableSchema | None
    booking: PubBookingSchema | None
    attendees: list[PersonLinkWithDiscordSchema]
    tombstoned_attendees: list[PersonLinkWithDiscordSchema]
    expected_booker: PersonLinkWithDiscordSchema | None
    announcements: list[str]


class PubEventTombstoneSchema(BaseModel):
    id: UUID
    person: UUID
    pub_event: UUID | None


class PubEventTombstoneAlreadyExistsError(Exception):
    pass


class FerryAPI:
    def __init__(self, api_url: str, api_key: str) -> None:
        self._api_url = api_url
        self._api_key = api_key

        self._client = httpx.AsyncClient()

    async def _request(
        self, method: str, endpoint: str, *, if_404_then_none: bool = False, **kwargs
    ) -> Any:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }
        LOGGER.info(f"{method} {endpoint} -> {kwargs}")
        resp = await self._client.request(
            method, self._api_url + endpoint, headers=headers, **kwargs
        )
        if if_404_then_none and resp.status_code == 404:
            return None

        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            LOGGER.error(str(e))
            LOGGER.error(resp.content)
            raise

        data = resp.json()
        LOGGER.info(f"{method} {endpoint} -> {resp.status_code} {data} ")
        return data

    async def get_current_user(self) -> UserSchema:
        data = await self._request("GET", "v2/users/me/")
        return UserSchema.model_validate(data)

    async def get_leaderboard(
        self,
    ) -> list[PersonWithScoreSchema]:
        data = await self._request("GET", "v2/people/?ordering=-current_score&limit=12")
        ta = TypeAdapter(list[PersonWithScoreSchema])
        return ta.validate_python(data["results"])

    async def get_person(self, person_id: UUID) -> PersonSchema:
        data = await self._request("GET", f"v2/people/{person_id}/")
        return PersonSchema.model_validate(data)

    async def get_person_for_discord_member(
        self, member: discord.User | discord.ClientUser | discord.Member
    ) -> PersonSchema:
        try:
            data = await self._request("GET", f"v2/people/?discord_id={member.id}")
        except httpx.HTTPStatusError as exc:
            raise exc

        ta = TypeAdapter(list[PersonSchema])
        try:
            return ta.validate_python(data["results"])[0]
        except IndexError:
            pass

        LOGGER.info(f"Creating new person for {member}")
        payload = {"display_name": member.display_name, "discord_id": member.id}
        data = await self._request("POST", "v2/people/", json=payload)
        return PersonSchema.model_validate(data)

    async def create_accusation(
        self, created_by: UUID, suspect: UUID, quote: str
    ) -> AccusationSchema:
        payload = {
            "quote": quote,
            "suspect": str(suspect),
            "created_by": str(created_by),
        }
        data = await self._request("POST", "v2/court/accusations/", json=payload)
        return AccusationSchema.model_validate(data)

    async def get_accusation(self, accusation_id: UUID) -> AccusationSchema:
        data = await self._request("GET", f"v2/court/accusations/{accusation_id}/")
        return AccusationSchema.model_validate(data)

    async def create_ratification(
        self, accusation_id: UUID, created_by: UUID
    ) -> RatificationSchema:
        payload = {
            "created_by": str(created_by),
        }
        data = await self._request(
            "POST", f"v2/court/accusations/{accusation_id}/ratification/", json=payload
        )
        return RatificationSchema.model_validate(data)

    async def get_pubs(
        self,
    ) -> list[PubSchema]:
        data = await self._request("GET", "v2/pub/pubs/")
        ta = TypeAdapter(list[PubSchema])
        return ta.validate_python(data["results"])

    async def get_pub(
        self,
        pub_id: UUID,
    ) -> PubSchema | None:
        data = await self._request("GET", f"v2/pub/pubs/{pub_id}/", if_404_then_none=True)
        if data is None:
            return None
        return PubSchema.model_validate(data)

    async def create_pub_event(
        self,
        timestamp: datetime,
        pub_id: UUID,
        created_by: UUID,
        scheduled_event_id: int,
    ) -> None:
        payload = {
            "timestamp": timestamp.isoformat(),
            "pub": str(pub_id),
            "discord_id": scheduled_event_id,
            "table": None,
            "created_by": str(created_by),
        }
        await self._request("POST", "v2/pub/events/", json=payload)

    async def update_pub_event(
        self,
        event_id: UUID,
        *,
        timestamp: datetime | None = None,
        pub_id: UUID | None = None,
    ) -> PubEventSchema:
        payload = {}

        if timestamp is not None:
            payload["timestamp"] = timestamp.isoformat()

        if pub_id is not None:
            payload["pub"] = str(pub_id)

        data = await self._request("PATCH", f"v2/pub/events/{event_id}/", json=payload)
        return PubEventSchema.model_validate(data)

    async def get_pub_event_by_discord_id(self, scheduled_event_id: int) -> PubEventSchema | None:
        try:
            data = await self._request("GET", f"v2/pub/events/?discord_id={scheduled_event_id}")
        except httpx.HTTPStatusError as exc:
            raise exc

        ta = TypeAdapter(list[PubEventSchema])
        try:
            return ta.validate_python(data["results"])[0]
        except IndexError:
            return None

    async def add_attendee_to_pub_event(self, pub_event_id: UUID, person_id: UUID) -> None:
        payload = {
            "person": str(person_id),
        }
        try:
            await self._request(
                "POST", f"v2/pub/events/{pub_event_id}/attendees/add/", json=payload
            )
        except httpx.HTTPStatusError as exc:
            LOGGER.exception(exc)

    async def remove_attendee_from_pub_event(
        self, pub_event_id: UUID, person_id: UUID
    ) -> PubEventSchema | None:
        payload = {
            "person": str(person_id),
        }
        try:
            data = await self._request(
                "POST", f"v2/pub/events/{pub_event_id}/attendees/remove/", json=payload
            )
            return PubEventSchema.model_validate(data)
        except httpx.HTTPStatusError as exc:
            LOGGER.exception(exc)
            return None

    async def update_table_for_pub_event(self, pub_event_id: UUID, table_number: int) -> None:
        payload = {
            "table_number": table_number,
        }
        try:
            await self._request("POST", f"v2/pub/events/{pub_event_id}/table/", json=payload)
        except httpx.HTTPStatusError as exc:
            LOGGER.exception(exc)

    async def create_pub_booking(
        self, pub_event_id: UUID, table_size: int, created_by: UUID
    ) -> PubBookingSchema:
        payload = {
            "table_size": table_size,
            "created_by": str(created_by),
        }
        try:
            data = await self._request(
                "POST", f"v2/pub/events/{pub_event_id}/booking/", json=payload
            )
            # The API returns a full PubEventSchema, extract the booking
            event = PubEventSchema.model_validate(data)
            if event.booking is None:
                raise ValueError("Booking was created but is None in response")
            return event.booking
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 409:
                LOGGER.warning(f"Booking already exists for pub event {pub_event_id}")
                raise PubBookingAlreadyExistsError()
            raise

    async def create_pub_event_tombstone(self, person_id: UUID) -> PubEventTombstoneSchema:
        payload = {
            "person": str(person_id),
        }
        try:
            data = await self._request("POST", "v2/pub/events/tombstones/", json=payload)
            return PubEventTombstoneSchema.model_validate(data)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 409:
                LOGGER.warning(f"Tombstone already exists for person {person_id}")
                raise PubEventTombstoneAlreadyExistsError()
            raise
