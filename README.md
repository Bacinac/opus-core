# opus-core

What the three OPUS modules (Library, Downloads, Player) do the same way, kept
once. Each module checks it out as a git submodule at `backend/opus_core`, next
to `opus_auth`: the backend's build context is `backend/`, so that is the only
place a shared Python package can live and still reach the image.

The package `opus_core` never imports a module's own `opus`: the module hands
in what is its own — its database URL, its models, its settings — so the core
is tested here, alone, without any module's database.

- `settings.py` — the settings table: the spec, the kinds every module checks
  alike, the read held between writes, what the form is shown and the two ways
  of writing (a person's form, the module's own credentials)
- `db.py` — the engine and sessions behind one URL, and a route's session
- `migrations.py` — the body of every module's alembic `env.py`
- `responses.py` — a `FileResponse` that stops reading when the client hangs up
- `encoding.py` — JSON answers compressed (zstd, else gzip) for whoever accepts
  it; nothing but a whole JSON body is ever held back, so a film or a photograph
  streams byte for byte
- `door.py` — the door every request passes, as plain ASGI: the module's
  `refusal(request)` answers instead of the route, or lets it through.
  `@app.middleware("http")` re-sends every answer in chunks, and behind it no
  JSON answer was ever compressed
- `dida.py` — the door to DIDA, the house's automation: one session per install
  by whichever credential is configured, renewed once when refused; what a
  module asks the house stays in its own `house.py`
- `plugins.py` — what an installation adds from outside the repositories: the
  directories under `/plugins` whose `opus-plugin.toml` names an object per
  module, loaded or the start stops; their words at `GET /words`
- `revision.py` — `GET /version`: which build the module is, read from the
  `revision.json` beside the code, answered with the module's name
- `testing.py` — an in-memory settings table for tests with no database
- `tests/` — run by every module's check, next to its own

- `ops/check.sh` — the check every module runs before a commit and before a
  deploy; the module's own `check.sh` sources it and adds only what it alone has
- `ops/tools.txt` — the exact versions of the tools the check installs in the
  backend: pyflakes and pytest
- `ops/audit.txt` — the exact version of pip-audit, which reads the lock in a
  plain Python container of its own
- `ops/deploy.sh` — the deploy: ship HEAD with each submodule at its recorded
  commit, only once the check has vouched for it; the module's
  `deploy/prod.sh` names its services, ports and mounts and sources it
- `ops/revision.sh` — the stamp: `VERSION`'s MAJOR.MINOR and the commit count,
  the commit and its date, into `backend/revision.json`, which git never
  tracks. `ops/hooks/post-commit` (and its links for merge, checkout and
  rewrite) keep a checkout's stamp current; the deploy stamps what it ships
- `ops/install.sh` — what every installer does alike: prerequisites, `.env`
  and its secrets, the production shape, waiting for the services; each
  module's `install.sh` and the suite installer source it

Change it here, commit and push, then bump the pointer in all three modules and
run each module's `./check.sh`.
