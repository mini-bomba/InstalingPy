from libs import classes, database, instaling, utils
import getpass
import asyncio


async def main():
    user = input("Username: ")
    password = getpass.getpass("Password: ")
    async with database.DatabaseManager(pool_recycle=60, user="mini_bomba", password="", db="InstalingBot",
                                        unix_socket="/var/run/mysqld/mysqld.sock") as db:
        async with instaling.Session(user, password) as session:
            del user, password
            print("Login successful. Beginning session.")
            async for word in session:
                word: classes.WordData
                if word.type == "marketing":
                    print("Marketing skipped")
                    continue
                db_word = await db.get_word(word.id, session.user_id)
                print("-"*15)
                print(word.usage_example)
                print(f"Translations: {', '.join(utils.split_translations(word.translations))}")
                print(f"Question type: {word.type}; Difficulty: {word.difficulty}")
                if db_word is None:
                    print("This word does not exist in the database.")
                else:
                    print(f"Word found in the database: {db_word.shown_word} (or {db_word.word})")
                    print(f"You've seen this word {db_word.seen_times} times.")
                    print(f"Last seen on {db_word.last_seen.ctime()}")
                answer = input("Answer: ")
                result = await session.submit_answer(word.id, answer)
                print(f"Result: {result.grade.name}")
                print(f"The answer: {result.shown_answer} (or {result.word})")
                print(f"Completed sentence: {result.usage_example}")
                if result.word is not None and result.shown_answer is not None and db_word is None:
                    await db.insert_word(result, session.user_id)
                    print("Word inserted into the database.")
                elif db_word is not None:
                    await db.mark_word_as_seen(word.id, session.user_id)
            print("Session finished!")


if __name__ == "__main__":
    asyncio.run(main())
