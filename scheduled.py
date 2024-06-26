import asyncio
import contextlib
import dataclasses
import datetime
import json
import logging
import math
import random
import string
import time
from pathlib import Path
from typing import Any

import pydantic

from automatic import SolverConfig, AutoSolver
from libs import utils, database, instaling, webhooks, rcon


@dataclasses.dataclass(init=True, slots=True)
class RunTimes:
    start: datetime.time
    end: datetime.time


@dataclasses.dataclass(init=True, kw_only=True, slots=True)
class SolverProfile:
    profile_name: str
    run_times: RunTimes
    username: str
    password: str
    user_agent: str
    timeout: float | None
    retries: int | None
    retry_wait: float | None
    solver_config: SolverConfig
    last_run: datetime.datetime
    next_run: datetime.datetime | None
    task: asyncio.Task | None
    running: bool
    last_log: str | None

    async def cancel_task(self):
        if self.task is None:
            return
        self.task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self.task
        self.task = None
        self.running = False

    @property
    def logger(self) -> logging.Logger:
        return logging.getLogger(f"solver.{self.profile_name}")

    @property
    def session_extras(self) -> dict[str, Any]:
        extras = {}
        if self.user_agent is not None:
            extras['user_agent'] = self.user_agent
        if self.timeout is not None:
            extras['timeout'] = self.timeout
        if self.retries is not None:
            extras['retries'] = self.retries
        if self.retry_wait is not None:
            extras['retry_wait'] = self.retry_wait
        return extras

    def reschedule(self) -> datetime.datetime:
        today = datetime.date.today()
        ts_min = datetime.datetime.combine(today, self.run_times.start).timestamp()
        ts_max = datetime.datetime.combine(today, self.run_times.end).timestamp()
        self.next_run = datetime.datetime.fromtimestamp(random.randint(int(ts_min), int(ts_max)))
        return self.next_run


