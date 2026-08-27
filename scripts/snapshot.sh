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

# rsync (via oc) is used for the transfer — reliable over a lossy exec channel.
command -v oc >/dev/null || { echo "ERROR: 'oc' is required (used for 'oc rsync')." >&2; exit 1; }

LOCAL_STAGE=
ORIGINAL_CONTEXT=$(kubectl config current-context 2>/dev/null || true)
cleanup() {
    [ -n "${LOCAL_STAGE:-}" ] && rm -rf "$LOCAL_STAGE" 2>/dev/null || true
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

# ---- dump to a COMPLETE file in the source pod, transfer it verified, restore
# Streaming pg_dump straight through 'kubectl exec' truncates the tail of large
# binary archives (the exec stream closes before the last buffer flushes), which
# is what gave "end of file". Writing a full file on the pod's disk, then copying
# it with a byte-count check + retry, is reliable. The dump stays custom format.
# Stage the dump in a directory in each pod; rsync it pod -> laptop -> pod.
# rsync checksums and retransmits, so it converges over the lossy exec channel
# (plain 'kubectl exec | cat' dropped bytes non-deterministically).
POD_DIR=/tmp/ca-snapshot.d
DUMP_NAME=snapshot.dump
schema_arg=
[ -n "$SRC_SCHEMA" ] && schema_arg="-n $SRC_SCHEMA"

echo "==> [3/4] Dumping ${label} to a file in ${SRC_NS}/${POD} ... (can take a while)"
src_size=$(kubectl --context "$DUMP_CONTEXT" -n "$SRC_NS" exec "$POD" -- \
    env PGPASSWORD="$PGPASSWORD" sh -c \
    "mkdir -p '$POD_DIR' && pg_dump -h '$SRC_HOST' -p '$SRC_PORT' -U '$SRC_USER' -d '$SRC_DB' $schema_arg -Fc -f '$POD_DIR/$DUMP_NAME' && wc -c < '$POD_DIR/$DUMP_NAME'" \
    | tr -d '[:space:]')
{ [ -n "$src_size" ] && [ "$src_size" -gt 0 ] 2>/dev/null; } \
    || { echo "ERROR: dump failed or is empty in the source pod." >&2; exit 1; }
echo "    dumped ${src_size} bytes."

LOCAL_STAGE=$(mktemp -d "${TMPDIR:-/tmp}/ca-snapshot.XXXXXX")

echo "    rsync: source pod -> laptop ..."
oc rsync --context "$DUMP_CONTEXT" -n "$SRC_NS" --no-perms --compress "$POD:$POD_DIR/" "$LOCAL_STAGE/" >/dev/null
local_size=$(wc -c < "$LOCAL_STAGE/$DUMP_NAME" | tr -d '[:space:]')
[ "$local_size" = "$src_size" ] \
    || { echo "ERROR: rsync to laptop incomplete (src=${src_size} laptop=${local_size})." >&2; exit 1; }

echo "    rsync: laptop -> local pod ..."
kubectl --context "$RESTORE_CONTEXT" -n "$LOCAL_NS" exec "$LOCAL_POD" -- mkdir -p "$POD_DIR"
oc rsync --context "$RESTORE_CONTEXT" -n "$LOCAL_NS" --no-perms --compress "$LOCAL_STAGE/" "$LOCAL_POD:$POD_DIR/" >/dev/null
dst_size=$(kubectl --context "$RESTORE_CONTEXT" -n "$LOCAL_NS" exec "$LOCAL_POD" -- \
    sh -c "wc -c < '$POD_DIR/$DUMP_NAME'" | tr -d '[:space:]')
[ "$dst_size" = "$src_size" ] \
    || { echo "ERROR: rsync into local pod incomplete (src=${src_size} dst=${dst_size})." >&2; exit 1; }
echo "    transfer verified (${src_size} bytes). Restoring ..."

kubectl --context "$RESTORE_CONTEXT" -n "$LOCAL_NS" exec "$LOCAL_POD" -- \
    env PGPASSWORD="$LOCAL_PGPASSWORD" \
    pg_restore -w -U "$LOCAL_SUPERUSER" -d "$TARGET_DB" --no-owner --no-privileges -j "$JOBS" "$POD_DIR/$DUMP_NAME"

kubectl --context "$DUMP_CONTEXT" -n "$SRC_NS" exec "$POD" -- rm -rf "$POD_DIR" >/dev/null 2>&1 || true
kubectl --context "$RESTORE_CONTEXT" -n "$LOCAL_NS" exec "$LOCAL_POD" -- rm -rf "$POD_DIR" >/dev/null 2>&1 || true

echo "==> [4/4] Validating restore ..."
count_schema=${SRC_SCHEMA:-public}
tables=$(local_psql -d "$TARGET_DB" -tAc \
    "SELECT count(*) FROM information_schema.tables WHERE table_schema = '$count_schema';" | tr -d '[:space:]')
{ [ -n "$tables" ] && [ "$tables" -gt 0 ] 2>/dev/null; } \
    || { echo "ERROR: no tables found in schema '$count_schema' after restore." >&2; exit 1; }

echo "OK Snapshot ready on ${RESTORE_CONTEXT}: ${TARGET_DB} — ${tables} tables in schema '${count_schema}'."
echo "   Point the audit at the local DB and run:  uv run audit.py"
