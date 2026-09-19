# Progress

## Current objective

- Official upstream v3.2.1 remains the base. Active development is now on `integrate-v3.2.1`, created from official `3c54009`.
- Our previous custom/stable implementation is preserved on `custom-pre-v3.2.1` and pushed to the fork.
- Current integration stage only changes conversation selection reliability. Input/send/at-most-once integration has not started yet.

## Repository / Git state

- Project root: `/root/mcp-workspace/DouYinSparkFlow`
- Branch: `integrate-v3.2.1`
- HEAD: `3c54009` — official v3.2.1 (`Bump version from 3.2.0 to 3.2.1`)
- Fork remote: `https://github.com/henryz78/DouYinSparkFlow.git`
- Official upstream: `https://github.com/2061360308/DouYinSparkFlow.git`
- `fork/main` and `origin/main` are both verified at `3c54009`.
- Our pre-v3.2.1 custom branch is `custom-pre-v3.2.1` at `9363a7e` and is pushed to `fork/custom-pre-v3.2.1`.
- `9363a7e` includes all prior custom commits plus the uncommitted native-sticker WIP that was found in the working tree and preserved as `WIP native sticker delivery`.
- `integrate-v3.2.1` now has checkpoint commit `0f8524c` (`WIP harden conversation selection`) on top of official `3c54009`; it contains only the click/selection reliability experiment and its tests.
- `PROGRESS.md` is intentionally being tracked for cross-agent handoff on our custom/integration branches. Other `.mcp/` diagnostic probe scripts remain locally ignored.

Relevant custom history now preserved on `custom-pre-v3.2.1`:

- `9363a7e` — WIP native sticker delivery
- `c7655c1` — Polish input focus and draft clearing
- `6f5258b` — Add natural friend-list scrolling
- `ea076b5` — Add low-risk humanized input pacing
- `61bddaa` — Fix stale dashboard schedule and one-off cron leak
- `942ba40` — Minimize upstream diff and enforce at-most-once delivery
- `6629db6` — Fix reliable daily delivery and add monitoring dashboard
- official baseline: `f0ff3d2` / upstream v3.2.0-era merge

## Formal runtime

- Formal task + dashboard image: `sha256:7e1f5a46ffe82fea62b81b46380cd5428d64047add5ca4f045e2131c5ceb9942`
- Important: the formal running containers have NOT been switched to official v3.2.1. They are still the previously deployed custom/stable image.
- `douyin-spark-flow`: running normally on the previous custom image.
- `douyin-spark-dashboard`: healthy on port 8787.
- No Compose one-off test containers remain.
- Cron currently logs as `* 8-9 * * *` with random window `08:00:00 +7200s`, timezone `Asia/Shanghai`.
- Current production targets are exactly Rick, Peter, Ken.
- 今心 is intentionally excluded. Do not add it back without explicit user instruction.

Current production-state hashes after all controlled tests/deploys:

- `logs/send_state.json`: `95ab3d323f8ad1f7ab33f589c5fa85b9a11131a54d32b94f8be5b702748113e1`
- `logs/random-run-schedule.json`: `fe33827833f2861354ad7c92bf05f27161ca2aad81cdf205c7b10251ba8d29c7`

These stayed unchanged during isolated stability testing.

## Reliability invariants that must not be weakened

- Strict per-recipient/day at-most-once delivery using shared state.
- State values include `attempted` and `confirmed`.
- Missing state is treated as new; malformed state fails closed.
- State retention is 30 days.
- Before sending, active conversation must exactly match the intended recipient.
- `attempted` is persisted immediately before the single send dispatch.
- If dispatch result is uncertain, stay `attempted`; never auto-resend.
- Existing `attempted` entries are verification-only on later runs.
- Fresh-page verification checks server-side persistence and exact non-whitespace content.
- `confirmed` is written only after fresh-page verification succeeds.
- Unresolved delivery raises an error so scheduler completion is not falsely marked.
- `flock /app/logs/task.lock` prevents simultaneous same-state runs.
- One-off Docker commands execute directly through `docker/entrypoint.sh` and do not become accidental cron containers.
- Recipient activation remains deterministic because this is safety-critical: current Douyin behavior is switched through `mousedown`, then the right-side conversation title is rechecked.
- Send dispatch remains deterministic and single-shot. Do not humanize it at the cost of duplicate-send risk.

## Humanization work now in production

### Input pacing (`ea076b5`)

