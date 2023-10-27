import contextlib
import datetime
import typing
from abc import ABC

import aiomysql

from . import classes
from . import utils

T = typing.TypeVar("T", aiomysql.Cursor, aiomysql.DictCursor, aiomysql.SSCursor, aiomysql.SSDictCursor)


class PatchedConnection(aiomysql.Connection):
    @typing.overload
    def cursor(self) -> contextlib.AbstractAsyncContextManager[aiomysql.Cursor]:
        pass

    @typing.overload
    def cursor(self, cur_type: type[T]) -> contextlib.AbstractAsyncContextManager[T]:
        pass

    def cursor(self, *cur_type):
        return super().cursor(*cur_type)


class PatchedPool(aiomysql.Pool, ABC):
    def acquire(self) -> contextlib.AbstractAsyncContextManager[PatchedConnection]:
        return super().acquire()


class DatabaseManager:
    pool: PatchedPool
    args: tuple
    kwargs: dict

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

    async def connect(self):
        self.pool = await aiomysql.create_pool(*self.args, **self.kwargs)
        del self.args, self.kwargs

    async def close(self):
        self.pool.close()
        await self.pool.wait_closed()

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def word_exists(self, word_id: int) -> bool:
        async with self.pool.acquire() as connection, connection.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute("""
                SELECT id FROM Words
                WHERE id = %s
                LIMIT 1
            """, (word_id,))
            return await cursor.fetchone() is not None

    async def get_word(self, word_id: int, user_id: int | None = None) -> classes.DBWord | None:
        async with self.pool.acquire() as connection, connection.cursor(aiomysql.DictCursor) as cursor:
            if user_id is None:
                await cursor.execute("""
                    SELECT * FROM Words
                    WHERE id = %s
                    LIMIT 1
                """, (word_id,))
            else:
                await cursor.execute("""
                    SELECT Words.*, WordHistory.seen_times, WordHistory.last_seen
                    FROM WordHistory INNER JOIN Words ON WordHistory.word_id = Words.id
                    WHERE WordHistory.word_id = %s AND WordHistory.user_id = %s;
                """, (word_id, user_id))
            result = await cursor.fetchone()
        if result is None:
            return None
        if user_id is None:
            result['seen_times'], result['last_seen'] = None, None
        translations = await self.get_word_translations(word_id)
        return classes.DBWord(**result, translations=translations)

    async def get_word_translations(self, word_id: int) -> list[str]:
        async with self.pool.acquire() as connection, connection.cursor() as cursor:
            await cursor.execute("""
                SELECT translation FROM WordTranslations
                WHERE word_id = %s
            """, (word_id,))
            return [t[0] for t in await cursor.fetchall()]

    async def get_seen_data(self, word_id: int, user_id: int) -> tuple[int, datetime.datetime]:
        async with self.pool.acquire() as connection, connection.cursor() as cursor:
            await cursor.execute("""
                SELECT seen_times, last_seen FROM WordHistory
                WHERE word_id = %s AND user_id = %s
                LIMIT 1
            """, (word_id, user_id))
            return await cursor.fetchone()

    async def translate_words(self, translations: list[str], user_id: int | None = None) -> list[classes.DBWord]:
        async with self.pool.acquire() as connection:
            async with connection.cursor(aiomysql.DictCursor) as cursor:

                if user_id is None:
                    await cursor.execute("""
                        SELECT DISTINCT Words.*
                        FROM Words INNER JOIN WordTranslations ON Words.id = WordTranslations.word_id
                        WHERE WordTranslations.translation IN %s
                    """, (translations,))
                else:
                    await cursor.execute("""
                        SELECT DISTINCT Words.*, WordHistory.seen_times, WordHistory.last_seen
                        FROM Words INNER JOIN WordTranslations ON Words.id = WordTranslations.word_id
                        INNER JOIN WordHistory ON Words.id = WordHistory.word_id
                        WHERE WordTranslations.translation IN %s AND WordHistory.user_id = %s 
                            AND WordHistory.seen_times > 0
                    """, (translations, user_id))
                result1 = await cursor.fetchall()
            async with connection.cursor() as cursor:
                words = []
                for word in result1:
                    await cursor.execute("""
                        SELECT translation FROM WordTranslations
                        WHERE word_id = %s
                    """, (word['id'],))
                    result2 = await cursor.fetchall()
                    if user_id is None:
                        word['seen_times'] = None
                        word['last_seen'] = None
                    words.append(classes.DBWord(
                        **word,
                        translations=[t[0] for t in result2]
                    ))
        return words

    async def insert_word(self, word: classes.WordData, user_id: int | None = None):
        async with self.pool.acquire() as connection, connection.cursor() as cursor:
            # word
            await cursor.execute("""
                INSERT INTO Words (id, word, shown_word, usage_example)
                VALUES (%s, %s, %s, %s);
            """, (word.id, word.word, word.shown_answer, word.usage_example))
            # translations
            translations = utils.split_translations(word.translations)
            await cursor.execute(f"""
                INSERT INTO WordTranslations (word_id, translation)
                VALUES {', '.join(('(%s, %s)',) * len(translations))};
            """, [i for t in translations for i in (word.id, t)])
            # seen data
            if user_id is not None:
                await cursor.execute(f"""
                    INSERT INTO WordHistory (word_id, user_id) 
                    VALUES (%s, %s);
                """, (word.id, user_id))

            await connection.commit()

    async def mark_word_as_seen(self, word_id: int, user_id: int):
        async with self.pool.acquire() as connection, connection.cursor() as cursor:
            await cursor.execute(f"""
                INSERT INTO WordHistory (word_id, user_id)
                VALUES (%s, %s)
                ON DUPLICATE KEY UPDATE seen_times = seen_times + 1;
            """, (word_id, user_id))
            await connection.commit()

    async def handle_word(self, word: classes.WordData, user_id: int):
        if await self.word_exists(word.id):
            await self.mark_word_as_seen(word.id, user_id)
        elif word.word is not None and word.shown_answer is not None:
            await self.insert_word(word, user_id)
        else:
            print(" ‼️ New word, but answer is missing!")

    async def capture_wordcounts_snapshot(self):
        async with self.pool.acquire() as connection, connection.cursor() as cursor:
            await cursor.execute("""
                INSERT INTO GlobalWordCountHistory (words, tasks, translations, unique_translations)
                SELECT
                    (SELECT COUNT(*) FROM Words) AS words,
                    (SELECT SUM(seen_times) FROM WordHistory) AS tasks,
                    COUNT(*) AS translations,
                    COUNT(DISTINCT translation) AS unique_translations
                FROM WordTranslations
            """)
            await cursor.execute("""
                INSERT INTO UserWordCountHistory (user_id, words, tasks, translations, unique_translations)
                SELECT
                    wh.user_id,
                    COUNT(DISTINCT w.id) AS words,
                    (SELECT SUM(wh2.seen_times) FROM WordHistory wh2 WHERE wh2.user_id = wh.user_id) AS tasks,
                    COUNT(*) AS translations,
                    COUNT(DISTINCT wt.translation) AS unique_translations
                FROM Words w
                JOIN WordHistory wh ON w.id = wh.word_id
                JOIN WordTranslations wt ON w.id = wt.word_id
                GROUP BY wh.user_id
            """)
            await connection.commit()
