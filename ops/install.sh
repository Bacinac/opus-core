# What every OPUS installer does the same way. A module's install.sh changes
# into its own root, sources this file and then says only what it alone has;
# the suite installer sources it for the same helpers.
#
# ENV_FILE is the environment file compose reads: OPUS_ENV_FILE, else .env.

ENV_FILE=${OPUS_ENV_FILE:-.env}

# the installer's opening comment is its --help
opus_help() {
	awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0"
}

opus_require() {
	local tool
	for tool in "$@"; do
		if [[ "$tool" = docker ]]; then
			command -v docker >/dev/null 2>&1 || { echo "Docker is required: https://docs.docker.com/engine/install/" >&2; exit 1; }
			docker compose version >/dev/null 2>&1 || { echo "Docker Compose v2 is required" >&2; exit 1; }
		else
			command -v "$tool" >/dev/null 2>&1 || { echo "$tool is required by the installer" >&2; exit 1; }
		fi
	done
}

compose() { docker compose --env-file "$ENV_FILE" "$@"; }

# BuildKit keeps a context file whose path, size and mtime match the last
# context it was sent by any compose project on the box, so two modules
# installed side by side could build with each other's file. A fresh mtime is
# new to it; the layer cache keys on content and still holds.
opus_build() {
	local context
	compose --profile '*' config | sed -n 's/^ *context: //p' | while read -r context; do
		find "$context" -type f -exec touch {} +
	done
	compose build "$@"
}

generate() {
	openssl rand -hex "${1:-24}" 2>/dev/null ||
		python3 -c 'import secrets,sys; print(secrets.token_hex(int(sys.argv[1])))' "${1:-24}"
}

# env_read KEY [FILE]
env_read() {
	python3 - "${2:-$ENV_FILE}" "$1" <<'PY'
import pathlib, sys
path, key = pathlib.Path(sys.argv[1]), sys.argv[2]
if path.exists():
    for line in reversed(path.read_text().splitlines()):
        if line.startswith(key + "="):
            print(line.split("=", 1)[1].strip().strip('"'))
            break
PY
}

env_set() {
	python3 - "$ENV_FILE" "$1" "$2" <<'PY'
import pathlib, sys
path, key, value = pathlib.Path(sys.argv[1]), sys.argv[2], sys.argv[3]
lines = path.read_text().splitlines() if path.exists() else []
for i, line in enumerate(lines):
    if line.startswith(key + "="):
        lines[i] = f"{key}={value}"
        break
else:
    lines.append(f"{key}={value}")
path.write_text("\n".join(lines) + "\n")
PY
}

# readable by its owner alone: it is where every secret of the module is kept
opus_env_file() {
	[[ -f "$ENV_FILE" ]] && return
	cp .env.example "$ENV_FILE"
	chmod 600 "$ENV_FILE"
	echo "created $ENV_FILE"
}

# opus_generate KEY:BYTES... — made once, kept on every rerun
opus_generate() {
	local spec key
	for spec in "$@"; do
		key=${spec%%:*}
		[[ -z "$(env_read "$key")" ]] || continue
		env_set "$key" "$(generate "${spec##*:}")"
		echo "generated $key"
	done
}

# opus_required HINT KEY... — what another module issued: from the environment,
# else what .env already holds
opus_required() {
	local hint=$1 key value
	shift
	for key in "$@"; do
		value=${!key:-$(env_read "$key")}
		[[ -n "$value" ]] || { echo "$key is required ($hint)" >&2; exit 1; }
		env_set "$key" "$value"
	done
}

# written only when the environment carries it
opus_pass_through() {
	local key
	for key in "$@"; do
		[[ -z "${!key:-}" ]] || env_set "$key" "${!key}"
	done
}

# the services run as whoever installed them, with the built UI and no reloader
opus_production() {
	env_set OPUS_APP_UID "$(id -u)"
	env_set OPUS_APP_GID "$(id -g)"
	env_set OPUS_UI_TARGET prod
	env_set OPUS_DEV_RELOAD 0
}

opus_validate() {
	compose config -q
	echo "$1 configuration is valid"
}

opus_host_address() {
	local address
	address=$(hostname -I 2>/dev/null | awk '{print $1}')
	printf '%s\n' "${address:-127.0.0.1}"
}

# opus_wait URL TRIES WHAT — two seconds apart
opus_wait() {
	local url=$1 tries=$2 what=$3
	for _ in $(seq 1 "$tries"); do
		curl -fsS "$url" >/dev/null 2>&1 && return
		sleep 2
	done
	compose ps
	echo "$what did not become ready" >&2
	exit 1
}
