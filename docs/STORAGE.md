# Storage layer

Metronix is heading toward two editions that share one memory/retrieval core and
differ only in the physical storage layer:

- **heavy / multi-tenant** — PostgreSQL + Qdrant + Neo4j + Redis (today's stack);
- **light / single-user** — SQLite, no separate vector service, a null/embedded
  graph, external model host.

This document tracks the seam between the two and is the **porting checklist** for
anyone writing a non-PostgreSQL implementation of a store.

---

## The seam: `STORAGE_BACKEND` + `metronix.storage.factory`

`STORAGE_BACKEND` (`Settings.storage_backend`, default `postgres`) selects the
relational backend. It is validated at config load and re-checked in
`metronix.storage.factory.require_supported_backend()`.

Every construction of the two relational stores goes through the factory:

| Factory function | Builds | Backs |
|---|---|---|
| `build_document_store(dsn)` | `PostgresStore` | `raw_documents`, `connections`, `sync_logs`, `connector_state`, dedup fingerprints, trace tables |
| `build_memory_store(engine)` | `MemoryPostgresStore` | `memory_records`, `review_entries`, dedup-simhash helpers |

### What Phase 0 did

- Added `STORAGE_BACKEND` (only `postgres` accepted) and `metronix/storage/factory.py`.
- Routed the scattered `PostgresStore(...)` / `MemoryPostgresStore(...)` calls in
  the hot paths through the factory: `mcp/tools/_memory_deps.py`,
  `mcp/tools/_source_deps.py`, `api/dependencies.py`, `api/app.py` (lifespan +
  proxy builder), `ingestion/pipeline.py`, `memory/freshness/worker.py`,
  `export/deps.py`, `app.py` (launcher).

### What Phase 0 did **not** do (deliberately, to keep behaviour byte-identical)

- No interface / `Protocol` extracted yet — the factory returns the concrete
  Postgres classes. Deriving `MemoryStorePort` / `DocumentStorePort` /
  `ConnectionStorePort` from the real method surface is Phase 2.
- Engine creation and caching still live at the call sites
  (`create_async_engine(...)`, `app.state.memory_pg_engine`). Moving the
  connection lifecycle behind the factory is Phase 2/3.
- No `ensure_schema()` for the core tables — schema is still alembic-only. A
  portable schema path (or a second migration set) is Phase 3.

### Remaining direct constructions (mechanical follow-up, not in Phase 0)

`api/routes/{graph,files,connections,admin}.py` (all behind an
`app.state.postgres` fallback that the lifespan already populates),
`benchmarker/api/generation.py`, `storage/migrate_env_connections.py` (a
pre-boot script). These construct only in isolated/test setups on the real path;
converting them also touches `test_files_routes.py` / `test_upload_alias.py` /
`test_benchmarker_endpoints.py`, so they were left for a follow-up PR.

---

## Porting checklist — non-portable SQL per store

Each store below is a concrete `asyncpg`/SQLAlchemy class holding raw SQL
strings. A SQLite (or other) implementation must replace the constructs listed.
Line numbers are approximate — grep the construct.

### `storage/memory_postgres.py` — `MemoryPostgresStore` (~53 KB) · **hardest**

| Construct | Where | Notes for a port |
|---|---|---|
| `tags @> CAST(:x AS jsonb)` (containment) | tag filter (~702, 714) | SQLite: `json_each` + `EXISTS`, or a tags join table |
| `tags \|\| CAST(:x AS jsonb)` (jsonb concat) | tag merge on update (~703) | rebuild the array in Python or `json_group_array` |
| `jsonb_agg(e) FROM jsonb_array_elements_text(CAST(:x AS jsonb)) WHERE NOT tags @> jsonb_build_array(e)` | dedup-append tags (~712–714) | needs an algorithmic rewrite, not a shim |
| `= ANY(:list)` | `kind` / `source_type` / `status` / `id` filters (~314–377, 549, 1032, 1056, 1086) | SQLite: expand to `IN (...)` with bound params |
| `unnest(CAST(:ids AS text[]))` + `unnest(CAST(:simhashes AS bigint[]))` | batch simhash lookup (~1290) | SQLite: `json_each` over two arrays, or a temp table |
| `NOW() - make_interval(days => :days)` | stale / recent windows (~1088, 1140) | SQLite: `datetime('now', :days \|\| ' days')` |
| `date_trunc('day', created_at)::date` | activity histogram (~1165) | SQLite: `date(created_at)` |
| `INTERVAL '1 minute'` | last-accessed throttle (~1035) | SQLite: `datetime(..., '-1 minute')` |
| `CAST(:x AS jsonb)` on `metadata` | insert/update (~197, 200) | store JSON as `TEXT`; `_as_json_dict` already tolerates str |
| `ON CONFLICT (id) DO UPDATE` + `RETURNING` | upsert (~200), ~22 `RETURNING` sites | SQLite ≥ 3.35 supports both; verify `EXCLUDED` forms |
| `content_simhash` as signed `BIGINT` via `_to_pg_bigint` / `_from_pg_bigint` | (~28, 48) | SQLite `INTEGER` is 64-bit signed — the conversion helpers already produce that |

### `storage/postgres.py` — `PostgresStore` (~79 KB) · **largest**

| Construct | Where | Notes |
|---|---|---|
| `SELECT ... FOR UPDATE` | `update_connection` (~472) | SQLite serialises writers DB-wide — drop the clause or app-lock |
| `claim_connection_for_sync` / `release_sync_claim` — conditional `UPDATE ... WHERE status != 'syncing' ... RETURNING id` and `WHERE sync_claim_id = :id RETURNING id` (#425) | (~587, ~632) | correctness leans on row-level MVCC; a SQLite port implements the claim with single-writer semantics or an app-level lock, exposed as an explicit port method in Phase 2 |
| `ON CONFLICT (...) DO UPDATE` | `set_connector_state` (~169), fingerprints | SQLite ≥ 3.35 |
| `= ANY(:ids)` / `= ANY(:source_ids)` | unsync / fingerprint queries (~1499, 1538, 1575) | expand to `IN (...)` |
| `CAST(:x AS JSONB)` / `::jsonb` | `connector_state`, sync-log errors (~433, 843, 939) | JSON as `TEXT` |
| `pg_try_advisory_lock` / `pg_advisory_lock` | (~1430) | SQLite: a file lock or in-process lock |
| `EXTRACT(EPOCH FROM (:now - created_at)) * 1000` | duration calc (also `recovery.py:47`) | SQLite: `(julianday(:now) - julianday(created_at)) * 86400000` |

### `storage/conversation_postgres.py` — `ConversationPostgresStore`

| Construct | Where | Notes |
|---|---|---|
| `FOR UPDATE SKIP LOCKED` | compaction-claim queue (~329) | **no SQLite equivalent** — move the queue into the single process or Redis |
| `FOR UPDATE` | (~400) | drop / app-lock |
| `jsonb_array_elements_text(CAST(:event_ids AS jsonb))` | (~451) | `json_each` |
| `ON CONFLICT` + `RETURNING` | (~250, ~354) | SQLite ≥ 3.35 |

*Flag-gated off by default (`METRONIX_CONVERSATION_COMPACTION_ENABLED=false`) — lowest priority; may be marked "postgres-only, not in the light build".*

### `storage/freshness_pg.py` — `FreshnessStore`

| Construct | Where | Notes |
|---|---|---|
| `ON CONFLICT` | lifecycle upserts (~121) | SQLite ≥ 3.35 |
| `CAST(:payload AS jsonb)` | (~369) | JSON as `TEXT` |
| Redis heartbeat / lock coordination (`CoordinationStore`) | freshness queue | not SQL — a light edition needs an in-process lock or drops the pipeline |

*Also flag-gated off by default (`METRONIX_FRESHNESS_ENABLED=false`).*

### `storage/activity_pg.py` — `ActivityStore`

| Construct | Where | Notes |
|---|---|---|
| `event_type = ANY(:event_types)` | list filter (~89) | expand to `IN (...)` |

Append-only insert + one filtered list — the smallest store, first target for the
port extraction (Phase 1).

### `storage/recovery.py` — startup recovery (module functions, sync engine)

| Construct | Where | Notes |
|---|---|---|
| `EXTRACT(EPOCH FROM (:now - created_at)) * 1000` | (~47) | see `postgres.py` note |
| `CAST(:err AS jsonb)` | (~46) | JSON as `TEXT` |
| runs on the **sync** engine (`pg_connection.py`) | — | shares the sync-engine wart with `WorkspaceManager` |

### Non-relational stores (separate ports, later phases)

| Store | File | Light-edition replacement |
|---|---|---|
| `QdrantVectorStore` / `AsyncQdrantVectorStore` | `storage/qdrant.py` | `sqlite-vec` `vec0` virtual table in the same DB file, or `pgvector` / in-process cosine scan. Surface to preserve: `add_document`, `search_dense`, `search_hybrid`, `delete_by_doc_labels`, `scroll`, `get_stats`, `_ensure_collection` |
| `MemoryQdrantStore` | `storage/memory_qdrant.py` | same; surface: `upsert`, `search`, `get`, `scroll`, `delete`, `delete_by_agent`, `update_payload` |
| Neo4j graph | `storage/{neo4j_graph,graph_ops,graph_entities,memory_graph}.py` (module functions) | recursive SQL over link tables (mnemosyne pattern), or a null graph. Already best-effort / try-except-wrapped on every read path |
| `RedisSessionCache` + queue/locks | `storage/{memory_redis,redis}.py` | in-process dict + `asyncio.Lock`; not on the base "put doc / ask / save note" path |

---

## Schema provisioning

34 alembic migrations, async env (`asyncpg`) + a psycopg2 sync DSN for the
migration advisory lock. **18** call sites use raw PostgreSQL-only DDL/DML in
`op.execute` — `gen_random_uuid()`, `md5()`, `::text` / `::jsonb` casts,
`ANY(:x)`, partial indexes (`CREATE INDEX ... WHERE ...`), `ARRAY` / `JSONB`
column types (migrations 001, 004, 009, 023, 025, 027, 032, …).

Porting options (Phase 3):

1. **Second hand-written migration set** (`migrations/sqlite/`) — mnemosyne does
   exactly this. Accepts the duplication; avoids a lowest-common-denominator DDL.
2. **Per-store `ensure_schema()`** — the auth stores (`UserStore`, `ApiKeyStore`,
   `PlatformUserMapper`) already do this and already run on SQLite in tests.

The Postgres edition keeps alembic; the new path is additive.

## Driver

`postgresql+asyncpg` throughout the app; `postgresql://` (psycopg2) for
migrations and the legacy sync `pg_connection.py` (`WorkspaceManager`, trace
writes). Finishing the long-postponed async migration of `pg_connection.py`
removes a second hidden Postgres coupling.

---

## Roadmap (summary)

| Phase | Scope |
|---|---|
| **0 (this)** | `STORAGE_BACKEND` + factory; centralize construction; this doc. No behaviour change. |
| 1 | Ports for the low-surface stores: `ActivityStore`, auth stores, vector, graph, session cache. Independent PRs. |
| 2 | Ports for `MemoryPostgresStore`, then `PostgresStore` (split into document / connection / trace), then conversation + freshness. |
| 3 | Schema provisioning path (second migration set or `ensure_schema()`). |
| — | SQLite implementations land *after* the ports exist, as their own PRs. |
