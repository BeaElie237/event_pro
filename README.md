# EventPro — Agrégation & recommandation intelligente d'événements

Plateforme qui agrège des événements professionnels et académiques (conférences, hackathons,
bourses, fellowships, subventions…, financés ou non), centrée sur l'Afrique et ouverte au monde.
Les données passent par un pipeline batch et streaming, sont stockées dans PostgreSQL + pgvector,
puis servies par une API FastAPI qui fait du matching sémantique avec le profil de l'utilisateur.

## Architecture

```
            ┌──────────── BATCH (quotidien, Airflow) ─────────────┐
 Sources    │ scrape_source ×N ─► data/raw ─► Spark clean/dedup/  │
 RSS / API ─┤   (mapped tasks)     (JSONL)    embed ─► data/      │
            │                                processed (parquet) │
            │                 Spark JDBC ─► staging_events ─► MERGE ─┐
            └─────────────────────────────────────────────────────┘ │
                                                                    ▼
 Webhooks ─► streaming-webhook ─► Kafka (Redpanda) ─► consumer ─► PostgreSQL + pgvector
 partenaires  (HMAC, 202)        events.incoming      normalise    events / users /
                                 events.dlq           + embed      user_profiles (HNSW)
                                                                    │
                                              FastAPI ◄─────────────┘
                                   /events  /events/search  /recommendations
```

