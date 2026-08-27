#!/bin/sh
#
# Idempotent dev -> local database snapshot, across two kube contexts.
# POSIX sh — no bash required.
#
#   DUMP    : in DUMP_CONTEXT (e.g. the dev/OpenShift cluster) run pg_dump
#             inside a pod that can reach the DB, streaming to the laptop.
#   RESTORE : in RESTORE_CONTEXT (e.g. k3d-mdm-local-k8s) drop + recreate a
#             local Postgres database and restore everything (schema, data,
#             indexes, constraints, matviews).
#
# SAFETY: the kube context is switched AND verified before each phase. The
# destructive drop/create is re-checked against RESTORE_CONTEXT immediately
# before it runs and refuses to proceed on any other context, so a DROP can
# never hit the source cluster. Every kubectl call also pins --context.
#
# Config: scripts/snapshot.env (gitignored). Copy the .example first.
# Alias:  alias ca-snapshot='sh ~/RuleManager/scripts/snapshot.sh'
set -eu
# Enable pipefail where the shell supports it, so a failed pg_dump in the
# dump|restore pipe aborts the run (dash lacks it — the test just no-ops).
if ( set -o pipefail ) 2>/dev/null; then set -o pipefail; fi

HERE=$(cd "$(dirname "$0")" && pwd)
ENV_FILE=${SNAPSHOT_ENV:-$HERE/snapshot.env}
if [ -f "$ENV_FILE" ]; then
    . "$ENV_FILE"
else
    echo "ERROR: $ENV_FILE not found. Copy scripts/snapshot.env.example to it and fill it in." >&2
    exit 1
fi

# ---- required / defaulted config ------------------------------------------
: "${DUMP_CONTEXT:?set DUMP_CONTEXT (kube context of the source cluster) in snapshot.env}"
: "${SRC_NS:?set SRC_NS (namespace of the pod that can reach the DB) in snapshot.env}"
: "${POD:?set POD (a pod that can reach the DB) in snapshot.env}"
: "${SRC_HOST:?set SRC_HOST in snapshot.env}"
: "${SRC_DB:?set SRC_DB in snapshot.env}"
: "${SRC_USER:?set SRC_USER in snapshot.env}"
: "${LOCAL_NS:?set LOCAL_NS (namespace of the local postgres pod) in snapshot.env}"
RESTORE_CONTEXT=${RESTORE_CONTEXT:-k3d-mdm-local-k8s}
SRC_PORT=${SRC_PORT:-5432}
SRC_SCHEMA=${SRC_SCHEMA:-}                   # empty = whole database
LOCAL_SUPERUSER=${LOCAL_SUPERUSER:-postgres}
TARGET_DB=${TARGET_DB:-$SRC_DB}
JOBS=${JOBS:-4}
LOCAL_POD=${LOCAL_POD:-}
LOCAL_SELECTOR=${LOCAL_SELECTOR:-}
LOCAL_PGPASSWORD=${LOCAL_PGPASSWORD:-}

command -v kubectl >/dev/null || { echo "ERROR: 'kubectl' not found." >&2; exit 1; }

if [ "$DUMP_CONTEXT" = "$RESTORE_CONTEXT" ]; then
    echo "ERROR: DUMP_CONTEXT and RESTORE_CONTEXT are identical ('$DUMP_CONTEXT'). Refusing — the drop must target a different cluster than the source." >&2
    exit 1
fi

