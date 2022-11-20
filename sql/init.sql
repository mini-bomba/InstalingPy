CREATE TABLE Words(
    id INT NOT NULL PRIMARY KEY,
    word VARCHAR(64) NOT NULL,
    shown_word VARCHAR(64) NOT NULL,
    usage_example VARCHAR(256) NOT NULL
);

CREATE TABLE WordTranslations
(
    id          INT AUTO_INCREMENT PRIMARY KEY,
    word_id     INT         NOT NULL,
    translation VARCHAR(64) NOT NULL,
    CONSTRAINT WordTranslations_Words_id_fk
        FOREIGN KEY (word_id) REFERENCES Words (id)
        ON UPDATE CASCADE ON DELETE CASCADE
);

CREATE INDEX WordTranslations_translation_index
    ON WordTranslations (translation);

CREATE UNIQUE INDEX WordTranslations_word_id_translation_uindex
    ON InstalingBot.WordTranslations (word_id, translation);

CREATE TABLE WordHistory
(
    word_id    INT                                NOT NULL,
    user_id    INT                                NOT NULL,
    seen_times INT      DEFAULT 1                 NOT NULL,
    last_seen  DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT WordHistory_pk
        PRIMARY KEY (word_id, user_id),
    CONSTRAINT WordHistory_Words_null_fk
        FOREIGN KEY (word_id) REFERENCES Words (id)
        ON UPDATE CASCADE ON DELETE CASCADE
);

CREATE USER instaling@localhost IDENTIFIED WITH 'unix_socket';
GRANT INSERT, SELECT, UPDATE ON InstalingBot.* TO instaling@localhost;

