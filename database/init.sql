-- =============================================================================
-- EventPro — schéma applicatif (PostgreSQL 16 + pgvector)
--
-- Exécuté automatiquement au PREMIER démarrage du conteneur `postgres`
-- (docker-entrypoint-initdb.d). Pour le rejouer : docker compose down -v.
--
-- Dimension des vecteurs : 384 = sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2.
-- Changer de modèle implique de modifier vector(384) ET de ré-embedder les données.
-- Les enums sont synchronisés avec common/src/eventpro_common/taxonomy.py.
-- =============================================================================

BEGIN;

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS citext;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- -----------------------------------------------------------------------------
-- Types énumérés
-- -----------------------------------------------------------------------------
CREATE TYPE event_category AS ENUM (
    'conference', 'hackathon', 'scholarship', 'fellowship', 'grant',
    'workshop', 'webinar', 'competition', 'internship', 'training', 'other'
);

CREATE TYPE funding_type AS ENUM ('fully_funded', 'partially_funded', 'not_funded', 'unknown');

CREATE TYPE event_format AS ENUM ('in_person', 'online', 'hybrid', 'unknown');

CREATE TYPE event_status AS ENUM ('active', 'expired', 'cancelled');

CREATE TYPE ingestion_channel AS ENUM ('batch', 'stream', 'manual');

CREATE TYPE interaction_type AS ENUM ('view', 'click', 'save', 'apply', 'dismiss');

-- -----------------------------------------------------------------------------
-- Fonctions utilitaires
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

-- Un événement est expiré si la date limite de candidature est passée,
-- ou si l'événement lui-même est terminé.
CREATE OR REPLACE FUNCTION compute_event_status(p_start date, p_end date, p_deadline date)
RETURNS event_status
LANGUAGE sql STABLE AS $$
    SELECT CASE
        WHEN p_deadline < current_date THEN 'expired'::event_status
        WHEN GREATEST(p_start, p_end) < current_date THEN 'expired'::event_status
        ELSE 'active'::event_status
    END;
$$;

-- -----------------------------------------------------------------------------
-- events : catalogue unifié (batch + streaming)
-- -----------------------------------------------------------------------------
CREATE TABLE events (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    -- sha256(titre normalisé | date | pays-ou-lieu) : clé de déduplication cross-sources
    fingerprint        text NOT NULL UNIQUE CHECK (fingerprint ~ '^[0-9a-f]{64}$'),
    source             text NOT NULL,
    source_event_id    text,
    title              text NOT NULL CHECK (char_length(title) BETWEEN 3 AND 500),
    description        text,
    url                text,
    category           event_category NOT NULL DEFAULT 'other',
    funding_type       funding_type   NOT NULL DEFAULT 'unknown',
    event_format       event_format   NOT NULL DEFAULT 'unknown',
    status             event_status   NOT NULL DEFAULT 'active',
    organizer          text,
    location_raw       text,
    city               text,
    country_code       char(2),
    country_name       text,
    continent          text,
    is_africa          boolean GENERATED ALWAYS AS (coalesce(continent = 'Africa', false)) STORED,
    start_date         date,
    end_date           date,
    deadline           date,
    tags               text[] NOT NULL DEFAULT '{}',
    language           varchar(8),
    embedding          vector(384),
    embedding_model    text,
    ingestion_channel  ingestion_channel NOT NULL DEFAULT 'batch',
    raw_payload        jsonb NOT NULL DEFAULT '{}'::jsonb,
    search             tsvector GENERATED ALWAYS AS (
                           setweight(to_tsvector('simple', coalesce(title, '')), 'A') ||
                           setweight(to_tsvector('simple', coalesce(organizer, '') || ' ' || coalesce(location_raw, '')), 'B') ||
                           setweight(to_tsvector('simple', coalesce(description, '')), 'C')
                       ) STORED,
    scraped_at         timestamptz,
    first_seen_at      timestamptz NOT NULL DEFAULT now(),
    last_seen_at       timestamptz NOT NULL DEFAULT now(),
    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT events_dates_chk CHECK (end_date IS NULL OR start_date IS NULL OR end_date >= start_date)
);

COMMENT ON COLUMN events.fingerprint IS 'sha256(normalize(title)|start_or_deadline|country_or_location) — voir eventpro_common.text.compute_fingerprint';
COMMENT ON COLUMN events.embedding   IS 'Embedding normalisé L2 (cosine) de build_event_text()';

