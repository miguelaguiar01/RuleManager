#!/usr/bin/env bash
#
# Idempotent dev -> local database snapshot.
#
# Dumps a schema (or whole DB) from a database that is only reachable from
# inside the cluster, by running pg_dump *in a pod that can reach it* and
# streaming the result straight to the laptop (nothing is left in the pod, no
# proxy is opened). Then it drops and recreates a local Docker Postgres
# database and restores the snapshot in full — schema, data, indexes,
# constraints, materialized views.
#
# Every run rebuilds from scratch, so it is safe to re-run any time.
#
# Config comes from scripts/snapshot.env (gitignored). Copy the .example first.
# Alias it, e.g.:  alias ca-snapshot='bash ~/RuleManager/scripts/snapshot.sh'
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SNAPSHOT_ENV:-$HERE/snapshot.env}"
if [[ -f "$ENV_FILE" ]]; then
    # shellcheck disable=SC1090
    source "$ENV_FILE"
else
    echo "ERROR: $ENV_FILE not found. Copy scripts/snapshot.env.example to it and fill it in." >&2
    exit 1
fi

# ---- required / defaulted config ------------------------------------------
: "${NAMESPACE:?set NAMESPACE in snapshot.env}"
: "${POD:?set POD (a pod that can reach the DB) in snapshot.env}"
: "${SRC_HOST:?set SRC_HOST in snapshot.env}"
: "${SRC_DB:?set SRC_DB in snapshot.env}"
: "${SRC_USER:?set SRC_USER in snapshot.env}"
: "${LOCAL_CONTAINER:?set LOCAL_CONTAINER (local docker postgres) in snapshot.env}"
SRC_PORT="${SRC_PORT:-5432}"
SRC_SCHEMA="${SRC_SCHEMA:-}"                 # empty = whole database
LOCAL_SUPERUSER="${LOCAL_SUPERUSER:-postgres}"
TARGET_DB="${TARGET_DB:-$SRC_DB}"
JOBS="${JOBS:-4}"

LOCAL_DUMP="$(mktemp -t ca-snapshot.XXXXXX.dump)"
CONTAINER_DUMP="/tmp/ca-snapshot.dump"
cleanup() {
    rm -f "$LOCAL_DUMP"
    docker exec "$LOCAL_CONTAINER" rm -f "$CONTAINER_DUMP" 2>/dev/null || true
}
trap cleanup EXIT

# ---- resolve the password (never stored in the repo) ----------------------
if [[ -z "${PGPASSWORD:-}" ]]; then
    if [[ -n "${SECRET:-}" && -n "${SECRET_KEY:-}" ]]; then
        PGPASSWORD="$(oc get secret "$SECRET" -n "${SECRET_NS:-$NAMESPACE}" \
            -o "jsonpath={.data.${SECRET_KEY}}" | base64 -d)"
    else
        echo "ERROR: set PGPASSWORD, or SECRET + SECRET_KEY (to fetch it from the cluster) in snapshot.env." >&2
        exit 1
    fi
fi
[[ -n "$PGPASSWORD" ]] || { echo "ERROR: resolved password is empty (wrong SECRET_KEY?)." >&2; exit 1; }

# ---- preflight ------------------------------------------------------------
command -v oc >/dev/null     || { echo "ERROR: 'oc' not found." >&2; exit 1; }
command -v docker >/dev/null || { echo "ERROR: 'docker' not found." >&2; exit 1; }
oc whoami >/dev/null 2>&1    || { echo "ERROR: not logged into oc (run 'oc login')." >&2; exit 1; }
docker inspect "$LOCAL_CONTAINER" >/dev/null 2>&1 \
    || { echo "ERROR: local docker container '$LOCAL_CONTAINER' is not running." >&2; exit 1; }

schema_flag=()
[[ -n "$SRC_SCHEMA" ]] && schema_flag=(-n "$SRC_SCHEMA")
label="${SRC_DB}${SRC_SCHEMA:+ (schema $SRC_SCHEMA)}"

# ---- 1. dump straight out of the pod (no pod disk, no proxy) ---------------
echo "==> [1/4] Dumping ${label} from ${SRC_HOST} via pod ${POD} … (this can take a while)"
oc exec -n "$NAMESPACE" "$POD" -- env PGPASSWORD="$PGPASSWORD" \
    pg_dump -h "$SRC_HOST" -p "$SRC_PORT" -U "$SRC_USER" -d "$SRC_DB" \
    "${schema_flag[@]}" -Fc > "$LOCAL_DUMP"
[[ -s "$LOCAL_DUMP" ]] || { echo "ERROR: dump is empty — check credentials / schema name." >&2; exit 1; }
echo "    dump size: $(du -h "$LOCAL_DUMP" | cut -f1)"

# ---- 2. move the dump into the local container ----------------------------
echo "==> [2/4] Copying dump into ${LOCAL_CONTAINER} …"
docker cp "$LOCAL_DUMP" "$LOCAL_CONTAINER:$CONTAINER_DUMP"

# ---- 3. drop + recreate the local database (idempotent) -------------------
echo "==> [3/4] Recreating local database ${TARGET_DB} (drop + create) …"
docker exec "$LOCAL_CONTAINER" psql -U "$LOCAL_SUPERUSER" -d postgres -v ON_ERROR_STOP=1 \
    -c "DROP DATABASE IF EXISTS \"$TARGET_DB\" WITH (FORCE);" \
    -c "CREATE DATABASE \"$TARGET_DB\";"

# ---- 4. restore everything ------------------------------------------------
echo "==> [4/4] Restoring snapshot (schema, data, indexes, constraints, matviews) …"
docker exec "$LOCAL_CONTAINER" pg_restore -U "$LOCAL_SUPERUSER" -d "$TARGET_DB" \
    --no-owner --no-privileges -j "$JOBS" "$CONTAINER_DUMP"

# ---- sanity: how many tables landed ---------------------------------------
count_schema="${SRC_SCHEMA:-public}"
tables="$(docker exec "$LOCAL_CONTAINER" psql -U "$LOCAL_SUPERUSER" -d "$TARGET_DB" -tAc \
    "SELECT count(*) FROM information_schema.tables WHERE table_schema = '$count_schema';" | tr -d '[:space:]')"

echo "✓ Snapshot ready: ${LOCAL_CONTAINER}:${TARGET_DB} — ${tables} tables in schema '${count_schema}'."
echo "  Point the audit at this local DB and run:  uv run audit.py"
