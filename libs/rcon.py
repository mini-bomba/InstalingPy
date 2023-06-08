import asyncio
import datetime
import logging
from abc import ABC, abstractmethod
from typing import Literal, Annotated, TYPE_CHECKING, Awaitable

from pydantic import BaseModel, Field

from . import utils

if TYPE_CHECKING:
    from ..scheduled import Scheduler

logger = logging.getLogger("scheduler.rcon")


# ====================== #
#  rcon data components  #
# ====================== #


class ListedProfile(BaseModel):
    last_run: datetime.datetime
    next_run: datetime.datetime | None
    task_created: bool
    running: bool
    last_log: str | None


# ================ #
#  rcon responses  #
# ================ #


class BaseRconResponse(BaseModel, ABC):
    type: str
    nonce: str | None

    def send(self, writer: asyncio.StreamWriter):
        logger.debug(f"Sending response of type {self.type}")
        writer.write(self.json().encode() + b"\0")


class RconValidationErrorResponse(BaseRconResponse):
    type = "validation_error"
    errors: list[dict]


class RconPingResponse(BaseRconResponse):
    type = "pong"


class RconMessageResponse(BaseRconResponse):
    type = "message"
    msg: str


class RconCommandSuccessResponse(BaseRconResponse):
    type = "success"
    command_type: str


class RconErrorResponse(BaseRconResponse):
    type = "error"
    command_type: str
    error: str


class RconExitResponse(BaseRconResponse):
    type = "exit"
    reason: str


class RconProfilesListResponse(BaseRconResponse):
    type = "list_profiles"
    profiles: dict[str, ListedProfile]


class RconProfileRescheduledResponse(BaseRconResponse):
    type = "profile_rescheduled"
    profile: str
    new_time: datetime.datetime


class RconExit(Exception):
    reason: str

    def __init__(self, reason: str):
        super().__init__()
        self.reason = reason

    def response(self) -> RconExitResponse:
        return RconExitResponse(reason=self.reason)


# =============== #
#  rcon commands  #
# =============== #


class BaseRconCommand(BaseModel, ABC):
    type: str
    nonce: str | None

    @abstractmethod
    async def process(self, scheduler: 'Scheduler', writer: asyncio.StreamWriter):
        raise NotImplementedError

    def send_success(self, writer: asyncio.StreamWriter):
        RconCommandSuccessResponse(nonce=self.nonce, command_type=self.type).send(writer)

    def send_error(self, writer: asyncio.StreamWriter, error: str):
        RconErrorResponse(nonce=self.nonce, command_type=self.type, error=error).send(writer)


class RconPingCommand(BaseRconCommand):
    type: Literal["ping"]

    async def process(self, scheduler: 'Scheduler', writer: asyncio.StreamWriter):
        RconPingResponse(nonce=self.nonce).send(writer)


class RconEchoCommand(BaseRconCommand):
    type: Literal["echo"]
    data: str

    async def process(self, scheduler: 'Scheduler', writer: asyncio.StreamWriter):
        RconMessageResponse(nonce=self.nonce, msg=self.data).send(writer)


class RconExitCommand(BaseRconCommand):
    type: Literal["exit"]

    async def process(self, scheduler: 'Scheduler', writer: asyncio.StreamWriter):
        raise RconExit("user_request")


class RconWebhookSendCommand(BaseRconCommand):
    type: Literal["wh_send"]
    msg: Annotated[str, Field(min_length=1, max_length=512)]

    async def process(self, scheduler: 'Scheduler', writer: asyncio.StreamWriter):
        await scheduler.webhook.send_message(f"rcon message: {self.msg}")
        self.send_success(writer)


class RconListProfilesCommand(BaseRconCommand):
    type: Literal["list_profiles"]

    async def process(self, scheduler: 'Scheduler', writer: asyncio.StreamWriter):
        RconProfilesListResponse(nonce=self.nonce, profiles={
            name: ListedProfile(
                last_run=profile.last_run,
                next_run=profile.next_run,
                task_created=profile.task is not None,
                running=profile.running,
                last_log=profile.last_log,
            )
            for name, profile in scheduler.profiles.items()
        }).send(writer)


