# The deploy every OPUS module runs. A module's deploy/prod.sh says what only it
# has, sources this file and calls opus_deploy "$@":
#
#   ./deploy/prod.sh [instance]                          ship HEAD (default: prod)
#   ./deploy/prod.sh --tarball <file>                    only build what would ship
#   ./deploy/prod.sh --prepare-volumes [--apply] [inst]  show, then fix, mount owners
#
# What a module sets before opus_deploy:
#   OPUS_MODULE          the repository: opus-library, opus-downloads, opus-player
#   OPUS_SERVICES        the compose services rebuilt and recreated on every deploy
#   OPUS_HEALTH_PORTS    the ports whose /api/ping answers before a deploy is done
#   OPUS_VOLUME_OWNER    --prepare-volumes: the container, then `dirs` or `all`,
#                        then the mount targets whose owner the app must be
#   OPUS_SHIP_APART      top-level paths HEAD tracks that stay behind
#   OPUS_SHIP_BUILT      paths git does not track that ship when they were built
#   opus_deploy_module   a function run once the services answer
#
# Plugins (opus_core/plugins.py) ship with the module as their committed HEAD,
# under plugins/<name>, where the target's compose finds them by default: the
# target's .env names no OPUS_PLUGINS of its own.
#
# The instance's .env and volumes/ live only on the target and are never
# touched. deploy/hosts.conf names each instance: <name> <ssh-host> <lxc-id>
# <path-on-proxmox-host> <path-in-lxc>.

. "$(dirname "${BASH_SOURCE[0]}")/check.sh"
. "$(dirname "${BASH_SOURCE[0]}")/revision.sh"

opus_instance() {
	read -r _ SSH_HOST LXC_ID HOST_PATH LXC_PATH < <(
		grep -E "^$1[[:space:]]" deploy/hosts.conf
	) || { echo "unknown instance: $1" >&2; exit 1; }
}

# A Docker-root process inside the LXC cannot chown an NFS-backed bind: the
# export maps it rather than it being the Proxmox host's root. Each mount source
# is translated through pct's host/LXC bind mapping and changed on the host,
# where ownership is authoritative; a volume on the LXC's own root filesystem
# has no host path and is changed inside the LXC.
opus_prepare_volumes() {
	local mode=$1 uid="${OPUS_APP_UID:-1000}" gid="${OPUS_APP_GID:-1000}"
	[[ "$uid" =~ ^[0-9]+$ && "$gid" =~ ^[0-9]+$ ]] || { echo "OPUS_APP_UID/GID must be numeric" >&2; exit 2; }
	opus_instance "$2"
	ssh "${SSH_HOST}" "sudo bash -s -- '${mode}' '${uid}' '${gid}' '${LXC_ID}' ${OPUS_VOLUME_OWNER[*]}" <<'REMOTE'
set -euo pipefail
mode=$1 uid=$2 gid=$3 lxc=$4 container=$5 scope=$6
shift 6
[[ "$scope" = all ]] && only=() || only=(-type d)
resolve_host_path() {
    local source=$1 host lxc_path candidate='' best=0 rest
    while IFS=$'\t' read -r host lxc_path; do
        case "$source" in
            "$lxc_path"|"$lxc_path"/*)
                if (( ${#lxc_path} > best )); then
                    rest=${source#"$lxc_path"}
                    candidate="${host}${rest}"
                    best=${#lxc_path}
                fi
                ;;
        esac
    done < <(pct config "$lxc" | sed -nE 's/^mp[0-9]+: ([^,]+),mp=([^,]+).*/\1\t\2/p')
    [[ -n "$candidate" ]] || { echo "no Proxmox bind maps $source" >&2; return 1; }
    printf '%s\n' "$candidate"
}
for target in "$@"; do
    mount=$(pct exec "$lxc" -- docker inspect -f "{{range .Mounts}}{{if eq .Destination \"$target\"}}{{printf \"%s|%s|%s\" .Type .Name .Source}}{{end}}{{end}}" "$container")
    IFS='|' read -r type name source <<<"$mount"
    [[ -n "$source" ]] || { echo "$container has no $target mount" >&2; exit 1; }
    if [[ "$type" = volume ]]; then
        source=$(pct exec "$lxc" -- docker volume inspect -f '{{index .Options "device"}}' "$name")
    fi
    if path=$(resolve_host_path "$source" 2>/dev/null); then
        printf '%s -> %s ' "$target" "$path"
        stat -c 'mode=%a owner=%u:%g' "$path"
        if [[ "$mode" = apply ]]; then
            find -P "$path" "${only[@]}" -exec chown --no-dereference "$uid:$gid" {} +
        fi
    else
        printf '%s -> lxc:%s ' "$target" "$source"
        pct exec "$lxc" -- stat -c 'mode=%a owner=%u:%g' "$source"
        if [[ "$mode" = apply ]]; then
            pct exec "$lxc" -- find -P "$source" "${only[@]}" -exec chown --no-dereference "$uid:$gid" {} +
        fi
    fi
done
REMOTE
}