- Normal visible text is inserted one character at a time using `page.keyboard.insert_text(char)`.
- This was chosen because real Douyin Slate testing showed CloakBrowser/raw typing could drop ASCII and spaces.
- Random delays:
  - punctuation: about 0.08–0.22s
  - whitespace: about 0.03–0.09s
  - normal characters: about 0.035–0.13s
- Emoji shortcodes such as `[盖瑞]` remain atomic to avoid Douyin parsing them midway.
- Newlines continue to use `Shift+Enter`.
- Small randomized waits remain around page readiness, friend switching, post-message input, and between recipients.

### Natural scrolling (`6f5258b`)

- Replaced the old single `scrollTop += 800` jump.
- Each search gesture now advances roughly 650–850px total, split into 6–9 randomized steps.
- Step sizes follow a mild accelerate/decelerate shape with small random pauses.
- Existing bottom detection remains intact.
- Real Douyin no-send testing showed segmented movement to the true list bottom and normal termination.
- A stricter integration probe ran the real `scroll_and_select_user()` against a guaranteed-nonexistent sentinel and reached exactly `top=1350 / max=1350`, then stopped normally.

### Final editor polish (`c7655c1`)

- After focusing the editor, wait 0.12–0.30s before typing the first character.
- If an old draft exists:
  - focus
  - short randomized pause
  - `Ctrl+A`
  - short pause
  - second `Ctrl+A`
  - short pause
  - `Backspace`
  - short settle pause
  - verify the editor is actually empty before continuing
- Real Douyin Slate testing showed one `Ctrl+A` could select only a local block; two consecutive `Ctrl+A` presses were needed to reliably select the whole draft.
- Real no-send probe successfully cleared `OLD DRAFT 123`, entered `拟人化收尾测试 ABC (1) 空格 OK` with Chinese/ASCII/spaces/parentheses intact, and cleaned the editor afterward.

## Verification completed

- Current unit/integration suite: 20/20 passing.
- `py_compile`: passed.
- `git diff --check`: passed.
- Docker image build: passed.
- Natural scrolling real-page tests: passed.
- Friend switching for Rick / Peter / Ken: passed with active-conversation verification.
- Final real input probe: passed, no send performed.
- Formal deployment to `c7655c1`: completed and dashboard healthy.
- Production send-state and random-schedule hashes were unchanged across deployment and isolated stability tests.

### Real 5-round stability run

- Final controlled test ran five complete real rounds.
- Each round sent exactly one real message to Rick, Peter, and Ken.
- Final controlled result: Rick 5, Peter 5, Ken 5 — 15 controlled sends total.
- Every one of those 15 sends was confirmed from a fresh page.
- No wrong-recipient failure, missing persistence confirmation, or at-most-once violation occurred in the controlled run.
- Each round used a separate temporary `SEND_STATE_FILE`, so formal daily state was not altered.
- Important history note: before the final controlled five-round run, earlier interrupted/exploratory stability attempts in the same development session had already sent additional test-labelled messages. Therefore the total number of test messages visible in the conversations is greater than 15. The “5 each / 15 total” count refers only to the final controlled run after the user asked for status and execution resumed cleanly.
- User manually confirmed the final visible result for each of Rick/Peter/Ken was five messages in the controlled run and reported no problem with those results.

## Click / mouse humanization research — closed

- CloakBrowser 0.5.10 has humanized click/scroll internals and works normally on simple pages.
- On Douyin, Playwright/Cloak mouse clicks could return success while producing no useful DOM mouse events or conversation switch.
- Direct Locator click, original Playwright mouse click, and low-level locator impl click all showed this Douyin-specific inconsistency.
- Headed mode alone did not fix it.
- OS/X11/xdotool could generate trusted (`isTrusted=true`) events and, in one calibrated run, switched Rick/Peter/Ken successfully six times.
- However X11 pointer-to-DOM mapping, hover state, and calibration were inconsistent across runs. The system pointer could visibly move inside Chromium while Douyin DOM `mousemove`/`:hover` did not reliably reflect it.
- The user and assistant agreed this became too complex relative to the benefit.
- Do not integrate X11/openbox/xdotool, coordinate calibration, render-window probing, or OS-level click logic into production.
- “Soft human DOM click” / random coordinate event sequences were discussed but intentionally not implemented. Current deterministic friend activation and send dispatch are more valuable for correctness.

## Local diagnostics

- Various ignored `.mcp/` probe scripts exist from scrolling/input/click experiments.
- They are diagnostic only and not production code.
- Examples include natural-scroll probes, draft-clear/input probes, and older X11 click/render-window probes.
- Do not assume a probe is part of the product just because it exists under `.mcp/`.

