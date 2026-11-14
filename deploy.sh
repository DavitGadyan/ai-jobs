#!/usr/bin/env bash
# Build with uv (no Docker) and deploy to AWS Lambda with values from .env.
#   ./deploy.sh                       default AWS profile
#   AWS_PROFILE=claude ./deploy.sh    a named profile
set -euo pipefail
cd "$(dirname "$0")"
set -a && source .env && set +a

export AWS_REGION="${AWS_REGION:-eu-central-1}" AWS_DEFAULT_REGION="${AWS_REGION:-eu-central-1}"
STACK="${STACK_NAME:-ai-jobs-mcp}"
SAM="uvx --from aws-sam-cli sam"
if [[ -z "${GOOGLE_CLIENT_ID:-}" ]]; then
  echo "GOOGLE_CLIENT_ID not set: deploying with a placeholder (sign-in fails until you add it)."
  GOOGLE_CLIENT_ID=pending.apps.googleusercontent.com GOOGLE_CLIENT_SECRET=pending
fi

build() {  # Lambda zip contents: Linux arm64 wheels + our modules + run.sh
  rm -rf .build && mkdir .build
  uv export --frozen --no-dev --no-hashes --no-emit-project -q -o .build/requirements.txt
  uv pip install -q -r .build/requirements.txt --target .build \
    --python-platform aarch64-manylinux2014 --python-version 3.12 --only-binary :all:
  cp $(ls ./*.py | grep -v test_) run.sh .build/
}

stack_url() {
  aws cloudformation describe-stacks --stack-name "$STACK" \
    --query "Stacks[0].Outputs[?OutputKey=='McpUrl'].OutputValue" --output text 2>/dev/null || true
}

deploy() {
  local overrides=(
    "SupabaseUrl=$SUPABASE_URL" "SupabaseSecretKey=$SUPABASE_SECRET_KEY"
    "SupabaseTable=${SUPABASE_TABLE:-ai_leads}"
    "GoogleClientId=$GOOGLE_CLIENT_ID" "GoogleClientSecret=$GOOGLE_CLIENT_SECRET"
    "JwtSigningKey=$JWT_SIGNING_KEY" "McpServerUrl=$1"
  )
  [[ -n "${CONTACT_EMAIL:-}" ]] && overrides+=("ContactEmail=$CONTACT_EMAIL")
  $SAM deploy --template-file template.yaml --stack-name "$STACK" --resolve-s3 \
    --capabilities CAPABILITY_IAM --no-confirm-changeset --no-fail-on-empty-changeset \
    --parameter-overrides "${overrides[@]}"
}

uv lock --check
build

url="$(stack_url)"
deploy "${url:-http://localhost:8000/mcp}"
if [[ "$(stack_url)" != "$url" ]]; then  # new Function URL: bake it into the server config
  url="$(stack_url)"
  deploy "$url"
fi

echo
echo "MCP URL:             $url"
echo "Google redirect URI: ${url%/mcp}/auth/callback"