class Scheduler:
    profiles: dict[str, SolverProfile]
    webhook: webhooks.Webhook
    db: database.DatabaseManager
    scheduler_trigger: asyncio.Event
    schedule_every = datetime.timedelta(minutes=15)

    def __init__(self, profiles: dict[str, SolverProfile], webhook: webhooks.Webhook, db: database.DatabaseManager):
        self.profiles = profiles
        self.webhook = webhook
        self.db = db
        self.scheduler_trigger = asyncio.Event()

    def schedule_now(self):
        self.scheduler_trigger.set()

    async def handle_rcon_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        logger = logging.getLogger("scheduler.rcon")
        logger.info("New rcon connection received")
        rcon.RconMessageResponse(msg="hi!").send(writer)

        try:
            while True:
                raw_command = await reader.readuntil(b'\0')
                try:
                    command = rcon.RconCommand.parse_raw(raw_command.strip(b"\0" + string.whitespace.encode()))
                except pydantic.ValidationError as e:
                    logger.warning("Invalid data from rcon connection, closing")
                    rcon.RconValidationErrorResponse(errors=e.errors()).send(writer)
                    raise rcon.RconExit("invalid_command")

                logger.info(f"Got rcon command of type {command.type}")
                await command.process(self, writer)
        except rcon.RconExit as e:
            e.response().send(writer)
        except asyncio.IncompleteReadError:
            logger.warning("Unexpected rcon socket disconnect")
        except Exception:
            logger.exception("Error while handling rcon connection")
            rcon.RconExitResponse(reason="server_error").send(writer)

        writer.write_eof()
        writer.close()
        await writer.wait_closed()
        logger.info("Rcon connection closed")

    async def run(self):
        logger = logging.getLogger("scheduler")
        while True:
            # Schedule stuff
            logger.debug("Attempting to schedule stuff")
            now = datetime.datetime.now()
            today = now.replace(hour=0, minute=0, second=0, microsecond=0)
            for profile_name, profile in self.profiles.items():
                if profile.last_run >= today:
                    continue
                if profile.next_run is None and profile.run_times.end < now.time():
                    profile.last_run = now
                    logger.warning(f"Skipping profile {profile_name} - past the max start time.")
                    await self.webhook.send_message(f"(<@!446690119366475796>) Failed to schedule profile "
                                                    f"`{profile_name}` - already past the max start time")
                    continue
                if profile.task is None and profile.running:
                    logger.warning(f"Profile {profile_name} is registered as running, but it's task is None! "
                                   f"Rescheduling!")
                    await self.webhook.send_message(f"(<@!446690119366475796>) Possible bug detected - Profile "
                                                    f"{profile_name} is registered as running, but task is None!")
                    profile.running = False
                elif profile.task is not None and profile.running:
                    if not profile.task.done():
                        logger.warning(f"Profile {profile_name} hasn't been ran today yet, but is already running!")
                        profile.task.cancel("End of day reached")
                    if profile.task is not None:
                        try:
                            await profile.task
                            logger.warning(f"Profile {profile_name} did not unset its task property")
                            await self.webhook.send_message(f"(<@!446690119366475796>) Possible bug detected - Profile "
                                                            f"{profile_name} did not unset its task property!")
                        except Exception as e:
                            logger.error(f"Profile {profile_name} was found crashed outside of a try-catch!")
                            p_logger = profile.logger
                            p_logger.exception(f"Recovered an uncaught exception", exc_info=e)
                            for handler in p_logger.handlers[:]:
                                p_logger.removeHandler(handler)
                                handler.flush()
                                handler.close()
                            await self.webhook.send_message(f"(<@!446690119366475796>) Recovered an uncaught exception "
                                                            f"from profile `{profile_name}`! Last logs attached below.",
                                                            file_path=profile.last_log)
                            profile.task = None
                            profile.running = False
                if profile.next_run is None:
                    next_run = profile.reschedule()
                    logger.info(f"Profile {profile_name} has been scheduled to run at {next_run.ctime()}")
                    await self.webhook.send_message(f"Profile `{profile_name}` has been scheduled to run at "
                                                    f"<t:{utils.utc_timestamp(next_run)}:F>.")
            # Run stuff
            for profile_name, profile in self.profiles.items():
                if profile.next_run is None or profile.task is not None or profile.next_run - now > self.schedule_every:
                    continue
                logger.info(f"Creating a task for profile {profile_name}")
                profile.last_run = now
                self.start_solver_task(profile)
            with contextlib.suppress(asyncio.TimeoutError):
                async with asyncio.timeout(self.schedule_every.total_seconds()):
                    await self.scheduler_trigger.wait()
            self.scheduler_trigger.clear()

    def start_solver_task(self, profile: SolverProfile):
        if profile.task is not None:
            return
        profile.task = asyncio.create_task(self.solver_task(profile))
        profile.task.set_name(f"solver-{profile.profile_name}")

    async def solver_task(self, profile: SolverProfile):
        logger = logging.getLogger(f"scheduler.{profile.profile_name}")
        to_wait = (profile.next_run - datetime.datetime.now()).total_seconds() + random.random()
        logger.debug(f"Waiting {to_wait}s until solver start")
        await asyncio.sleep(to_wait)
        profile.next_run = None
        profile.last_run = datetime.datetime.now()
        profile.running = True

        logger.debug("Preparing loggers for autosolver")
        solver_logger = profile.logger
        log_file_name = time.strftime(f'logs/%Y-%m-%d_%H-%M-%S-{profile.profile_name}.log')
        profile.last_log = log_file_name
        handler = logging.FileHandler(log_file_name)
        handler.setFormatter(utils.logging_file_formatter())
        handler.setLevel(logging.DEBUG)
        solver_logger.setLevel(logging.DEBUG)
        solver_logger.addHandler(handler)

        logger.debug("Starting a session...")
        await self.webhook.send_message(f"Solver for profile `{profile.profile_name}` is starting.")
        start_time = datetime.datetime.now()
        user_id = None
        success = False
        try:
            async with instaling.Session(
                    profile.username, profile.password, root_logger=solver_logger, **profile.session_extras
            ) as session:
                user_id = session.db_user_id
                logger.info("Starting the auto solver session")
                autosolver = AutoSolver(session, self.db, solver_logger, profile.solver_config)
                await autosolver.run()
        except Exception:
            solver_logger.exception("Solver crashed!")
            result = f"crashed (<@!446690119366475796>)"
        except asyncio.CancelledError:
            solver_logger.exception("Solver cancelled!")
            result = "been cancelled"
            asyncio.current_task().uncancel()
        else:
            result = "finished"
            success = True
        end_time = datetime.datetime.now()
        time_elapsed = end_time - start_time

        logger.debug("Cleaning up solver loggers")
        solver_logger.removeHandler(handler)
        handler.flush()
        handler.close()

        if user_id is not None:
            logger.debug("Logging session completion")
            await self.db.log_session_timing(user_id, start_time, end_time, success)
        else:
            logger.warning("Not logging session completion: Signing into InstaLing failed")

        logger.debug("Creating wordcount snapshots")
        await self.db.capture_wordcounts_snapshot()

        logger.debug("Reporting task completion via webhook")
        mins = math.floor(time_elapsed.seconds / 60)
        secs = time_elapsed.seconds % 60
        try:
            await self.webhook.send_message(
                f"Solver for profile `{profile.profile_name}` has {result} after {mins}m {secs}s.\n"
                f"Task logs attached below.",
                file_path=log_file_name
            )
        except Exception:
            logger.exception("Failed to report task completion!")
        profile.task = None
        profile.running = False

    @staticmethod
    def load_config() -> tuple[dict[str, SolverProfile], str, dict[str, Any], Path]:
        logger = logging.getLogger("configs")
        with open("shared/config.json") as f:
            config = json.load(f)
        profiles = {}
        for name, p in config['profiles'].items():
            if p['solver_config']['runs'] < 1:
                logger.warning(f"Skipping profile {name} initialization: no runs configured")
                continue
            rt = p['run_times']
            profiles[name] = SolverProfile(
                profile_name=name,
                run_times=RunTimes(datetime.time(*rt[0]), datetime.time(*rt[1])),
                username=p['username'],
                password=p['password'],
                user_agent=p.get('user_agent'),
                timeout=p.get('timeout'),
                retries=p.get('retries'),
                retry_wait=p.get('retry_wait'),
                solver_config=SolverConfig(**p['solver_config']),
                last_run=datetime.datetime.fromtimestamp(0),
                next_run=None,
                task=None,
                running=False,
                last_log=None,
            )
        logger.debug("Config parsed.")
        return profiles, config['webhook'], config['database'], Path(config['rcon_path'])


async def main():
    profiles, webhook_url, database_config, rcon_path = Scheduler.load_config()
    async with webhooks.Webhook(webhook_url) as wh:
        async with database.DatabaseManager(**database_config) as db:
            scheduler = Scheduler(profiles, wh, db)
            rcon_path.parent.mkdir(parents=True, exist_ok=True)
            server = await asyncio.start_unix_server(scheduler.handle_rcon_client, rcon_path)
            rcon_path.chmod(0o600)

            await asyncio.gather(scheduler.run(), server.serve_forever())


if __name__ == "__main__":
    utils.logging_setup()
    utils.redirect_sigterm_to_sigint()
    with contextlib.suppress(KeyboardInterrupt), asyncio.Runner() as runner:
        runner.run(main())