# The dump is streamed straight into pg_restore — no temp file, no kubectl cp.
ORIGINAL_CONTEXT=$(kubectl config current-context 2>/dev/null || true)
cleanup() {
    [ -n "$ORIGINAL_CONTEXT" ] && kubectl config use-context "$ORIGINAL_CONTEXT" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

# ---- switch context and PROVE we're on it ---------------------------------
switch_and_verify() {
    want=$1
    kubectl config get-contexts -o name | grep -qx "$want" \
        || { echo "ERROR: kube context '$want' does not exist. Check DUMP_CONTEXT / RESTORE_CONTEXT." >&2; exit 1; }
    kubectl config use-context "$want" >/dev/null
    now=$(kubectl config current-context)
    [ "$now" = "$want" ] || { echo "ERROR: failed to switch to context '$want' (still on '$now')." >&2; exit 1; }
    echo "> context: $now"
}

# ==== PHASE 1: DUMP (source cluster) =======================================
echo "== Switching to SOURCE context to dump =="
switch_and_verify "$DUMP_CONTEXT"

kubectl --context "$DUMP_CONTEXT" -n "$SRC_NS" get pod "$POD" >/dev/null \
    || { echo "ERROR: pod '$POD' not found in namespace '$SRC_NS' on '$DUMP_CONTEXT'." >&2; exit 1; }

# resolve password (in the source context) unless supplied
if [ -z "${PGPASSWORD:-}" ]; then
    if [ -n "${SECRET:-}" ] && [ -n "${SECRET_KEY:-}" ]; then
        PGPASSWORD=$(kubectl --context "$DUMP_CONTEXT" -n "${SECRET_NS:-$SRC_NS}" \
            get secret "$SECRET" -o "jsonpath={.data.${SECRET_KEY}}" | base64 -d)
    else
        echo "ERROR: set PGPASSWORD, or SECRET + SECRET_KEY in snapshot.env." >&2; exit 1
    fi
fi
[ -n "$PGPASSWORD" ] || { echo "ERROR: resolved password is empty (wrong SECRET_KEY?)." >&2; exit 1; }
export PGPASSWORD

label="${SRC_DB}${SRC_SCHEMA:+ (schema $SRC_SCHEMA)}"

# ==== PHASE 2: RESTORE (local cluster) =====================================
echo "== Switching to LOCAL context to restore =="
switch_and_verify "$RESTORE_CONTEXT"

# resolve the local postgres pod
if [ -z "$LOCAL_POD" ]; then
    [ -n "$LOCAL_SELECTOR" ] || { echo "ERROR: set LOCAL_POD or LOCAL_SELECTOR in snapshot.env." >&2; exit 1; }
    LOCAL_POD=$(kubectl --context "$RESTORE_CONTEXT" -n "$LOCAL_NS" get pod -l "$LOCAL_SELECTOR" \
        -o jsonpath='{.items[0].metadata.name}')
    [ -n "$LOCAL_POD" ] || { echo "ERROR: no pod matches selector '$LOCAL_SELECTOR' in '$LOCAL_NS'." >&2; exit 1; }
fi
kubectl --context "$RESTORE_CONTEXT" -n "$LOCAL_NS" get pod "$LOCAL_POD" >/dev/null \
    || { echo "ERROR: local pod '$LOCAL_POD' not found in '$LOCAL_NS' on '$RESTORE_CONTEXT'." >&2; exit 1; }

# resolve the local superuser password (from a local secret, unless set directly)
if [ -z "$LOCAL_PGPASSWORD" ] && [ -n "${LOCAL_SECRET:-}" ] && [ -n "${LOCAL_SECRET_KEY:-}" ]; then
    LOCAL_PGPASSWORD=$(kubectl --context "$RESTORE_CONTEXT" -n "${LOCAL_SECRET_NS:-$LOCAL_NS}" \
        get secret "$LOCAL_SECRET" -o "jsonpath={.data.${LOCAL_SECRET_KEY}}" | base64 -d)
fi

# helper: run psql in the local pod (args after --); no stdin
local_psql() {
    kubectl --context "$RESTORE_CONTEXT" -n "$LOCAL_NS" exec "$LOCAL_POD" -- \
        env PGPASSWORD="$LOCAL_PGPASSWORD" psql -w -U "$LOCAL_SUPERUSER" "$@"
}

# ---- DESTRUCTIVE STEP: re-verify context immediately before the drop ------
NOW_CTX=$(kubectl config current-context)
if [ "$NOW_CTX" != "$RESTORE_CONTEXT" ] || [ "$NOW_CTX" = "$DUMP_CONTEXT" ]; then
    echo "ABORT: about to DROP DATABASE but context is '$NOW_CTX', not the restore target '$RESTORE_CONTEXT'." >&2
    exit 1
fi
echo "==> [1/4] Recreating ${TARGET_DB} on ${NOW_CTX}:${LOCAL_NS}/${LOCAL_POD} (drop + create) ..."
local_psql -d postgres -v ON_ERROR_STOP=1 \
    -c "DROP DATABASE IF EXISTS \"$TARGET_DB\" WITH (FORCE);" \
    -c "CREATE DATABASE \"$TARGET_DB\";"

echo "==> [2/4] Validating drop + create ..."
exists=$(local_psql -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname = '$TARGET_DB';" | tr -d '[:space:]')
[ "$exists" = "1" ] \
    || { echo "ERROR: database '$TARGET_DB' does not exist after create — aborting before restore." >&2; exit 1; }
pre=$(local_psql -d "$TARGET_DB" -tAc \
    "SELECT count(*) FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema');" | tr -d '[:space:]')
[ "$pre" = "0" ] \
    || { echo "ERROR: '$TARGET_DB' is not empty (${pre} tables) after recreate — aborting." >&2; exit 1; }
echo "    OK: '$TARGET_DB' exists and is empty."

# ---- stream the custom-format dump straight into pg_restore ---------------
# No intermediate file, no 'kubectl cp', no parallel -j — those corrupted the
# 339M archive. A single -Fc stream, restored in one pass.
echo "==> [3/4] Streaming ${label} from ${SRC_HOST} into ${TARGET_DB} ... (can take a while)"
if [ -n "$SRC_SCHEMA" ]; then
    kubectl --context "$DUMP_CONTEXT" -n "$SRC_NS" exec "$POD" -- env PGPASSWORD="$PGPASSWORD" \
        pg_dump -h "$SRC_HOST" -p "$SRC_PORT" -U "$SRC_USER" -d "$SRC_DB" -n "$SRC_SCHEMA" -Fc \
      | kubectl --context "$RESTORE_CONTEXT" -n "$LOCAL_NS" exec -i "$LOCAL_POD" -- env PGPASSWORD="$LOCAL_PGPASSWORD" \
        pg_restore -w -U "$LOCAL_SUPERUSER" -d "$TARGET_DB" --no-owner --no-privileges
else
    kubectl --context "$DUMP_CONTEXT" -n "$SRC_NS" exec "$POD" -- env PGPASSWORD="$PGPASSWORD" \
        pg_dump -h "$SRC_HOST" -p "$SRC_PORT" -U "$SRC_USER" -d "$SRC_DB" -Fc \
      | kubectl --context "$RESTORE_CONTEXT" -n "$LOCAL_NS" exec -i "$LOCAL_POD" -- env PGPASSWORD="$LOCAL_PGPASSWORD" \
        pg_restore -w -U "$LOCAL_SUPERUSER" -d "$TARGET_DB" --no-owner --no-privileges
fi

echo "==> [4/4] Validating restore ..."
count_schema=${SRC_SCHEMA:-public}
tables=$(local_psql -d "$TARGET_DB" -tAc \
    "SELECT count(*) FROM information_schema.tables WHERE table_schema = '$count_schema';" | tr -d '[:space:]')
{ [ -n "$tables" ] && [ "$tables" -gt 0 ] 2>/dev/null; } \
    || { echo "ERROR: no tables found in schema '$count_schema' after restore." >&2; exit 1; }

echo "OK Snapshot ready on ${RESTORE_CONTEXT}: ${TARGET_DB} — ${tables} tables in schema '${count_schema}'."
echo "   Point the audit at the local DB and run:  uv run audit.py"
