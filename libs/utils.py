import datetime
import logging
import os
import random
import re
import signal
import sys
import time

import httpx

from . import urls
from .exceptions import SessionExpired

paren_remover = re.compile(r"\s*\(.+?\)\s*")
double_space = re.compile(r"\s{2,}")


async def check_for_session_expiry(response: httpx.Response):
    if response.url.path == urls.LOGOUT:
        raise SessionExpired("Session expired or logged out")


def js_timestamp() -> int:
    return round(datetime.datetime.now().timestamp() * 1000)


def split_translations(translations: str) -> list[str]:
    return [
        translation.strip()
        for s1 in double_space.sub(" ", paren_remover.sub(" ", translations)).split(",")
        for s2 in s1.split(";")
        for translation in s2.split("/")
    ]


def check_chance(chance: float) -> bool:
    return chance > 0 and (chance >= 1 or random.random() < chance)


def logging_file_formatter() -> logging.Formatter:
    return logging.Formatter("[%(asctime)s] [%(name)s|%(levelname)s]: %(message)s")


def utc_timestamp(dt: datetime.datetime) -> int:
    return int(dt.astimezone(datetime.timezone.utc).timestamp())


def logging_setup():
    # Make logs dir
    os.makedirs("logs", exist_ok=True)
    # Create objects
    file_formatter = logging_file_formatter()
    stdout_formatter = logging.Formatter("[%(name)s|%(levelname)s]: %(message)s")
    file_handler = logging.FileHandler(time.strftime('logs/%Y-%m-%d_%H-%M-%S-main.log'))
    stdout_handler = logging.StreamHandler(sys.stdout)
    # Set up handlers
    file_handler.setFormatter(file_formatter)
    file_handler.setLevel(logging.DEBUG)
    stdout_handler.setFormatter(stdout_formatter)
    stdout_handler.setLevel(logging.DEBUG)
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(stdout_handler)
    logging.getLogger("httpcore").setLevel(logging.INFO)


def interrupt_self(*_):
    os.kill(os.getpid(), signal.SIGINT)


def redirect_sigterm_to_sigint():
    signal.signal(signal.SIGTERM, interrupt_self)