# A deploy ships a pushed commit the check has vouched for, the rule a push
# keeps as well (opus_check_commit in check.sh).
opus_require_checked() {
	local sha
	sha=$(git rev-parse HEAD)
	git fetch -q origin
	git merge-base --is-ancestor "$sha" "origin/$(git rev-parse --abbrev-ref HEAD)" 2>/dev/null \
		|| { echo "HEAD ${sha:0:7} is not pushed" >&2; exit 1; }
	opus_check_commit "$sha"
	opus_require_plugins
}

# Each plugin clean, pushed, and written down by a check of this module run with
# it in place. One not yet vouched for is checked here, on the same condition a
# commit is: the working tree has to be what ships.
opus_require_plugins() {
	local plugin name unvouched=()
	while read -r plugin; do
		[[ -n "$plugin" ]] || continue
		name=$(basename "$plugin")
		[[ -z "$(git -C "$plugin" status --porcelain)" ]] \
			|| { echo "plugin ${name} holds uncommitted work, which no deploy ships" >&2; exit 1; }
		git -C "$plugin" fetch -q origin
		[[ -n "$(git -C "$plugin" branch -r --contains HEAD 2>/dev/null)" ]] \
			|| { echo "plugin ${name}: HEAD $(git -C "$plugin" rev-parse --short HEAD) is not pushed" >&2; exit 1; }
		grep -qxF "plugin ${name} $(git -C "$plugin" rev-parse 'HEAD^{tree}')" "$(opus_check_receipts)" 2>/dev/null \
			|| unvouched+=("$name")
	done < <(opus_plugins)
	(( ${#unvouched[@]} )) || return 0
	[[ -z "$(git status --porcelain)" ]] \
		|| { echo "plugin ${unvouched[*]} has not been checked with this module, and the working tree is not HEAD" >&2; exit 1; }
	echo "==> checking with plugin ${unvouched[*]}"
	./check.sh </dev/null
	while read -r plugin; do
		[[ -n "$plugin" ]] || continue
		grep -qxF "plugin $(basename "$plugin") $(git -C "$plugin" rev-parse 'HEAD^{tree}')" "$(opus_check_receipts)" \
			|| { echo "the check did not vouch for plugin $(basename "$plugin")" >&2; exit 1; }
	done < <(opus_plugins)
}

# What is committed and nothing else: HEAD, and every submodule at the commit
# HEAD records for it — never the working tree, where another session's
# unfinished work may be lying — plus what a module builds and git does not track,
# and the stamp that says which build it is.
opus_tarball() {
	local out=$1 work commit path apart=()
	work=$(mktemp -d)
	for path in "${OPUS_SHIP_APART[@]}"; do apart+=(":(exclude)$path"); done
	echo "==> stage HEAD $(git rev-parse --short HEAD)"
	git archive --format=tar -o "$work/head.tar" HEAD -- . "${apart[@]}"
	while read -r _ type commit path; do
		[[ "$type" = commit ]] || continue
		git -C "$path" cat-file -e "$commit^{commit}" 2>/dev/null \
			|| { echo "$path: $commit, which HEAD records, is not in the local checkout" >&2; rm -rf "$work"; exit 1; }
		echo "    $path @ ${commit:0:7}"
		git -C "$path" archive --format=tar --prefix="$path/" -o "$work/submodule.tar" "$commit"
		tar --concatenate -f "$work/head.tar" "$work/submodule.tar"
	done < <(git ls-tree -r HEAD)
	while read -r path; do
		[[ -n "$path" ]] || continue
		echo "    plugin $(basename "$path") @ $(git -C "$path" rev-parse --short HEAD)"
		git -C "$path" archive --format=tar --prefix="plugins/$(basename "$path")/" -o "$work/plugin.tar" HEAD
		tar --concatenate -f "$work/head.tar" "$work/plugin.tar"
	done < <(opus_plugins)
	for path in "${OPUS_SHIP_BUILT[@]}"; do
		if [[ -e "$path" ]]; then
			tar --append -f "$work/head.tar" "$path"
		else
			echo "    $path was not built and does not ship"
		fi
	done
	mkdir "$work/backend"
	opus_revision HEAD false > "$work/backend/revision.json" || { rm -rf "$work"; exit 1; }
	tar --append -f "$work/head.tar" -C "$work" backend/revision.json
	gzip -c "$work/head.tar" > "$out"
	rm -rf "$work"
}

opus_deploy() {
	case "${1:-}" in
		--tarball)
			[[ -n "${2:-}" ]] || { echo "usage: $0 --tarball <file>" >&2; exit 2; }
			opus_tarball "$2"
			return ;;
		--prepare-volumes)
			local mode=preview
			shift
			if [[ "${1:-}" = --apply ]]; then mode=apply; shift; fi
			opus_prepare_volumes "$mode" "${1:-prod}"
			return ;;
	esac

	# Two sessions deploying at once ran two compose projects over one stack:
	# each renamed the other's containers away and production was left with none.
	exec 9>"${TMPDIR:-/tmp}/${OPUS_MODULE}-deploy.lock"
	flock -w 1800 9 || { echo "another deploy of ${OPUS_MODULE} is still running" >&2; exit 1; }

	opus_require_checked

	local instance="${1:-prod}" shipped wiped="" name port
	opus_instance "$instance"
	shipped=$(mktemp)
	trap 'rm -f "'"$shipped"'"' EXIT
	opus_tarball "$shipped"

	for name in $(git ls-tree --name-only HEAD); do
		case "$name" in
			.env|volumes) echo "HEAD tracks ${name}, which lives only on the target" >&2; exit 1 ;;
			*) wiped+=" '${name}'" ;;
		esac
	done
	for name in "${OPUS_SHIP_BUILT[@]}"; do wiped+=" && sudo mkdir -p '${name}'"; done

	ssh "${SSH_HOST}" "sudo sh -c '! grep -q ^OPUS_PLUGINS= \"${HOST_PATH}/.env\"'" \
		|| { echo "${instance}'s .env names OPUS_PLUGINS; it builds the plugins shipped under plugins/" >&2; exit 1; }

	echo "==> sync → ${SSH_HOST}:${HOST_PATH}"
	# tar over ssh (no rsync on the dev LXC): wipe every top-level path HEAD
	# tracks, so a file deleted from the repository leaves the target as well,
	# then extract fresh. --touch: git archive stamps every file with the commit
	# time, and BuildKit keeps a context file whose path, size and mtime match the
	# last context it was sent by any compose project on the box — two modules
	# committed in the same second were built with each other's file
	ssh "${SSH_HOST}" "sudo mkdir -p '${HOST_PATH}' && cd '${HOST_PATH}' && sudo rm -rf ${wiped}"
	ssh "${SSH_HOST}" "sudo tar xzf - --touch -C '${HOST_PATH}'" < "$shipped"

	echo "==> compose up inside LXC ${LXC_ID}"
	# --force-recreate: the extract above replaced the bind-mounted code dirs, so
	# a container compose leaves running (unchanged image — e.g. a redeploy of the
	# same tree) keeps the DELETED directory pinned as an empty /app. postgres is
	# not forced: it is recreated only when its own definition changed, and its
	# data dir is never wiped
	ssh "${SSH_HOST}" "sudo pct exec ${LXC_ID} -- sh -c 'cd ${LXC_PATH} && docker compose up -d postgres && docker compose up -d --build --force-recreate ${OPUS_SERVICES[*]}'"

	echo "==> health"
	for port in "${OPUS_HEALTH_PORTS[@]}"; do
		ssh "${SSH_HOST}" "sudo pct exec ${LXC_ID} -- curl -fsS --retry 30 --retry-delay 2 --retry-connrefused --retry-all-errors http://localhost:${port}/api/ping"
		echo
	done
	if declare -F opus_deploy_module >/dev/null; then opus_deploy_module; fi
	echo "deploy ${instance}: done"
}
