import dataclasses
import datetime
import enum


@dataclasses.dataclass(init=True, frozen=True, slots=True, kw_only=True, repr=True)
class SessionStatus:
    id: str | None
    in_progress: bool


class AnswerGrade(enum.Enum):
    Incorrect = 0
    Correct = 1
    Synonym = 2
    WrongCase = 3
    Mistyped = 4


@dataclasses.dataclass(init=True, frozen=True, slots=True, kw_only=True)
class WordData:
    id: int
    word: str | None            # only present on objects from submit_answer() if grade == Correct or grade == Incorrect
    shown_answer: str | None    # not present in objects from get_next_word()
    usage_example: str
    difficulty: int | None      # only present on objects from get_next_word(), if the word was not shown before
    translations: str
    audio_filename: str | None  # not present in objects from get_next_word()
    has_audio: bool
    grade: AnswerGrade | None   # only present in objects from submit_answer()
    type: str | None            # only present on objects from get_next_word()


@dataclasses.dataclass(init=True, frozen=True, slots=True, kw_only=True)
class DBWord:
    id: int
    word: str
    shown_word: str
    usage_example: str
    translations: list[str]
    seen_times: int | None
    last_seen: datetime.datetime | None
