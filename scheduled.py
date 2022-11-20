import asyncio
import dataclasses
import datetime
import json
import logging
import math
import random
import time

from automatic import SolverConfig, AutoSolver
from libs import utils, database, instaling, webhooks

schedule_every = datetime.timedelta(minutes=1)


@dataclasses.dataclass(init=True, kw_only=True, slots=True)
class SolverProfile:
    run_times: tuple[datetime.time, datetime.time]
    username: str
    password: str
    user_agent: str
    solver_config: SolverConfig
    last_run: datetime.date
    next_run: datetime.datetime | None
    task: asyncio.Task | None


async def solver_task(db: database.DatabaseManager, wh: webhooks.Webhook, profile: SolverProfile):
    logger = logging.getLogger(f"scheduler.{profile.username}")
    to_wait = (profile.next_run - datetime.datetime.now()).total_seconds() + random.random()
    logger.debug(f"Waiting {to_wait}s until solver start")
    await asyncio.sleep(to_wait)

    logger.debug("Preparing loggers for autosolver")
    solver_logger = logging.getLogger(f"solver.{profile.username}")
    log_file_name = time.strftime(f'logs/%Y-%m-%d_%H-%M-%S-{profile.username}.log')
    handler = logging.FileHandler(log_file_name)
    handler.setFormatter(utils.logging_file_formatter())
    handler.setLevel(logging.DEBUG)
    solver_logger.setLevel(logging.DEBUG)
    solver_logger.addHandler(handler)

    logger.debug("Starting a session...")
    await wh.send_message(f"Solver for profile `{profile.username}` is starting.")
    start_time = time.time()
    try:
        async with instaling.Session(profile.username, profile.password, user_agent=profile.user_agent) as session:
            logger.info("Starting the auto solver session")
            autosolver = AutoSolver(session, db, solver_logger, profile.solver_config)
            await autosolver.run()
    except Exception:
        solver_logger.exception("Solver crashed!")
        result = f"crashed (<@!446690119366475796>)"
    else:
        result = f"finished"
    time_elapsed = round(time.time() - start_time)

    logger.debug("Cleaning up solver loggers")
    solver_logger.removeHandler(handler)
    handler.flush()
    handler.close()

    logger.debug("Reporting task completion via webhook")
    mins = math.floor(time_elapsed / 60)
    secs = time_elapsed % 60
    await wh.send_message(
        f"Solver for profile `{profile.username}` has {result} after {mins}m {secs}s.\nTask logs attached below.",
        file_path=log_file_name
    )
    profile.task = None


async def main():
    logger = logging.getLogger("scheduler")
    with open("config.json") as f:
        config = json.load(f)
    profiles = []
    for p in config['profiles']:
        rt = p['run_times']
        profiles.append(SolverProfile(
            run_times=(datetime.time(*rt[0]), datetime.time(*rt[1])),
            username=p['username'],
            password=p['password'],
            user_agent=p['user_agent'],
            solver_config=SolverConfig(**p['solver_config']),
            last_run=datetime.date.fromtimestamp(0),
            next_run=None,
            task=None
        ))
    logger.debug("Config parsed.")
    async with webhooks.Webhook(config['webhook']) as wh:
        async with database.DatabaseManager(**config['database']) as db:
            del config
            while True:
                # Schedule stuff
                logger.debug("Attempting to schedule stuff")
                now = datetime.datetime.now()
                today = now.date()
                for profile in profiles:
                    if profile.last_run >= today:
                        continue
                    if profile.next_run is None and profile.run_times[1] < now.time():
                        profile.last_run = today
                        logger.warning(f"Skipping profile {profile.username} - past the max start time.")
                        await wh.send_message(f"(<@!446690119366475796>) Failed to schedule profile "
                                              f"`{profile.username}` - already past the max start time")
                        continue
                    if profile.task is not None:
                        logger.warning(f"Profile {profile.username} hasn't been ran today yet, but is already running!")
                    if profile.next_run is None:
                        ts_min = datetime.datetime.combine(today, profile.run_times[0]).timestamp()
                        ts_max = datetime.datetime.combine(today, profile.run_times[1]).timestamp()
                        profile.next_run = datetime.datetime.fromtimestamp(random.randint(int(ts_min), int(ts_max)))
                        logger.info(f"Profile {profile.username} has been scheduled to run "
                                    f"at {profile.next_run.ctime()}")
                        utc_timestamp = int(profile.next_run.astimezone(datetime.timezone.utc).timestamp())
                        await wh.send_message(f"Profile `{profile.username}` has been scheduled to run at "
                                              f"<t:{utc_timestamp}:F>.")
                    if profile.next_run - now > schedule_every:
                        continue
                    logger.info(f"Creating a task for profile {profile.username}")
                    profile.last_run = today
                    profile.task = asyncio.create_task(solver_task(db, wh, profile))
                await asyncio.sleep(schedule_every.total_seconds())


if __name__ == "__main__":
    utils.logging_setup()
    asyncio.run(main())
