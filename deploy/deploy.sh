#!/usr/bin/env bash
# Deploy the latest code. Run on the server:
#   sudo bash /opt/docsearch/deploy/deploy.sh [branch]    (default: main)
set -euo pipefail

BRANCH="${1:-main}"
REGION="us-east-2"
APP_DIR="/opt/docsearch"
COMPOSE=(docker compose -f docker-compose.prod.yml --env-file .env.prod)

cd "$APP_DIR"

echo "==> Fetching $BRANCH"
git fetch --quiet origin "$BRANCH"
git checkout --quiet -B "$BRANCH" "origin/$BRANCH"
git log -1 --oneline

param() {
  aws ssm get-parameter --region "$REGION" --name "$1" \
    --with-decryption --query Parameter.Value --output text
}

echo "==> Writing .env.prod from Parameter Store"
umask 077
cat > .env.prod <<EOF
DOMAIN=docsearch.mqazi98.com
POSTGRES_PASSWORD=$(param /docsearch/postgres_password)
OPENAI_API_KEY=$(param /docsearch/openai_api_key)
PUBLIC_DEMO_KEY=$(param /docsearch/public_demo_key 2>/dev/null || true)
EOF

if ! grep -q '^PUBLIC_DEMO_KEY=.' .env.prod; then
  echo "WARNING: /docsearch/public_demo_key is missing or empty; the demo page will show as offline."
fi

echo "==> Building and starting"
"${COMPOSE[@]}" up -d --build --remove-orphans
docker image prune -f > /dev/null

"${COMPOSE[@]}" ps
