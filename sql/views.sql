CREATE SQL SECURITY INVOKER VIEW Dictionary
AS
SELECT WordTranslations.translation, Words.word, Words.shown_word, Words.usage_example
FROM WordTranslations
         LEFT JOIN Words ON WordTranslations.word_id = Words.id
ORDER BY WordTranslations.translation;