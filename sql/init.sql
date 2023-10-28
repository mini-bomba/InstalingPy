CREATE TABLE InstalingBot.Words
(
    id            INT          NOT NULL PRIMARY KEY,
    word          VARCHAR(64)  NOT NULL,
    shown_word    VARCHAR(64)  NOT NULL,
    usage_example VARCHAR(256) NOT NULL
);

CREATE TABLE InstalingBot.WordTranslations
(
    id          INT AUTO_INCREMENT PRIMARY KEY,
    word_id     INT         NOT NULL,
    translation VARCHAR(64) NOT NULL,
    CONSTRAINT WordTranslations_Words_id_fk
        FOREIGN KEY (word_id) REFERENCES Words (id)
            ON UPDATE CASCADE ON DELETE CASCADE
);

CREATE INDEX WordTranslations_translation_index
    ON InstalingBot.WordTranslations (translation);

CREATE UNIQUE INDEX WordTranslations_word_id_translation_uindex
    ON InstalingBot.WordTranslations (word_id, translation);

CREATE TABLE InstalingBot.WordHistory
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

CREATE TABLE InstalingBot.GlobalWordCountHistory
(
    timestamp           DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    words               INT UNSIGNED NOT NULL,
    tasks               INT UNSIGNED NOT NULL,
    translations        INT UNSIGNED NOT NULL,
    unique_translations INT UNSIGNED NOT NULL
);

CREATE UNIQUE INDEX GlobalWordCountHistory_timestamp_uindex
    ON InstalingBot.GlobalWordCountHistory (timestamp DESC);


CREATE TABLE InstalingBot.UserWordCountHistory
(
    timestamp           DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    user_id             INT          NOT NULL,
    words               INT UNSIGNED NOT NULL,
    tasks               INT UNSIGNED NOT NULL,
    translations        INT UNSIGNED NOT NULL,
    unique_translations INT UNSIGNED NOT NULL
);

CREATE UNIQUE INDEX UserWordCountHistory_user_id_timestamp_index
    ON InstalingBot.UserWordCountHistory (user_id ASC, timestamp DESC);


CREATE TABLE InstalingBot.SessionHistory
(
    timestamp  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    user_id    INT      NOT NULL,
    start_time DATETIME NOT NULL,
    end_time   DATETIME NOT NULL,
    success    BOOL     NOT NULL
);

CREATE UNIQUE INDEX SessionHistory_timestamp_user_id_uindex
    ON InstalingBot.SessionHistory (timestamp DESC, user_id ASC);


CREATE USER instaling@localhost IDENTIFIED WITH 'unix_socket';
GRANT INSERT, SELECT, UPDATE ON InstalingBot.* TO instaling@localhost;
