# The check every OPUS module runs on itself. A module's own check.sh sources
# this file, says what only it adds, and calls opus_check.
#
# Each step runs against the source as it is on disk, never against what an
# image baked in when it was built: the frontend's src is mounted, and the words
# check spans both halves of the repository — half of what the screens say is a
# vocabulary the backend owns — so it runs over the repository itself,
# read-only, in the frontend's own image. The frontend's logic is tested
# (vitest), every button has to carry a name a screen reader can say (the kit's
# names.mjs), every size of text is a step of the kit's scale (type.mjs), every
# help article is whole in both languages and every page it names for this
# module is one of its routes (articles.mjs over opus-ui's help — the other
# two modules' pages are held to their routes by their own checks), and
# the frontend is also built the way
# production builds it, because the type checker never bundles and a module
# that only fails to bundle would otherwise be found by the deploy. A backend
# symbol deleted while something still calls it imports cleanly and fails only
# when called, so the backend is read by pyflakes as well, and its tests, with
# the door protocol's and this core's, run with every warning an error. Every locked dependency,
# Python and npm alike, is looked up in the public advisories: a known
# vulnerability turns the check red instead of waiting for someone to read a
# feed. The Python lock is read as data, so it is audited in a plain Python
# rather than in the backend, whose /tmp may not execute what pip installs.
#
# The check vouches for a tree, not for a moment: the tree's id is taken before
# and after, and written down only when nothing moved meanwhile. Uncommitted
# work in a submodule is read here but shipped by no deploy, so a tree holding
# some is not vouched for. What is written down is what a push and a deploy ask
# for (opus_check_commit); nothing else checks a commit, there is no CI.
#
# Plugins (opus_core/plugins.py) are checked with the module they are built
# into: the directories under OPUS_PLUGINS, which .env names and compose builds
# and mounts at /plugins. Their tests for this module run beside the module's,
# their code is read by pyflakes and their lock for this module audited. A
# plugin holding uncommitted work fails the check the way a submodule does, and
# a clean one is written down beside the tree as `plugin <name> <tree>`, which
# is what a deploy asks for before it ships it.
#
# What a module may add, defined before opus_check: opus_check_module, a
# function run after the backend's tests.

# The trees the check found green, the newest last. A list and not the last one
# alone: another session checking its own work must not take the vouching back
# from a commit still waiting to be pushed or deployed.
opus_check_receipts() {
	printf '%s/checked\n' "$(git rev-parse --git-dir)"
}

opus_check_vouched() {
	grep -qxF "$1" "$(opus_check_receipts)" 2>/dev/null
}

# A commit leaves this machine, pushed or deployed, only as one the check has
# vouched for, and only with every submodule commit it records already on that
# submodule's remote. A tree not yet vouched for is checked here and now, which
# is only honest while the working tree IS that commit: with another session's
# uncommitted work in it, the check would read that work in the commit's place,
# which is how a commit taking part of the tree once shipped unchecked.
opus_check_commit() {
	local sha short tree dirty
	sha=$(git rev-parse "$1^{commit}")
	short=$(git rev-parse --short "$sha")
	git ls-tree -r "$sha" | awk '$2 == "commit" { print $3, $4 }' | while read -r commit path; do
		git -C "$path" fetch -q origin
		[ -n "$(git -C "$path" branch -r --contains "$commit" 2>/dev/null)" ] \
			|| { printf '%s: %s records %.7s, which is not pushed\n' "$path" "$short" "$commit" >&2; exit 1; }
	done || exit 1
	tree=$(git rev-parse "$sha^{tree}")
	if ! opus_check_vouched "$tree"; then
		dirty=$(git status --porcelain)
		[ "$(git rev-parse HEAD)" = "$sha" ] && [ -z "$dirty" ] || {
			printf '%s has not been checked, and the working tree is not %s, so it cannot be here:\n%s\n' \
				"$short" "$short" "${dirty:-HEAD is $(git rev-parse --short HEAD)}" >&2
			exit 1
		}
		echo "==> checking $short"
		./check.sh </dev/null
		opus_check_vouched "$tree" || { echo "the check did not vouch for $short" >&2; exit 1; }
	fi
	echo "checked $short"
}

opus_check_tree() {
	idx=$(mktemp)
	GIT_INDEX_FILE="$idx" git read-tree HEAD
	GIT_INDEX_FILE="$idx" git add -A
	GIT_INDEX_FILE="$idx" git write-tree
	rm -f "$idx"
}