-- Recherche vectorielle approximative (cosine) — opérateur <=>
CREATE INDEX events_embedding_hnsw_idx ON events
    USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);
CREATE INDEX events_search_idx          ON events USING gin (search);
CREATE INDEX events_title_trgm_idx      ON events USING gin (title gin_trgm_ops);
CREATE INDEX events_tags_idx            ON events USING gin (tags);
CREATE INDEX events_status_dates_idx    ON events (status, deadline, start_date);
CREATE INDEX events_category_funding_idx ON events (category, funding_type);
CREATE INDEX events_country_idx         ON events (country_code);
-- Non unique : un titre modifié à la source produit un nouveau fingerprint
CREATE INDEX events_source_ref_idx      ON events (source, source_event_id);

CREATE TRIGGER events_set_updated_at
    BEFORE UPDATE ON events
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- -----------------------------------------------------------------------------
-- staging_events : zone d'atterrissage du job Spark (JDBC), fusionnée ensuite
-- dans `events` par airflow/dags/sql/merge_staging_events.sql.
-- UNLOGGED : pas de WAL, table jetable rechargée à chaque batch.
-- -----------------------------------------------------------------------------
CREATE UNLOGGED TABLE staging_events (
    fingerprint      text NOT NULL,
    source           text NOT NULL,
    source_event_id  text,
    title            text NOT NULL,
    description      text,
    url              text,
    category         text,
    funding_type     text,
    event_format     text,
    organizer        text,
    location_raw     text,
    city             text,
    country_code     text,
    country_name     text,
    continent        text,
    start_date       date,
    end_date         date,
    deadline         date,
    tags             text,        -- tableau JSON
    language         text,
    embedding        text,        -- littéral pgvector '[0.1,...]'
    embedding_model  text,
    raw_payload      text,        -- objet JSON
    scraped_at       timestamptz,
    batch_date       date NOT NULL
);

-- -----------------------------------------------------------------------------
-- users / user_profiles
-- -----------------------------------------------------------------------------
CREATE TABLE users (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email            citext NOT NULL UNIQUE,
    hashed_password  text NOT NULL,
    full_name        text,
    is_active        boolean NOT NULL DEFAULT true,
    is_superuser     boolean NOT NULL DEFAULT false,
    last_login_at    timestamptz,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now()
);

CREATE TRIGGER users_set_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE user_profiles (
    user_id               uuid PRIMARY KEY REFERENCES users (id) ON DELETE CASCADE,
    headline              text,
    bio                   text,
    skills                text[] NOT NULL DEFAULT '{}',
    interests             text[] NOT NULL DEFAULT '{}',
    goals                 text[] NOT NULL DEFAULT '{}',
    -- valeurs de event_category / event_format (validées côté API)
    preferred_categories  text[] NOT NULL DEFAULT '{}',
    preferred_formats     text[] NOT NULL DEFAULT '{}',
    languages             text[] NOT NULL DEFAULT '{}',
    country_code          char(2),
    city                  text,
    career_stage          text,
    requires_funding      boolean NOT NULL DEFAULT false,
    open_to_travel        boolean NOT NULL DEFAULT true,
    embedding             vector(384),
    embedding_model       text,
    embedding_updated_at  timestamptz,
    created_at            timestamptz NOT NULL DEFAULT now(),
    updated_at            timestamptz NOT NULL DEFAULT now()
);

-- Permet la requête inverse : « quels utilisateurs notifier pour ce nouvel événement ? »
CREATE INDEX user_profiles_embedding_hnsw_idx ON user_profiles
    USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);
CREATE INDEX user_profiles_country_idx ON user_profiles (country_code);

CREATE TRIGGER user_profiles_set_updated_at
    BEFORE UPDATE ON user_profiles
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- -----------------------------------------------------------------------------
-- user_event_interactions : signaux implicites pour le futur re-ranking
-- -----------------------------------------------------------------------------
CREATE TABLE user_event_interactions (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id      uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    event_id     uuid NOT NULL REFERENCES events (id) ON DELETE CASCADE,
    interaction  interaction_type NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT user_event_interactions_uniq UNIQUE (user_id, event_id, interaction)
);

CREATE INDEX user_event_interactions_event_idx ON user_event_interactions (event_id);

COMMIT;