La logique métier (taxonomie, dates FR/EN, géo Afrique, fingerprint de déduplication, texte
d'embedding) est écrite **une seule fois** dans `common/` et partagée par Spark, le consumer et
l'API. Un même événement reçu par le batch et par le stream obtient donc le même `fingerprint`
et donne une seule ligne en base.

## Arborescence

```
EVENT/
├── docker-compose.yml          # Postgres/pgvector, Airflow 3, API (+ profil streaming)
├── .env.example                # à copier en .env
├── common/                     # package partagé eventpro_common
│   ├── src/eventpro_common/
│   │   ├── taxonomy.py         # enums + classifieurs catégorie / financement / format
│   │   ├── text.py             # nettoyage HTML, URL canonique, fingerprint sha256
│   │   ├── dates.py            # parsing dates ISO / EN / FR, plages "12 au 15 mars"
│   │   ├── geo.py              # 54 pays africains + hubs mondiaux, villes
│   │   ├── embeddings.py       # modèle multilingue, templates texte événement/profil
│   │   ├── schemas.py          # RawEvent / NormalizedEvent (Pydantic)
│   │   └── normalization.py    # RawEvent -> NormalizedEvent (fonction pure)
│   └── tests/
├── database/
│   └── init.sql                # schéma complet (events, users, user_profiles, staging…)
├── airflow/
│   ├── Dockerfile              # Airflow 3 + Java 17 + PySpark + torch CPU
│   ├── dags/
│   │   ├── events_batch_pipeline.py
│   │   └── sql/                # merge_staging_events.sql, expire_events.sql
│   ├── include/
│   │   ├── sources.yaml        # sources de scraping déclaratives
│   │   └── scrapers/           # base, rss, json_api, registry, writer
│   └── plugins/  logs/
├── spark/
│   └── jobs/
│       ├── clean_events.py     # normalisation + dédup + embeddings (pandas UDF)
│       ├── load_events.py      # parquet -> staging_events (JDBC)
│       └── spark_utils.py
├── streaming/
│   ├── app/
│   │   ├── webhook.py          # FastAPI : réception signée -> Kafka
│   │   ├── consumer.py         # Kafka -> normalise -> embed -> upsert (DLQ)
│   │   ├── repository.py
│   │   └── config.py
│   └── scripts/send_sample_event.py
├── backend/
│   ├── app/
│   │   ├── main.py             # app factory + lifespan (chargement du modèle)
│   │   ├── core/               # config (pydantic-settings), sécurité (Argon2, JWT)
│   │   ├── db/                 # engine async + codec pgvector
│   │   ├── models/             # SQLAlchemy 2.0 typé
│   │   ├── schemas/            # Pydantic v2
│   │   ├── repositories/       # accès données (full-text, vecteurs)
│   │   ├── services/           # embeddings, scoring hybride, recommandation
│   │   └── api/v1/endpoints/   # auth, users, events, recommendations, health
│   └── tests/
└── data/
    ├── raw/                    # <source>/batch_date=YYYY-MM-DD/events.jsonl
    └── processed/              # events/ et rejected/ par batch_date
```

## Démarrage

Prérequis : Docker Desktop avec **au moins 8 Go de RAM** (Spark et les modèles d'embedding
tournent en local).

```bash
cp .env.example .env            # puis remplacer toutes les valeurs change-me-*
docker compose up -d --build    # Postgres + Airflow + API
docker compose --profile streaming up -d --build   # optionnel : Kafka + webhook + consumer
```

| Service    | URL                                  |
|------------|--------------------------------------|
| API (docs) | http://localhost:8000/docs           |
| Airflow    | http://localhost:8080 (admin / `.env`) |
| Webhook    | http://localhost:8001/webhooks/events |
| Postgres   | localhost:5432                       |

Au premier démarrage, chaque service télécharge le modèle
`paraphrase-multilingual-MiniLM-L12-v2` (~470 Mo, mis en cache dans un volume Docker).

### Lancer le pipeline batch

Dans Airflow, activer le DAG `events_batch_pipeline` puis le déclencher (▶). Ou en ligne de commande :

```bash
docker compose exec airflow-scheduler airflow dags unpause events_batch_pipeline
docker compose exec airflow-scheduler airflow dags trigger events_batch_pipeline
```

### Tester le streaming

```bash
python streaming/scripts/send_sample_event.py --secret "<WEBHOOK_SECRET>"
# -> 202 {"accepted": 1} ; l'événement est en base quelques secondes après
```

### Exemple de parcours API

```bash
# 1. Compte + token
curl -X POST localhost:8000/api/v1/auth/register -H "Content-Type: application/json" \
     -d '{"email":"awa@example.com","password":"Sup3rSecret!","full_name":"Awa"}'
TOKEN=$(curl -s -X POST localhost:8000/api/v1/auth/token \
     -d "username=awa@example.com&password=Sup3rSecret!" | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

# 2. Profil (l'embedding est calculé à l'enregistrement)
curl -X PUT localhost:8000/api/v1/users/me/profile -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/json" -d '{
       "headline":"Data scientist junior", "skills":["python","machine learning","NLP"],
       "interests":["IA pour la santé","agritech"], "goals":["trouver un master financé"],
       "preferred_categories":["scholarship","hackathon"], "country_code":"CM",
       "requires_funding":true }'

# 3. Recommandations personnalisées (avec explications)
curl "localhost:8000/api/v1/recommendations/me?limit=10&africa_only=true" -H "Authorization: Bearer $TOKEN"

# Recherche sémantique libre / plein texte
curl "localhost:8000/api/v1/events/search?q=bourse%20master%20intelligence%20artificielle"
curl "localhost:8000/api/v1/events?q=hackathon&categories=hackathon&funding_types=fully_funded"
```

## Comment fonctionne le matching

1. **Récupération** : le profil (compétences, objectifs, intérêts, lieu) est transformé en
   texte, puis en vecteur normalisé de 384 dimensions. pgvector renvoie les 200 événements actifs
   les plus proches en distance cosinus (`<=>`, index HNSW, `iterative_scan` pour que les filtres
   ne vident pas le résultat).
2. **Re-ranking explicable** ([backend/app/services/scoring.py](backend/app/services/scoring.py)) :

   | Signal     | Poids | Règle |
   |------------|-------|-------|
   | sémantique | 0.70  | similarité cosinus |
   | lieu       | 0.10  | en ligne / même pays = 1, hybride 0.8, même continent 0.7 |
   | catégorie  | 0.10  | dans les préférences = 1 |
   | financement| 0.07  | si financement requis : complet 1, partiel 0.6 |
   | urgence    | 0.03  | clôture dans moins de 30 jours |

   Chaque résultat renvoie `score`, `breakdown` et `reasons` (« Entièrement financé »,
   « Clôture dans 3 jours »…).

## Déduplication

- **Clé** : `fingerprint = sha256(titre_normalisé | date_début_ou_deadline | pays_ou_lieu)`.
  Le titre normalisé est en minuscules, sans accents ni ponctuation ; le pays est déduit de la
  ville quand c'est possible (« Kigali » → `RW`).
- **Spark** fait deux passes : d'abord par URL canonique (sans `utm_*`, sans `www`, en https),
  puis par fingerprint. Dans chaque groupe, on garde l'enregistrement le plus complet, puis le
  plus récent.
- **En base** : `ON CONFLICT (fingerprint) DO UPDATE` (dans le batch comme dans le stream) ne
  remplace jamais une valeur connue par `NULL` ou `unknown`.

## Tests

```bash
pip install -e "common[dev]" && pytest common
pip install -r backend/requirements-dev.txt -e common && cd backend && pytest
```

## Pistes pour la suite

- Migrations Alembic une fois le schéma stabilisé (aujourd'hui, `init.sql` fait foi).
- Notifications : nouvel événement en streaming → recherche des profils proches via l'index HNSW
  de `user_profiles`.
- Utiliser les signaux de `user_event_interactions` dans le re-ranking.
- Frontend (Next.js) et CI GitHub Actions (lint, mypy, pytest, build des images).