## Current conclusion / next conversation

- Humanization phase is finished and stable enough to stop changing.
- Preserve the current reliability-first balance:
  - humanize timing, typing, scrolling
  - keep recipient activation and send dispatch deterministic and verified
- Do not run more bulk real-message stability tests unless explicitly needed; enough real traffic has already been generated during development.
- Next likely feature: research/implement native large “续火花” sticker support.
- If implementing a sticker click that itself sends immediately, preserve the same safety model: exact recipient verification immediately before action, persist `attempted` before the irreversible send-like action, never retry after an uncertain dispatch, and verify from a fresh page afterward.
- For native sticker research, the previously mentioned reference project was `https://github.com/unmev/douyin-auto-fire`; inspect its current implementation independently before copying any assumptions.

## Upstream v3.2.1 review (2026-09-19)

- Fetched official `origin/main` at `3c54009` / tag `v3.2.1`; common merge-base with our branch remains `f0ff3d2`.
- Official update is large: ~61 files changed, about +5k/-1.2k lines. The central change is new `core/douyin_im.py` (~1690 lines) and a major rewrite of `core/tasks.py` around it.
- Mechanical merge preview reports only two Git conflicts: `core/tasks.py` (content) and the old `docs/Docker部署说明.md` (ours modified, upstream deleted). This understates the real problem: there are major semantic overlaps between upstream `core/douyin_im.py` and our `core/reliable_delivery.py` even though Git cannot flag them.
- Official strengths worth adopting/reusing: login/preflight gate, response monitoring, conv_id-based virtual-list scanning and deduplication, richer identity joining (remark/nickname/douyin_id/uid/sec_uid), explicit scan stop reasons, fold/stranger-group awareness, better scan logging, configTool refactor, browser binary-path handling, numeric-input wheel guard, GitHub Actions browser setup, docs restructuring, and removal of default gost credentials.
- Hard conflicts with our proven behavior:
  - upstream `type_and_send()` uses `page.keyboard.type(line)`; our real Douyin tests showed that path can drop ASCII/spaces, so keep our per-character `insert_text` path unless new live testing proves otherwise;
  - upstream draft clearing uses JS selection + `execCommand('delete')`; our double-`Ctrl+A` keyboard clear is live-tested and should remain the default;
  - upstream friend selection uses `page.mouse.move/down/up`; our earlier Douyin testing found Playwright/Cloak mouse input unreliable in this environment, so the upstream mouse path needs live validation before replacing our deterministic mousedown activation;
  - upstream retries a send once when no receipt is seen. This violates our at-most-once rule and can duplicate a message if delivery succeeded but the receipt was lost. Do not adopt this retry behavior;
  - upstream receipt confirmation is same-session HTTP/DOM based. Useful as a fast signal, but it should supplement rather than replace our persisted attempted/confirmed state plus fresh-page persistence verification;
  - upstream fuzzy substring target matching is broader but increases wrong-recipient risk. Rich exact identifiers are useful; fuzzy auto-send matching should be disabled or heavily constrained.
- Upstream tests are extensive for scanning/parsing/login behavior, but current test search found no coverage for our key duplicate-prevention scenario (successful send + lost receipt must not trigger another send).
- Config migration is not drop-in: official replaces `BROWSER_TIMEOUT`/old friend wait semantics with `BROWSER_ACTION_TIMEOUT`, `IM_SCAN_TIMEOUT`, `IM_READY_TIMEOUT`, `FRIEND_LIST_WAIT_TIME` in seconds, and `IM_MAX_STEPS`. Our current code still consumes the old config keys, so this needs an adapter/migration.
- Docker merge is also not drop-in: upstream switches the main service to a remote ACR image and makes GOST credentials mandatory; our deployment intentionally builds/uses the custom local image and adds the dashboard/random scheduler/optional gost profile. Keep our deployment shape and selectively adopt the security improvements.
- Recommended integration strategy: do NOT raw-merge v3.2.1 into current production and do NOT discard either side. Create a separate integration branch based on official v3.2.1, then port our safety/reliability/humanization layers onto the new official IM architecture. Keep current `main`/production untouched until the integration branch passes tests and small controlled live sends.
- Target end state: official `DouyinIM` for login + identity + scanning + response telemetry, wrapped by our at-most-once state machine, fresh-page verification, deterministic safe activation/send semantics, proven input/draft handling, random scheduler/dashboard, and selected humanized pacing/scrolling.

### Official v3.2.1 live stability test