class RconRescheduleCommand(BaseRconCommand):
    type: Literal["reschedule"]
    profile: str = Field(min_length=1)
    new_time: datetime.datetime | datetime.time | None = Field(None)

    async def process(self, scheduler: 'Scheduler', writer: asyncio.StreamWriter):
        profile = scheduler.profiles.get(self.profile)
        now = datetime.datetime.now()
        if profile is None:
            return self.send_error(writer, f"Profile '{self.profile}' not found")
        if profile.task is not None and profile.running:
            return self.send_error(writer, f"Cannot reschedule a running profile")
        if isinstance(self.new_time, datetime.time):
            self.new_time = datetime.datetime.combine(datetime.date.today(), self.new_time)
        if self.new_time is None:
            if profile.run_times.end < now.time():
                return self.send_error(writer, "Automatic rescheduling failed - past profile max start time!")
        elif self.new_time < now:
            return self.send_error(writer, f"New scheduled time cannot be in the past!")
        else:
            profile.next_run = self.new_time
        next_run = profile.next_run
        logger.info(f"Profile '{self.profile}' has been rescheduled to run at {next_run.ctime()}")
        if profile.task is not None:
            logger.debug(f"Cancelling current task for profile {profile.profile_name}")
            await profile.cancel_task()
        if next_run - datetime.datetime.now() < scheduler.schedule_every:
            logger.debug(f"Starting new task for profile {profile.profile_name}")
            scheduler.start_solver_task(profile)
        await scheduler.webhook.send_message(f"Profile `{profile.profile_name}` has been rescheduled to run at "
                                             f"<t:{utils.utc_timestamp(next_run)}:F>")
        RconProfileRescheduledResponse(nonce=self.nonce, profile=profile.profile_name, new_time=next_run).send(writer)


class RconCancelCommand(BaseRconCommand):
    type: Literal["cancel"]
    profile: str = Field(min_length=1)

    async def process(self, scheduler: 'Scheduler', writer: asyncio.StreamWriter):
        await self.cancel(scheduler, writer, False)

    async def cancel(self, scheduler: 'Scheduler', writer: asyncio.StreamWriter, force: bool):
        profile = scheduler.profiles.get(self.profile)
        if profile is None:
            return self.send_error(writer, f"Profile '{self.profile}' not found")
        if not force and profile.task is not None and profile.running:
            return self.send_error(writer, f"Cannot cancel a running profile - use force_cancel")
        profile.last_run = datetime.datetime.now()
        profile.next_run = None
        logger.debug(f"Profile {profile.profile_name} has been cancelled")
        if profile.task is not None:
            logger.debug(f"Cancelling current task for profile {profile.profile_name}")
            await profile.cancel_task()
        await scheduler.webhook.send_message(f"Profile `{profile.profile_name}` has been cancelled.")
        self.send_success(writer)


class RconForceCancelCommand(RconCancelCommand):
    type: Literal["force_cancel"]

    async def process(self, scheduler: 'Scheduler', writer: asyncio.StreamWriter):
        await self.cancel(scheduler, writer, True)


class RconRunNowCommand(BaseRconCommand):
    type: Literal["run_now"]
    profile: str = Field(min_length=1)

    async def process(self, scheduler: 'Scheduler', writer: asyncio.StreamWriter):
        profile = scheduler.profiles.get(self.profile)
        if profile is None:
            return self.send_error(writer, f"Profile '{self.profile}' not found")
        if profile.task is not None and profile.running:
            return self.send_error(writer, f"Profile already running")
        profile.next_run = datetime.datetime.now()
        if profile.task is not None:
            logger.debug(f"Cancelling current task for profile {profile.profile_name}")
            await profile.cancel_task()
        logger.info(f"Starting profile {profile.profile_name} now")
        scheduler.start_solver_task(profile)
        await scheduler.webhook.send_message(f"Profile `{profile.profile_name}` has been manually started")
        self.send_success(writer)


# Autogenerate a union of all BaseRconCommand classes defined here
_rcon_command_types_list = [item for item in globals().values()
                            if item is not BaseRconCommand and isinstance(item, type)
                            and issubclass(item, BaseRconCommand)]
_rcon_command_types = _rcon_command_types_list[0]
for t in _rcon_command_types_list[1:]:
    _rcon_command_types |= t


class RconCommand(BaseModel):
    __root__: _rcon_command_types = Field(..., discriminator="type")

    @property
    def type(self) -> str:
        return self.__root__.type

    def process(self, scheduler: 'Scheduler', writer: asyncio.StreamWriter) -> Awaitable:
        return self.__root__.process(scheduler, writer)
