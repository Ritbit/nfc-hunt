#!/usr/bin/env bash
# Deploy the NFC Treasure Hunt to a remote host over SSH.
#
# Usage:
#   ./deploy/deploy.sh                      # deploys to the default host
#   ./deploy/deploy.sh root@10.255.253.20   # explicit target
#
# Assumes first-time setup is already done on the target (see deploy/README.md):
# python venv at /var/www/nfc_hunt/venv, configs installed, nfc_hunt.service
# and nginx enabled. This script syncs the code and restarts the app.

set -euo pipefail

TARGET="${1:-root@10.255.253.20}"
APP_DIR="/var/www/nfc_hunt"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

echo "==> Deploying to ${TARGET}"

rsync -az --delete \
    --exclude '.git' \
    --exclude 'venv' \
    --exclude 'treasure_hunt.db*' \
    --exclude 'clues.yaml.bak' \
    --exclude '__pycache__' \
    --exclude '*.pyc' \
    --exclude '*.tgz' \
    --exclude 'tests' \
    --exclude '.markdownlint.json' \
    "${REPO_ROOT}/" "${TARGET}:${APP_DIR}/"

echo "==> Installing any new dependencies"
ssh "$TARGET" "${APP_DIR}/venv/bin/pip -q install -r ${APP_DIR}/requirements.txt"

echo "==> Refreshing deploy configs and restarting"
ssh "$TARGET" '
    cp '"$APP_DIR"'/deploy/nfc_hunt.ini /etc/uwsgi.d/nfc_hunt.ini &&
    cp '"$APP_DIR"'/deploy/nfc_hunt.conf /etc/nginx/conf.d/nfc_hunt.conf &&
    cp '"$APP_DIR"'/deploy/nfc_hunt.service /etc/systemd/system/nfc_hunt.service &&
    systemctl daemon-reload &&
    systemctl restart nfc_hunt nginx &&
    sleep 2
'

echo "==> Health check"
STATUS=$(ssh "$TARGET" "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1/")
if [ "$STATUS" = "200" ]; then
    echo "==> Done. App responding at http://${TARGET#*@}/ (HTTP $STATUS)"
else
    echo "!! Health check returned HTTP $STATUS — check: ssh $TARGET journalctl -u nfc_hunt -n 30" >&2
    exit 1
fi
