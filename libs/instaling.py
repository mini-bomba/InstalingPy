import httpx
import re

from . import urls
from .exceptions import LoginError, SessionExpired
from . import utils, classes

default_useragent = "Mozilla/5.0 (X11; Linux x86_64; rv:106.0) Gecko/20100101 Firefox/106.0"
version_regex = re.compile(r"""updateParams\((?:[\w'"]+,\s*){3}['"](\w+)['"]\)""")


class Session:
    httpx_client: httpx.AsyncClient
    user_id: str
    version: str | None
    username: str
    password: str

    def __init__(self, username: str, password: str, /, *, user_agent: str = default_useragent):
        self.username = username
        self.password = password
        self.version = None
        headers = {
            "User-Agent": user_agent
        }
        self.httpx_client = httpx.AsyncClient(headers=headers, base_url="https://instaling.pl",
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
        del self.username
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
        r = await self.httpx_client.post(urls.INIT_SESSION, data={
            "child_id": self.user_id,
            "repeat": "",
            "start": "",
            "end": ""
        })
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
        r = await self.httpx_client.post(urls.NEXT_WORD, data={
            "child_id": self.user_id,
            "date": utils.js_timestamp()
        })
        data = r.json()
        if 'id' not in data:
            return None
        return classes.WordData(
            id=int(data['id']),
            word=None,
            shown_answer=None,
            usage_example=data['usage_example'],
            difficulty=int(data['difficulty']) if 'difficulty' in data else None,
            translations=data['translations'],
            audio_filename=None,
            grade=None,
            type=data['type']
        )

    async def submit_answer(self, word_id: int, answer: str) -> classes.WordData | None:
        r = await self.httpx_client.post(urls.SUBMIT_ANSWER, data={
            "child_id": self.user_id,
            "word_id": word_id,
            "answer": answer,
            "version": self.version
        })
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
            grade=classes.AnswerGrade(data['grade']),
            type=None
        )
