import asyncio
import contextlib
import logging
import re

import httpx

from . import urls
from . import utils, classes
from .exceptions import LoginError, SessionExpired

default_useragent = "Mozilla/5.0 (X11; Linux x86_64; rv:106.0) Gecko/20100101 Firefox/106.0"
version_regex = re.compile(r"""updateParams\((?:[\w'"]+,\s*){3}['"](\w+)['"]\)""")


class Session:
    httpx_client: httpx.AsyncClient
    user_id: str
    version: str | None
    username: str
    password: str
    logger: logging.Logger
    retries: int
    retry_wait: float

    def __init__(
            self,
            username: str, password: str, /, *,
            user_agent: str = default_useragent,
            timeout: float | None = 10.0,
            root_logger: logging.Logger = logging.root,
            retries: int = 10,
            retry_wait: float = 2.5,
    ):
        self.username = username
        self.password = password
        self.version = None
        self.logger = root_logger.getChild("session")
        self.retries = retries
        self.retry_wait = retry_wait
        headers = {
            "User-Agent": user_agent
        }
        limits = httpx.Limits(keepalive_expiry=30.0)
        self.httpx_client = httpx.AsyncClient(headers=headers, base_url="https://instaling.pl", timeout=timeout,
                                              limits=limits,
                                              event_hooks={'response': [utils.check_for_session_expiry]})

    async def __aenter__(self) -> 'Session':
        await self.httpx_client.__aenter__()
        # log in
        r = await self.httpx_client.post(urls.LOGIN, follow_redirects=True, data={
            "action": "login",
            "from": "",
            "log_email": self.username,
            "log_password": self.password
        })
        del self.password
        if r.url.path != urls.MAIN:
            raise LoginError("Failed to log in.")
        self.user_id = r.url.params['student_id']
        await self.get_app_version(ignore_cache=True)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        # log out
        try:
            await self.httpx_client.get(urls.LOGOUT)
        except SessionExpired:
            pass
        await self.httpx_client.__aexit__(exc_type, exc_val, exc_tb)

    def __aiter__(self) -> 'Session':
        return self

    async def __anext__(self) -> classes.WordData:
        res = await self.get_next_word()
        if res is None:
            raise StopAsyncIteration
        return res

    @property
    def db_user_id(self) -> int:
        return int(self.user_id)

    async def is_daily_completed(self) -> bool:
        r = await self.httpx_client.get(urls.MAIN, params={"student_id": self.user_id})
        return r.content.find(b"sesja wykonana") != -1

    async def get_session_status(self) -> classes.SessionStatus:
        for _ in range(self.retries):
            r = await self.httpx_client.post(urls.INIT_SESSION, data={
                "child_id": self.user_id,
                "repeat": "",
                "start": "",
                "end": ""
            })
            if r.is_server_error or (r.is_success and len(r.content) == 0):
                self.logger.warning("Got empty response or server error during session status request, retrying")
                await asyncio.sleep(self.retry_wait)
                continue
            if r.status_code == 405:
                self.logger.warning("Got 405 error during session status request, retrying")
                await asyncio.sleep(self.retry_wait)
                continue
            break
        r.raise_for_status()
        data = r.json()
        return classes.SessionStatus(
            in_progress=not data['is_new'],
            id=data['id']
        )

    async def get_app_version(self, *, ignore_cache: bool = False) -> str:
        if self.version is not None and not ignore_cache:
            return self.version
        r = await self.httpx_client.get(urls.APP, params={"child_id": self.user_id})
        match = version_regex.search(r.text)
        if match is None:
            raise RuntimeError("Could not find version ID in app code!")
        self.version = match.groups()[0]
        return self.version

    async def get_next_word(self) -> classes.WordData | None:
        data = {
            "child_id": self.user_id,
            "date": utils.js_timestamp()
        }
        for _ in range(self.retries):
            r = await self.httpx_client.post(urls.NEXT_WORD, data=data)
            if r.is_server_error or (r.is_success and len(r.content) == 0):
                self.logger.warning("Got empty response or server error during next word request, retrying")
                await asyncio.sleep(self.retry_wait)
                continue
            if r.status_code == 405:
                self.logger.warning("Got 405 error during session status request, retrying")
                await asyncio.sleep(self.retry_wait)
                continue
            break
        r.raise_for_status()
        data = r.json()
        if 'id' not in data:
            return None
        return classes.WordData(
            id=int(data['id']),
            word=None,
            shown_answer=None,
            usage_example=data['usage_example'],
            difficulty=int(d) if (d:=data.get('difficulty')) is not None else None,
            translations=data['translations'],
            audio_filename=None,
            has_audio=data.get("has_audio") == "1",
            grade=None,
            type=data['type']
        )

    async def submit_answer(self, word_id: int, answer: str) -> classes.WordData | None:
        for _ in range(self.retries):
            r = await self.httpx_client.post(urls.SUBMIT_ANSWER, data={
                "child_id": self.user_id,
                "word_id": word_id,
                "answer": answer,
                "version": self.version
            })
            if r.is_server_error or (r.is_success and len(r.content) == 0):
                self.logger.warning("Got empty response or server error during answer submission, retrying")
                await asyncio.sleep(self.retry_wait)
                continue
            if r.status_code == 405:
                self.logger.warning("Got 405 error during session status request, retrying")
                await asyncio.sleep(self.retry_wait)
                continue
            break
        r.raise_for_status()
        data = r.json()
        if 'id' not in data:
            return None  # session finished
        return classes.WordData(
            id=int(data['id']),
            word=data.get('word'),
            shown_answer=data['answershow'],
            usage_example=data['usage_example'],
            difficulty=None,
            translations=data['translations'],
            audio_filename=data['audio_filename'],
            has_audio=data.get("has_audio") == "1",
            grade=classes.AnswerGrade(data['grade']),
            type=None
        )

    async def make_ad_request(self, location_id: str, premium: int) -> httpx.Response:
        return await self.httpx_client.get(urls.GET_ADS, params={
            "location_id": location_id,
            "premium": premium
        })

    async def make_ad_requests(self):
        # we really don't care if an ad request goes wrong
        # this is only to make our client look more legit
        with contextlib.suppress(Exception):
            await asyncio.gather(
                self.make_ad_request("learning_session_dynamic_top", 0),
                self.make_ad_request("learning_session_dynamic_bot", 0),
            )

    async def get_audio_url(self, word_id: int) -> httpx.URL | None:
        r = await self.httpx_client.get(urls.GET_AUDIO_URL, params={
            "id": word_id,
        })
        if not r.is_success:
            self.logger.warning(f"Failed to make audio URL request: got status code {r.status_code}")
            return None
        data = r.json()
        url = data.get("url")
        if url is None:
            return None
        try:
            return httpx.URL(url)
        except Exception:
            self.logger.exception("Failed to parse returned audio url")
            return None

    async def make_audio_request(self, word_id: int):
        with contextlib.suppress(Exception):  # we don't care, this is here only to make us look legit
            url = await self.get_audio_url(word_id)
            if url is None:
                return
            if url.host != self.httpx_client.base_url.host:
                self.logger.warning(f"Aborting audio request: Returned URL '{url}' does not match expected host "
                                    f"'{self.httpx_client.base_url.host}'")
                return
            await self.httpx_client.get(url)
