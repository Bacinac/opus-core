# Which build a module is: MAJOR.MINOR from the module's VERSION, raised by hand
# for a milestone, then the commit count, so the number climbs with every commit
# and nobody keeps it. The stamp is backend/revision.json, which the backend
# serves at /api/version and git never tracks: a file that changes with every
# commit cannot be one of its files. The hooks stamp a checkout; the deploy
# stamps what it ships, from HEAD.

# The stamp of one commit, on stdout.
opus_revision() {
	local base
	base=$(git show "$1:VERSION" 2>/dev/null | tr -d ' \t\r\n')
	[ -n "$base" ] || { echo "$1 has no VERSION" >&2; return 1; }
	printf '{\n  "version": "%s.%s",\n  "sha": "%s",\n  "branch": "%s",\n  "committed_at": "%s",\n  "dirty": %s\n}\n' \
		"$base" "$(git rev-list --count "$1")" "$(git rev-parse --short=8 "$1")" \
		"$(git rev-parse --abbrev-ref HEAD)" "$(git log -1 --format=%cI "$1")" "$2"
}

# The working tree's stamp, written where the backend reads it.
opus_stamp() {
	local dirty
	cd "$(git rev-parse --show-toplevel)" || return 1
	if git diff --quiet --ignore-submodules HEAD; then dirty=false; else dirty=true; fi
	opus_revision HEAD "$dirty" > backend/revision.json.new && mv backend/revision.json.new backend/revision.json
}
