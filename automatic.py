from libs import classes, database, instaling, utils
import getpass
import asyncio
import random
import logging
import dataclasses


@dataclasses.dataclass(init=True, kw_only=True, slots=True, frozen=True)
class SolverConfig:
    speed_config: dict[str, list[int]]
    runs: int
    distraction_chance: float
    base_memorize_chance: float
    memorize_requirement: int
    synonym_chance: float
    mistake_chance: float


class AutoSolver:
    main_logger: logging.Logger
    session: instaling.Session
    db: database.DatabaseManager
    seen_words: set[int]
    config: SolverConfig

    def __init__(self, session: instaling.Session, db: database.DatabaseManager, logger: logging.Logger,
                 config: SolverConfig):
        self.session = session
        self.db = db
        self.main_logger = logger
        self.seen_words = set()
        self.config = config

    @property
    def user_id(self) -> str:
        return self.session.user_id

    @property
    def db_user_id(self) -> int:
        return self.session.db_user_id

    async def random_sleep(self, t: str, times: int = 1):
        logger = self.main_logger.getChild("timing")
        sleep_time = random.randint(*self.config.speed_config[t]) * times
        logger.debug(f"Simulating delay '{t}' - sleeping for {sleep_time}ms")
        await asyncio.sleep(sleep_time / 1000)

    def check_mistake_chance(self, seen_times: int) -> bool:
        return (
                utils.check_chance((1 - seen_times / self.config.memorize_requirement)
                                   * (1 - self.config.base_memorize_chance))
                or utils.check_chance(self.config.mistake_chance)
        )

    async def distraction(self):
        if utils.check_chance(self.config.distraction_chance):
            logger = self.main_logger.getChild("timing")
            logger.debug("Simulating a distraction")
            await self.random_sleep("distraction")

    async def run(self):
        logger = self.main_logger.getChild("solver")
        for i in range(self.config.runs):
            logger.info(f"Starting session {i + 1} of {self.config.runs}")
            await self.random_sleep("first_session" if i == 0 else "next_session")
            await self.distraction()
            async for word in self.session:
                word: classes.WordData
                if word.type == "marketing":
                    logger.debug("Skipping marketing")
                    await self.random_sleep("marketing_skip")
                    await self.distraction()
                    continue
                db_word = await self.db.get_word(word.id, self.db_user_id)
                translations = await self.db.translate_words(utils.split_translations(word.translations),
                                                             self.db_user_id)
                logger.info(f"New prompt: {word.usage_example} ({word.translations})")
                await self.distraction()
                await self.random_sleep("initial")
                if db_word is None and (len(translations) == 0 or not utils.check_chance(self.config.synonym_chance)):
                    logger.info("Answer not found in the DB, sending nothing")
                    await self.random_sleep("give_up")
                    await self.send_nothing(word)
                elif db_word is None:
                    logger.info("Answer not found in the DB, but found a synonym instead")
                    answer = random.choice(translations)
                    answer: classes.DBWord
                    await self.random_sleep("typing", len(answer.word))
                    await self.send_answer(word, answer.word)
                elif word.id not in self.seen_words and self.check_mistake_chance(db_word.seen_times):
                    logger.debug(f"Seen {db_word.seen_times} times, last on {db_word.last_seen.ctime()}")
                    logger.info("Simulating mistake")
                    if len(translations) > 1 and utils.check_chance(self.config.synonym_chance):
                        await self.random_sleep("extra_think")
                        logger.info("Submitting a synonym instead of the actual answer")
                        # remove actual word from the list
                        for j, w in enumerate(translations):
                            if w.id == word.id:
                                del translations[j]
                                break
                        answer = random.choice(translations)
                        await self.random_sleep("typing", len(answer.word))
                        await self.send_answer(word, answer.word)
                    else:
                        logger.info("Submitting nothing instead of the actual answer")
                        await self.random_sleep('give_up')
                        await self.send_nothing(word)
                else:
                    logger.debug(f"Seen {db_word.seen_times} times, last on {db_word.last_seen.ctime()}")
                    await self.random_sleep("typing", len(db_word.shown_word))
                    result = await self.send_answer(word, db_word.shown_word)
                    if result.grade != classes.AnswerGrade.Correct:
                        raise RuntimeError(f"Word ID {word.id} didn't accept answer from the DB. "
                                           f"Sent {db_word.shown_word}, got {result.word}/{result.shown_answer}")
                self.seen_words.add(word.id)
                await self.random_sleep("next_question")
            logger.info(f"Session {i + 1} of {self.config.runs} finished!")
        logger.info("All finished!")

    async def send_nothing(self, word: classes.WordData):
        logger = self.main_logger.getChild("answers")
        logger.debug("Sending nothing")
        result = await self.session.submit_answer(word.id, "")
        if result.word is None or result.shown_answer is None:
            raise RuntimeError(f"Word ID {word.id} didn't return an answer after entering nothing")
        logger.info(f"Got answer: {result.shown_answer}/{result.word}")
        await self.db.handle_word(result, self.db_user_id)

    async def send_answer(self, word: classes.WordData, answer: str) -> classes.WordData:
        logger = self.main_logger.getChild("answers")
        logger.info(f"Sending '{answer}'")
        result = await self.session.submit_answer(word.id, answer)
        logger.info(f"Got result: {result.grade.name}")
        logger.debug(f"The correct answer was {result.shown_answer}/{result.word}")
        await self.db.handle_word(result, self.db_user_id)
        return result


async def main():
    user = input("Username: ")
    password = getpass.getpass("Password: ")
    config = SolverConfig(
        speed_config={
            "marketing_skip": [500, 2000],
            "initial": [1000, 4000],
            "extra_think": [2000, 10000],
            "typing": [150, 600],
            "give_up": [5000, 15000],
            "next_question": [1000, 3000],
            "first_session": [1000, 10000],
            "next_session": [5000, 60000],
            "distraction": [15000, 60000]
        },
        runs=1,
        distraction_chance=0.01,
        base_memorize_chance=0.2,
        memorize_requirement=3,
        synonym_chance=0.75,
        mistake_chance=0.025
    )
    async with database.DatabaseManager(pool_recycle=60, user="mini_bomba", password="", db="InstalingBot",
                                        unix_socket="/var/run/mysqld/mysqld.sock") as db:
        async with instaling.Session(user, password) as session:
            await AutoSolver(session, db, logging.getLogger(f"solver.{user}"), config).run()


if __name__ == "__main__":
    utils.logging_setup()
    asyncio.run(main())