opus_check_loose() {
	git submodule foreach --quiet 'git status --porcelain | sed "s#^#$sm_path: #"'
	opus_plugins | while read -r plugin; do
		git -C "$plugin" status --porcelain 2>/dev/null | sed "s#^#plugin $(basename "$plugin"): #"
	done
}
opus_plugins_dir() {
	dir=$(sed -n 's/^OPUS_PLUGINS=//p' .env 2>/dev/null | tail -n 1)
	printf '%s\n' "${dir:-./plugins}"
}
opus_plugins() {
	for manifest in "$(opus_plugins_dir)"/*/opus-plugin.toml; do
		[ -f "$manifest" ] && dirname "$manifest"
	done
	return 0
}
# `plugin <name> <tree>` for each plugin, the line the receipts keep
opus_plugin_trees() {
	opus_plugins | while read -r plugin; do
		tree=$(git -C "$plugin" rev-parse 'HEAD^{tree}' 2>/dev/null) || {
			echo "plugin $(basename "$plugin") is not a git checkout, so nothing of it can be vouched for" >&2
			exit 1
		}
		printf 'plugin %s %s\n' "$(basename "$plugin")" "$tree"
	done
}

# A colour is a token of the palette: a hex, rgb() or hsl() written anywhere
# but the palette is a colour no theme can reach. What is computed from data is
# not a choice.
opus_check_colour() {
	off=$(grep -rnE --include='*.svelte' --include='*.css' --include='*.ts' \
		--exclude='tokens.css' --exclude='colours.ts' --exclude='*.test.ts' \
		'#[0-9a-fA-F]{3,8}\b|(rgb|hsl)a?\(' frontend/src | grep -v '\${' || true)
	[ -z "$off" ] || { printf '%s\n' "$off" >&2; echo "a raw colour; use a token from the palette, opus-ui's tokens.css" >&2; exit 1; }
	echo 'colour: every colour a token'
}

opus_check() {
	# a clone that checks itself gates its pushes on the check too; the hook is
	# found through the clone's own config, which no commit carries
	git config core.hooksPath backend/opus_core/ops/hooks
	# the module's name is its compose project's, which names its plugin tests
	# and locks
	OPUS_MODULE=$(sed -n 's/^name: //p' docker-compose.yml)
	# the help's apps, this one with the source the check can read
	help_apps=$(for app in library downloads player; do
		if [ "opus-$app" = "$OPUS_MODULE" ]; then printf ' %s=src' "$app"; else printf ' %s' "$app"; fi
	done)

	plugins_before=$(opus_plugin_trees)
	tree_before=$(opus_check_tree)
	loose_before=$(opus_check_loose)

	opus_check_colour

	# The resident Vite server lives in 512 MiB; the compiler over the whole
	# tree does not, and a one-off check is not the thing that limit protects.
	OPUS_FRONTEND_MEMORY_LIMIT=2g docker compose run --rm --no-deps -q \
		-e NODE_OPTIONS=--max-old-space-size=1536 frontend sh -lc "
		set -e
		npx svelte-kit sync
		npm run check
		node --test src/lib/kit/*.test.mjs src/lib/opus/*.test.mjs
		node src/lib/kit/names.mjs src
		node src/lib/kit/type.mjs src
		node src/lib/kit/articles.mjs src/lib/opus/help$help_apps
		npx vitest run
		NODE_ENV=production npm run build >/tmp/build.log 2>&1 || { cat /tmp/build.log; exit 1; }
		echo 'production build: clean'"
	docker compose run --rm --no-deps -q -v "$PWD:/repo:ro" -w /repo frontend sh -c '
		set -e
		node /repo/frontend/src/lib/i18n/words.mjs
		cd /repo/frontend
		npm audit'
	# A module's own tests are the module as it is published, so its conftest
	# points OPUS_PLUGIN_ROOT at nothing. A plugin's tests run on their own,
	# after the module's, with the plugins in place and the module's conftest
	# loaded as a pytest plugin for its fixtures: collected in one run, that
	# conftest would be two modules and set its database up twice. Outside the
	# module's tree the configuration and the root are named rather than
	# searched for, and the plugin is importable before anything loads it.
	docker compose exec -T -e OPUS_MODULE="$OPUS_MODULE" backend sh -c '
		set -e
		pip install -q --root-user-action=ignore --no-warn-script-location -r opus_core/ops/tools.txt
		plugins=$(find /plugins -mindepth 2 -maxdepth 2 -name opus-plugin.toml -exec dirname {} + 2>/dev/null || true)
		find opus tests opus_auth opus_core $plugins -name "*.py" | xargs python -m pyflakes
		echo "pyflakes: clean"
		python -m pytest -q -p no:cacheprovider -W error tests opus_auth/tests opus_core/tests
		for plugin in $plugins; do
			[ -d "$plugin/tests/$OPUS_MODULE" ] || continue
			echo "plugin $(basename "$plugin"):"
			OPUS_PLUGIN_ROOT=/plugins PYTHONPATH="$plugin" python -m pytest -q -p no:cacheprovider -p tests.conftest -W error \
				-c pyproject.toml --rootdir . "$plugin/tests/$OPUS_MODULE"
		done'
	docker run --rm -v "$PWD/backend:/backend:ro" -v "$(cd "$(opus_plugins_dir)" && pwd):/plugins:ro" \
		-w /backend -v opus-check-pip:/root/.cache/pip -e OPUS_MODULE="$OPUS_MODULE" \
		python:3.14-slim sh -c '
		set -e
		pip install -q --root-user-action=ignore --disable-pip-version-check -r opus_core/ops/audit.txt
		for lock in requirements.lock /plugins/*/requirements/$OPUS_MODULE.lock; do
			[ -f "$lock" ] || continue
			pip-audit --disable-pip --progress-spinner off --vulnerability-service osv -r "$lock"
		done'

	if command -v opus_check_module >/dev/null 2>&1; then
		opus_check_module
	fi

	tree_after=$(opus_check_tree)
	loose_after=$(opus_check_loose)
	plugins_after=$(opus_plugin_trees)
	[ "$tree_before$loose_before$plugins_before" = "$tree_after$loose_after$plugins_after" ] \
		|| { echo "the tree changed while it was being checked; run the check again" >&2; exit 1; }
	[ -z "$loose_after" ] || {
		echo "uncommitted work in a submodule or a plugin, which no deploy ships; commit it there (and bump a submodule's pointer):" >&2
		echo "$loose_after" >&2
		exit 1
	}
	receipts=$(opus_check_receipts)
	{
		tail -n 99 "$receipts" 2>/dev/null || true
		printf '%s\n' "$tree_after"
		[ -z "$plugins_after" ] || printf '%s\n' "$plugins_after"
	} > "$receipts.$$"
	mv "$receipts.$$" "$receipts"
}