- Before live testing, official core tests were run against the current official source using the existing CloakBrowser runtime: 110 tests passed, 15 HAR-dependent tests skipped. The Tk-only configTool wheel test was not part of this server runtime check because the runtime image does not contain Tk.
- Existing production `.env` is not directly compatible with v3.2.1 timing semantics: it has `FRIEND_LIST_WAIT_TIME=2000` from the old millisecond interpretation. Official v3.2.1 interprets that value as seconds. Live tests therefore overrode only the new timing variables inside the disposable test container (`FRIEND_LIST_WAIT_TIME=2`, official defaults/values for IM timeouts) without modifying production config.
- Official code was tested in five disposable containers using the exact `main` source at `3c54009`. Formal production containers were not restarted or replaced.
- Round 1: Rick, Ken, Peter were all matched by `remark` and selected successfully. All 3 sends returned HTTP `code=0`, `status=OK`, unique message IDs, and the task reported `发送成功=3 / 发送失败=0`.
- Round 1 also exposed a small scan-stat bookkeeping issue: after logging `3 个目标全部找到`, final scan state was still `stopped=caller-break / scanned_all=False` instead of `all-found`. Sending was not affected.
- Round 2: Peter, Ken, and Rick were all matched correctly by `remark` with correct conv_id values, but all three failed `_select_and_verify()` using the official `page.mouse.move/down/up` path. Final result: `找到=3 / 未找到=0 / select_failed=['Peter','Ken','Rick'] / 发送成功=0 / 发送失败=0`.
- Rounds 3, 4, and 5 reproduced the same failure pattern as round 2: all three targets were discovered correctly, all three failed selection, and each run ended with `发送成功=0 / 发送失败=0` plus `找到但选中失败=['Peter','Ken','Rick']`.
- All of rounds 2–5 exited with process code 0 and `账号任务完成` even though no target was actually sent. This is a meaningful reliability issue: select failures are not counted as send failures and do not make the task fail.
- Because the failures in rounds 2–5 happened before `type_and_send()`, the official automatic send-retry path was not exercised in this five-round test.
- Five-round aggregate: round 1 = 3/3 sends; rounds 2–5 = 0/3 each. Total successful deliveries = 3/15 attempted target opportunities, with each of Rick/Peter/Ken receiving exactly one new message from this official-code test series.
- This live result directly confirms the earlier concern from our click research: official v3.2.1's `page.mouse` selection path is not stable in this deployment environment even though its conv_id discovery/matching layer works well.
- No official-test containers remain. Formal custom runtime remains healthy and unchanged.

### Official v3.2.1 click-root-cause research

- CloakBrowser wrapper is `0.5.10`. With `humanize=True`, `page.mouse.move()` is patched to a human-like Bézier path with wobble/optional overshoot. `page.mouse.click()` is also patched and adds an aim delay plus randomized hold time. However official `DouyinIM._mouse_select()` does **not** use the fully humanized `page.mouse.click()`; it calls patched `page.mouse.move()` followed by the original raw `page.mouse.down()` / `page.mouse.up()` with no randomized hold. Thus the official selection path is partially humanized, not the full CloakBrowser click pipeline.
- When this physical mouse path works, captured browser events are genuinely trusted: `pointerdown/mousedown/mouseup/click` all reported `isTrusted=true` and switched to the expected conv_id.
- In a failing task-like session, instrumentation around the exact official `iter_find_and_select()` path observed 9 consecutive `_mouse_select()` attempts (3 targets × 3 retries) where **zero** pointer/mouse DOM events arrived even though the target geometry and `elementsFromPoint()` were correct. Waiting 10 seconds did not recover it. `page.mouse.click()`, `page._original.mouse_click()`, `bring_to_front()`, and direct CDP `Input.dispatchMouseEvent` also produced zero DOM events in that session. Synthetic `dispatch_event('mousedown')` immediately switched the correct conversation. This proves there is an intermittent session-level low-level input failure in this CloakBrowser/Chromium environment, not merely an application callback problem.
- A separate session where physical input was working exposed a second race: Rick was resolved as DOM index 0 / point `(151,86)`, but by the time trusted CDP input was dispatched at that point the event landed on **Ken**. The conversation list had reordered between identity resolution and physical click. This is especially plausible after sends, because recent conversations move to the top and initial IM sync continues updating/reordering rows.
- Official code already defines `JS_WINDOW_FINGERPRINT` but does not currently use it to gate selection readiness. The existing ready check verifies rendered count/title stability, not stable conversation ordering/conv_id mapping.
- CloakBrowser changelog is consistent with this class of issue: v0.5.6 fixed humanized clicks silently missing on pages that continue reflowing by rechecking/re-scrolling targets, and v0.5.9 fixed humanized actions selecting the wrong visible element. Official `_mouse_select()` bypasses much of that higher-level actionability logic by manually combining bounding-box coordinates with `page.mouse`.
- Recommended click integration design: keep official conv_id identity/scanning; before a physical click wait for the conversation window fingerprint/order to stabilize, humanized-move toward the current target, then re-resolve **the conv_id under the intended point immediately before mouse-down**. If it moved, recompute and move again. After the trusted click, verify current conv_id. If the low-level mouse channel produces no usable result after a small bounded number of attempts, fall back to our proven synthetic `mousedown` for conversation selection only. This hybrid preserves trusted/human-like clicks when available without sacrificing reliability.
- Do not apply this strategy to the irreversible send action: send remains single-shot/at-most-once and must not gain a physical-click-then-fallback double-dispatch path.

