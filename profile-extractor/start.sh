#!/usr/bin/env bash
# start.sh — bootstrap and run the macprofile profile extractor on macOS.
#
#   ./start.sh           Interactive setup, then offers to run the pipeline.
#   ./start.sh --setup   Setup only (deps + API key + preflight); no pipeline.
#
# Safe to re-run: every step is idempotent.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"

SETUP_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --setup) SETUP_ONLY=1 ;;
    -h|--help)
      sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done

# ---------- pretty output ----------
if [[ -t 1 ]]; then
  BOLD=$'\033[1m'; DIM=$'\033[2m'; GREEN=$'\033[32m'
  YELLOW=$'\033[33m'; RED=$'\033[31m'; RESET=$'\033[0m'
else
  BOLD=""; DIM=""; GREEN=""; YELLOW=""; RED=""; RESET=""
fi
say()  { printf '%s==>%s %s\n' "$BOLD" "$RESET" "$*"; }
ok()   { printf '%s  ok%s  %s\n' "$GREEN" "$RESET" "$*"; }
warn() { printf '%swarn%s  %s\n' "$YELLOW" "$RESET" "$*"; }
die()  { printf '%s err%s  %s\n' "$RED" "$RESET" "$*" >&2; exit 1; }

confirm() {
  local prompt="$1" default="${2:-N}" reply
  local hint="[y/N]"; [[ "$default" == "Y" ]] && hint="[Y/n]"
  read -r -p "$prompt $hint " reply || reply=""
  reply="${reply:-$default}"
  [[ "$reply" =~ ^[Yy]$ ]]
}

# ---------- 0. sanity ----------
say "Checking platform"
if [[ "$(uname -s)" != "Darwin" ]]; then
  die "This extractor reads macOS-specific data sources. Detected: $(uname -s)."
fi
ok "macOS $(sw_vers -productVersion 2>/dev/null || echo '?')"

# ---------- 1. Homebrew ----------
say "Checking Homebrew"
if ! command -v brew >/dev/null 2>&1; then
  warn "Homebrew not found."
  if confirm "Install Homebrew now? (runs the official installer)" "Y"; then
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  else
    die "Homebrew is required. Install from https://brew.sh and re-run."
  fi
fi
# Make brew visible in this shell regardless of the user's profile.
if [[ -x /opt/homebrew/bin/brew ]]; then
  eval "$(/opt/homebrew/bin/brew shellenv)"
elif [[ -x /usr/local/bin/brew ]]; then
  eval "$(/usr/local/bin/brew shellenv)"
fi
command -v brew >/dev/null 2>&1 || die "brew still not on PATH after install."
ok "brew $(brew --version | head -n1)"

# ---------- 2. uv ----------
say "Checking uv"
if ! command -v uv >/dev/null 2>&1; then
  warn "uv not found. Installing via Homebrew."
  brew install uv
fi
ok "$(uv --version)"

# ---------- 3. workspace sync ----------
say "Syncing Python workspace (this installs all three subsystems)"
( cd "$WORKSPACE_ROOT" && uv sync )
ok "uv sync complete"

# ---------- 4. API key ----------
say "Configuring LLM API key"
if [[ -f "$ENV_FILE" ]] && grep -qE '^(ANTHROPIC|OPENAI)_API_KEY=' "$ENV_FILE"; then
  warn ".env already contains an API key at $ENV_FILE"
  if ! confirm "Overwrite it?" "N"; then
    # shellcheck disable=SC1090
    set -a; source "$ENV_FILE"; set +a
    ok "Keeping existing key."
    SKIP_KEY_PROMPT=1
  fi
fi

if [[ "${SKIP_KEY_PROMPT:-0}" -ne 1 ]]; then
  echo
  echo "  Which provider's key will you use?"
  echo "    1) Anthropic  (claude-sonnet-4-5, preferred)"
  echo "    2) OpenAI     (gpt-5)"
  PROVIDER=""
  while [[ -z "$PROVIDER" ]]; do
    read -r -p "  Choose [1/2]: " choice || choice=""
    case "$choice" in
      1|a|A|anthropic) PROVIDER="anthropic" ;;
      2|o|O|openai)    PROVIDER="openai" ;;
      *) echo "  please enter 1 or 2" ;;
    esac
  done

  if [[ "$PROVIDER" == "anthropic" ]]; then
    KEY_VAR="ANTHROPIC_API_KEY"
    KEY_HINT="starts with 'sk-ant-'"
  else
    KEY_VAR="OPENAI_API_KEY"
    KEY_HINT="starts with 'sk-'"
  fi

  API_KEY=""
  while [[ -z "$API_KEY" ]]; do
    # -s so the key isn't echoed to the terminal.
    read -r -s -p "  Paste your $KEY_VAR ($KEY_HINT): " API_KEY || true
    echo
    [[ -n "$API_KEY" ]] || echo "  key cannot be empty"
  done

  umask 077
  {
    echo "# Written by profile-extractor/start.sh"
    echo "# Source before running macprofile manually:  set -a; source .env; set +a"
    echo "$KEY_VAR=$API_KEY"
  } > "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  export "$KEY_VAR=$API_KEY"
  unset API_KEY
  ok "Wrote $ENV_FILE (chmod 600, gitignored)."
fi

# ---------- 5. preflight ----------
say "Running Full Disk Access preflight"
PREFLIGHT_OK=1
( cd "$SCRIPT_DIR" && uv run macprofile preflight ) || PREFLIGHT_OK=0
if [[ $PREFLIGHT_OK -eq 0 ]]; then
  warn "Preflight reported denied paths. Grant Full Disk Access to the venv's"
  warn "Python (path printed above) in System Settings -> Privacy & Security"
  warn "-> Full Disk Access, then re-run ./start.sh."
  exit 1
fi

# ---------- 6. pipeline ----------
if [[ $SETUP_ONLY -eq 1 ]]; then
  say "Setup complete (--setup specified, skipping pipeline)."
  cat <<EOF

Next steps, from $SCRIPT_DIR:

  set -a; source .env; set +a            # load the API key
  uv run macprofile extract --all        # pull events into the warehouse
  uv run macprofile analyze              # SQL aggregates -> output/analyses.json
  uv run macprofile profile              # LLM pass    -> output/profile.{json,md}
  uv run macprofile serve                # local API at http://127.0.0.1:8766

EOF
  exit 0
fi

echo
if confirm "Run the full pipeline now (extract + analyze + profile)?" "Y"; then
  say "extract --all"
  ( cd "$SCRIPT_DIR" && uv run macprofile extract --all )
  say "analyze"
  ( cd "$SCRIPT_DIR" && uv run macprofile analyze )
  say "profile"
  ( cd "$SCRIPT_DIR" && uv run macprofile profile )
  ok "Done. See $SCRIPT_DIR/output/profile.json and profile.md."
  echo
  echo "${DIM}Tip: 'uv run macprofile serve' exposes a local query API.${RESET}"
else
  say "Skipping pipeline. Run it later with:"
  cat <<EOF

  cd $SCRIPT_DIR
  set -a; source .env; set +a
  uv run macprofile extract --all
  uv run macprofile analyze
  uv run macprofile profile

EOF
fi
