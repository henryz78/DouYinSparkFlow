# Project notes for Claude

## Fork and upstream-sync policy

This repository is a personal fork (`origin` = henryz78/DouYinSparkFlow) of the
official project (`upstream` = 2061360308/DouYinSparkFlow). It carries many
custom changes beyond upstream, and it is meant to keep tracking upstream
releases closely.

Whenever the user says upstream has released a new version, Claude does the merge:

1. `git fetch --all --tags`, then compare the release against our last merge base.
   Read the release notes and the actual diff (`git diff <base> <tag>`), not just the commit titles.
2. **Before merging, check whether upstream's changes overlap with anything we
   previously modified or fixed** (same files, same behaviour, or a feature we
   built ourselves that upstream now also provides). A trial merge
   (`git merge --no-commit --no-ff <tag>`) is a quick way to find the conflicts.
3. For every overlap, evaluate which side is better and decide: keep ours,
   take upstream's, or combine both. Prefer upstream's version when it is
   good enough, because fewer custom lines means fewer conflicts on the next
   release. Keep ours only when it does something upstream does not.
4. Tell the user about each conflict point together with your recommendation
   (what overlaps, which side you suggest keeping and why, any behaviour change
   they will notice, and any risk to the running production container) before
   or alongside doing the merge.
5. Run the full test suite after the merge. Do not push or deploy to the VPS
   without the user's explicit go-ahead.

## What we changed beyond upstream (check these first when merging)

- **Sticker delivery**: `DELIVERY_MODE` / `NATIVE_STICKER_NAME`, `send_native_sticker` in
  `core/douyin_im.py`, plus two fixes there (avatar loading no longer gates "ready";
  `jsclick` clicks the element that was already scrolled into view).
- **Random start window**: `CRON_RANDOM_WINDOW_SECONDS`, implemented in `docker/run-task.sh`.
- **Run log**: one JSON line per account run in `logs/runs.jsonl` (`core/run_log.py`);
  scheduled runs skip when today's last run per account already succeeded.
- **Personal web console**: `web/` (stdlib server, single password, self-signed HTTPS on
  port 8443, manual run, config editing, live logs). Started by `docker/entrypoint-cron.sh`
  only when `DASH_PASSWORD_HASH` is set. Config edits apply live via `docker/apply-config.sh`.
- **`core/tasks.py`**: merged with upstream's exit code and per-account isolation; we keep
  the run record and per-friend results.
- **Desktop app** (`app/`): our extra settings live in `app/config/models.py`;
  `ConfigService._dict_to_config` keeps fields the GUI has no inputs for.
- **Notifications** use upstream's `NOTIFY`. Our own Telegram notifier was removed on purpose
  to cut merge conflicts; do not re-add it.

## Production (VPS, Docker)

- Container `douyin-spark-flow`, project dir `/root/mcp-workspace/DouYinSparkFlow`, config in
  `config/.env` (bind-mounted to `/app/.env`), logs in `logs/`. The image is built on the
  server through an untracked `docker-compose.override.yml` (`build: .`, image `douyin-spark-flow:local`).
- Deploy = back up `config/.env`, `git pull`, `docker compose build douyin-spark-flow`
  (about 10 minutes), `docker compose up -d douyin-spark-flow`. Do not touch other
  services on that server (nginx, other projects).
- **Never deploy to production without the user's explicit permission.** Access details and
  passwords are not in this repo; ask the user, and never write them into files or memory.
- A real send test is `docker exec -e MANUAL_RUN=1 douyin-spark-flow bash /app/docker/run-task.sh`.
  It messages real friends and counts as that day's run, so the scheduled run will skip.
- Dashboard logins live in process memory, so a container restart logs everyone out. The user
  accepted this.

## Conventions

- Work directly on `main`. Do not commit half-finished changes or leftover debug code.
- Run tests with `python -m pytest` before committing.
- `*.sh` files must stay LF (see `.gitattributes`); other files may be CRLF in the working tree.