### `integrate-v3.2.1` selection reliability implementation

- Created branch `integrate-v3.2.1` directly from official v3.2.1 `3c54009`. No production deployment and no send-path changes have been made on this branch.
- Implemented a hybrid conversation-selection path in `core/douyin_im.py`:
  - `JS_WINDOW_FINGERPRINT` now includes visible item order, not only count/min/max index;
  - before a physical click, wait briefly for the visible conversation window to stabilize;
  - use CloakBrowser's humanized `page.mouse.move()` toward the current target;
  - immediately before mouse-down, resolve the conversation currently under that exact point and require its `conv_id` to still match the intended target; if the row reordered, do not click and re-resolve instead;
  - keep one press/release physical dispatch when the point is still bound to the target;
  - after bounded physical attempts fail, use the proven synthetic `mousedown` only for conversation selection, then require exact current `conv_id` verification;
  - this fallback is intentionally limited to reversible conversation selection and must never be copied to the send button.
- Added unit coverage for physical-success/no-fallback, physical-failure/fallback, failed fallback, point-reorder preventing mouse-down, and matching-point single press/release.
- Verification after implementation: `py_compile` passed, `git diff --check` passed, official core test set now runs 115 tests successfully with 15 HAR-dependent tests skipped.
- Real no-send validation used five brand-new browser sessions. Every session selected Rick, Peter, and Ken and verified the active `conv_id` after each selection: 15/15 correct selections, 0 wrong recipients, 0 `select_failed`.
- Physical/fallback breakdown:
  - rounds 1, 2, 4, 5: all three targets selected through the physical mouse path; no fallback needed;
  - round 3: reproduced the intermittent low-level mouse-channel failure. Each target exhausted three physical attempts, then the synthetic `mousedown` fallback selected Ken, Rick, and Peter correctly; round still finished 3/3.
- The five-round no-send test therefore directly demonstrates the intended behavior: trusted/humanized physical selection is preserved when the browser input channel works, while a failing physical-input session no longer causes the whole task to miss every target.
- Follow-up hardening added a per-`DouyinIM` physical-selection circuit breaker: after at least two real physical dispatches to one target still fail to switch the verified `conv_id`, the current IM session is marked physical-degraded. Subsequent targets in that same browser/IM session skip redundant physical attempts and go directly to the reversible synthetic `mousedown` fallback. A new browser/`DouyinIM` session starts with physical selection enabled again.
- Unit suite after the circuit breaker: 116 tests passed, 15 HAR-dependent tests skipped; `py_compile` and `git diff --check` also passed.
- A stricter same-session no-send stress test then repeatedly switched Rick/Peter/Ken in five different sequences (15 verified switches) without reopening the browser. Result: 15/15 correct final `conv_id`, 0 wrong recipients. In that session the low-level physical channel was degraded; only 3 physical dispatches were attempted before the circuit breaker tripped, then the remaining selections used fallback successfully. Before the breaker, the equivalent probe consumed 42 physical dispatches for the same 15 verified switches. This confirms the breaker removes repeated dead physical attempts without weakening selection correctness.
- No test containers remain. Formal production is still running the previous custom/stable image and was not restarted.
- Selection-integration code is committed as `0f8524c` (`WIP harden conversation selection`). It is an experimental checkpoint, not production-ready and not deployed.
- The next agent should treat `main` as pure official v3.2.1, `custom-pre-v3.2.1` as the previous stable/custom line (plus native-sticker WIP), and `integrate-v3.2.1` as the experimental official-based selection-integration line.

- Last updated: 2026-09-19 12:58 PDT
