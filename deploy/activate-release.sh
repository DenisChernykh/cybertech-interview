#!/usr/bin/env bash
set -Eeuo pipefail
export PATH="/usr/local/bin:/usr/bin:/bin"

base=/srv/cybertech
release_id=${1:?release identifier required}
case "$release_id" in *[!a-zA-Z0-9-]*|'') echo 'Invalid release identifier' >&2; exit 1;; esac
incoming="$base/incoming/$release_id"
release="$base/releases/$release_id"
test -f "$incoming/backend/pyproject.toml"
test -f "$incoming/frontend/dist/index.html"
test -r "$base/shared/demo.env"
test ! -e "$release"

exec 9>"$base/deploy.lock"
flock -n 9 || { echo 'Another deployment is in progress' >&2; exit 1; }
mkdir -p "$base/releases"
mv "$incoming" "$release"
rm -f "$base/incoming/$release_id.tar.gz"

# Runtime settings and credentials live outside Git and survive releases.
set -a
# shellcheck disable=SC1091
source "$base/shared/demo.env"
set +a

cd "$release/backend"
uv sync --locked --no-dev --python 3.13
uv run --no-sync alembic upgrade head
uv run --no-sync python -m app.seed

previous=$(readlink -f "$base/current" || true)
rollback() {
  if [ -n "$previous" ] && [ -d "$previous" ]; then
    ln -s "$previous" "$base/current.rollback"
    mv -Tf "$base/current.rollback" "$base/current"
    sudo -n /usr/bin/systemctl restart cybertech-api.service cybertech-worker.service || true
  fi
}
ln -s "$release" "$base/current.next"
mv -Tf "$base/current.next" "$base/current"

if ! sudo -n /usr/bin/systemctl restart cybertech-api.service cybertech-worker.service; then
  rollback
  echo 'Service restart failed; database migrations are not automatically rolled back.' >&2
  exit 1
fi

for _ in {1..15}; do
  if curl -fsS http://127.0.0.1:8000/api/health >/dev/null && \
     systemctl is-active --quiet cybertech-worker.service; then
    echo "Release $release_id is healthy"
    exit 0
  fi
  sleep 2
done
rollback
echo 'Release did not pass the health check; inspect both services.' >&2
echo 'Database migrations are not automatically rolled back.' >&2
exit 1
