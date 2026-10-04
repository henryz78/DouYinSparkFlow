const $ = (id) => document.getElementById(id);
const STATUS = { ok: "全部成功", partial: "部分成功", failed: "失败", error: "异常中断" };
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const pad = (n) => String(n).padStart(2, "0");
const hm = (iso) => { const d = new Date(iso); return `${pad(d.getHours())}:${pad(d.getMinutes())}`; };
const md = (iso) => { const d = new Date(iso); return `${d.getMonth() + 1} 月 ${d.getDate()} 日`; };
const get = async (url) => {
  const r = await fetch(url);
  if (r.status === 401) { showLogin(); throw new Error("401"); }
  return r.json();
};
const post = (url, body) => fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
const showLogin = () => { document.body.classList.add("locked"); $("login").hidden = false; $("pw").focus(); };

function dayWord(iso) {
  const d = new Date(iso), t = new Date();
  const diff = Math.round((new Date(d.getFullYear(), d.getMonth(), d.getDate()) - new Date(t.getFullYear(), t.getMonth(), t.getDate())) / 864e5);
  return diff === 0 ? "今天" : diff === 1 ? "明天" : md(iso);
}

function rowHtml(r) {
  const prob = r.problems.length ? `<span class="small">${esc(r.problems.join("；"))}</span>` : "";
  return `<li><span class="when">${md(r.start)}<small>${hm(r.start)} – ${hm(r.end)}</small></span>
    <span class="what">${esc(r.account)} · 已发送 ${r.sent} / ${r.targets}${prob}</span>
    <span class="state ${r.status}">${STATUS[r.status] || r.status}</span></li>`;
}

const NOTIFY = { true: "已送达", false: "未送达", null: "未发送" };
const FSTATE = { ok: "已发送", failed: "失败", missing: "未找到", select_failed: "选中失败", waiting: "等待" };
const span = (a, b) => { const s = Math.max(0, Math.round((new Date(b) - new Date(a)) / 1000)); return s < 60 ? `${s} 秒` : `${Math.floor(s / 60)} 分 ${s % 60} 秒`; };

// 记录页的详细版：信息量对齐 Telegram 通知（账号、方式、目标好友、结果、问题）
function detailHtml(r) {
  const friends = (r.friends && r.friends.length ? r.friends : (r.target_names || []).map((name) => ({ name, status: "" })))
    .map((f) => `<li>${esc(f.name)}${f.status ? `<span class="state ${f.status}">${FSTATE[f.status] || f.status}</span>` : ""}</li>`).join("");
  const kv = (k, v) => v ? `<div><p class="eyebrow">${k}</p><p>${v}</p></div>` : "";
  return `<li class="rec">
    <div class="rec-head"><span class="when">${md(r.start)} <small>${hm(r.start)} – ${hm(r.end)} · 耗时 ${span(r.start, r.end)}</small></span>
      <span class="state ${r.status}">${STATUS[r.status] || r.status}</span></div>
    <div class="kv">${kv("账号", esc(r.account))}${kv("方式", esc(r.method || ""))}${kv("结果", `${r.sent} / ${r.targets} 已发送`)}${kv("Telegram", NOTIFY[r.notified])}</div>
    ${friends ? `<div><p class="eyebrow">目标好友</p><ul class="friends">${friends}</ul></div>` : ""}
    ${r.problems.length ? `<div class="problem"><p class="eyebrow alert">问题</p><p>${esc(r.problems.join("；"))}</p></div>` : ""}
  </li>`;
}

const HERO = {
  ok: ["今天", "已发送", "", ""],
  running: ["今天", "发送中", "", ""],
  partial: ["今天", "部分发送", "", "alert"],
  failed: ["今天", "发送失败", "", "alert"],
  pending: ["今天", "还没到点", "", ""],
  missing: ["今天", "没有记录", "", "alert"],
};

const CAL = { ok: "成功", partial: "部分成功", failed: "失败", none: "无记录" };
const duration = (sec) => {
  const d = Math.floor(sec / 86400), h = Math.floor(sec % 86400 / 3600), m = Math.floor(sec % 3600 / 60);
  return d ? `${d} 天 ${h} 小时` : h ? `${h} 小时 ${m} 分` : `${m} 分钟`;
};

let sum = null, tick;
function drawClock() {
  if (!sum) return;
  const now = Date.now(), a = Date.parse(sum.next_start), b = Date.parse(sum.next_end);
  const left = (t) => { const s = Math.max(0, Math.round((t - now) / 1000)); return `${pad(Math.floor(s / 3600))}:${pad(Math.floor(s % 3600 / 60))}:${pad(s % 60)}`; };
  const inWindow = now >= a && now <= b && sum.state === "pending";
  $("bar").hidden = !inWindow;
  if (inWindow) {
    $("clock").textContent = left(b);
    $("clock-note").textContent = "发送窗口进行中，最迟在此之前发送";
    $("bar-fill").style.width = (b > a ? 100 * (now - a) / (b - a) : 100) + "%";
  } else {
    $("clock").textContent = now < a ? left(a) : "–";
    $("clock-note").textContent = now < a ? "距离发送窗口开始" : "发送窗口已过";
  }
}

async function loadOverview() {
  const [s, runs] = await Promise.all([get("/api/summary"), get("/api/runs?limit=5")]);
  sum = s;
  const [a, b, , cls] = HERO[s.running ? "running" : s.state];
  setRunning(s.running);
  $("hero").innerHTML = `${a}<br><em>${b}</em>`;
  $("today-eyebrow").className = "eyebrow " + cls;
  $("today-eyebrow").textContent = cls ? "需要你处理" : "今日";
  $("hero-sub").textContent =
    s.running ? "任务正在运行，完成后这里会自动更新。"
    : s.state === "pending" ? `预计 ${hm(s.next_start)} – ${hm(s.next_end)} 之间发送。`
    : s.state === "missing" ? "发送窗口已过，今天还没有运行记录。去日志里看看容器有没有在跑。"
    : `已发送 ${s.sent} / ${s.targets} 位好友，${hm(s.finished)} 完成。${s.problems.length ? "问题：" + s.problems.join("；") : ""}`;
  $("friends").innerHTML = s.friends.map((f) => `<li>${esc(f.name)}<span class="state ${f.status}">${FSTATE[f.status] || f.status}</span></li>`).join("");
  $("next-sub").textContent = `${dayWord(s.next_start)} ${hm(s.next_start)}` + (s.next_end !== s.next_start ? ` – ${hm(s.next_end)}（随机窗口）` : "（定点发送）");
  $("s-streak").textContent = s.streak;
  $("s-days").textContent = `已记录 ${s.days_recorded} 天`;
  $("s-best").textContent = s.best_streak;
  $("s-rate").textContent = s.rate_30 == null ? "–" : s.rate_30 + "%";
  $("s-rate-sub").textContent = s.rate_30 == null ? "还没有数据" : "按有记录的天数计算";
  $("cal").innerHTML = s.calendar.map((c, i) =>
    `<i class="sq ${c.status}${i === s.calendar.length - 1 ? " today" : ""}" title="${c.date} · ${CAL[c.status]}"></i>`).join("");
  const h = s.health, dot = (cls, t) => `<span class="state ${cls}">${t}</span>`;
  $("health").innerHTML = [
    ["登录状态", { ok: dot("ok", "正常"), bad: dot("failed", "已失效，需要重新登录"), unknown: "暂无记录" }[h.login]],
    ["Telegram 通知", { ok: dot("ok", "上次已送达"), failed: dot("failed", "上次未送达"), off: "上次未发送", unknown: "暂无记录" }[h.telegram]],
    ["容器已运行", duration(h.uptime)],
    ["版本", esc(h.version || "–")],
  ].map(([k, v]) => `<div><p class="eyebrow">${k}</p><p>${v}</p></div>`).join("");
  $("recent").innerHTML = runs.length ? runs.map(rowHtml).join("") : '<li class="empty">还没有运行记录。下一次运行后会出现在这里。</li>';
  drawClock();
}

let runsCache = [], runFilter = "all";
function drawRuns() {
  const list = runsCache.filter((r) => runFilter === "all" || (runFilter === "ok" ? r.status === "ok" : r.status !== "ok"));
  $("run-count").textContent = `${list.length} 条`;
  $("run-list").innerHTML = list.length ? list.map(detailHtml).join("") : '<li class="empty">没有符合条件的记录。</li>';
}
async function loadRuns() { runsCache = await get("/api/runs?limit=500"); drawRuns(); }

let logLines = [], logFilter = "all";
const LEVEL = / - (DEBUG|INFO|WARNING|ERROR|CRITICAL) - /;
function drawLogs() {
  const keep = { all: () => true, WARNING: (l) => /WARNING|ERROR|CRITICAL/.test(l), ERROR: (l) => /ERROR|CRITICAL/.test(l) }[logFilter];
  const box = $("log-box"), stick = box.scrollTop + box.clientHeight >= box.scrollHeight - 40;
  box.innerHTML = logLines.filter((l) => keep(LEVEL.test(l) ? l : "")).map((l) => {
    const m = l.match(LEVEL);
    return `<span class="${m ? m[1] : ""}">${esc(l)}</span>`;
  }).join("\n") || "暂无日志。";
  if (stick) box.scrollTop = box.scrollHeight;
}
async function loadLogs() { logLines = await get("/api/logs?lines=400"); drawLogs(); }

function chips(id, set) {
  $(id).addEventListener("click", (e) => {
    const b = e.target.closest(".chip"); if (!b) return;
    $(id).querySelectorAll(".chip").forEach((c) => c.classList.toggle("on", c === b));
    set(b.dataset.f);
  });
}
chips("run-filter", (f) => { runFilter = f; drawRuns(); });
chips("log-filter", (f) => { logFilter = f; drawLogs(); });

// ---- 配置页：字段由后端 /api/config 描述，这里只负责渲染和提交变更的部分 ----
let cfgLoaded = null;
const GROUPS = { time: "发送时间", content: "发送内容", telegram: "Telegram 通知" };
const ENUM = { text: "文本消息", native_sticker: "原生贴纸" };
const attr = (s) => esc(s).replace(/'/g, "&#39;");

function fieldHtml(f) {
  const id = "f-" + f.key;
  if (f.type === "bool") return `<label class="switch"><input type="checkbox" id="${id}" ${f.value ? "checked" : ""}>${f.label}</label>`;
  if (f.type === "enum") return `<div class="field"><label for="${id}">${f.label}</label><select class="input" id="${id}">${f.range.map((o) => `<option value="${o}" ${o === f.value ? "selected" : ""}>${ENUM[o] || o}</option>`).join("")}</select></div>`;
  if (f.type === "int") {
    const minutes = f.key === "CRON_RANDOM_WINDOW_SECONDS";
    const [lo, hi] = minutes ? [0, f.range[1] / 60] : f.range;
    return `<div class="field"><label for="${id}">${minutes ? "随机窗口（分钟）" : f.label}</label><input class="input" type="number" id="${id}" min="${lo}" max="${hi}" value="${minutes ? Math.round(f.value / 60) : Number(f.value)}">${f.hint && !minutes ? `<p class="small">${f.hint}</p>` : minutes ? '<p class="small">到点后再随机等 0 到这么多分钟才发送，0 表示不随机</p>' : ""}<p class="small error" data-err="${f.key}"></p></div>`;
  }
  return `<div class="field"><label for="${id}">${f.label}</label>${f.key === "MESSAGE_TEMPLATE" ? `<textarea class="input" id="${id}" rows="3">${esc(f.value)}</textarea>` : `<input class="input" id="${id}" value="${attr(f.value)}">`}${f.hint ? `<p class="small">${esc(f.hint)}</p>` : ""}<p class="small error" data-err="${f.key}"></p></div>`;
}

async function loadConfig() {
  const c = await get("/api/config");
  cfgLoaded = c;
  const by = (g) => c.fields.filter((f) => f.group === g);
  const time = by("time"), hms = time.slice(0, 3);
  $("cfg-form").innerHTML = `
    <fieldset><legend>${GROUPS.time}</legend>
      <div class="row3">${hms.map(fieldHtml).join("")}</div>
      <p class="small" style="margin:6px 0 20px">每天这个时刻触发，再叠加下面的随机窗口。</p>
      ${time.slice(3).map(fieldHtml).join("")}</fieldset>
    <fieldset><legend>${GROUPS.content}</legend>${by("content").map(fieldHtml).join("")}</fieldset>
    <fieldset><legend>好友名单</legend>${c.accounts.map((a) => `<div class="field acct"><label for="acct-${a.id}">${esc(a.name)}（每行一位好友）</label><textarea class="input" id="acct-${a.id}" rows="${Math.max(3, a.targets.length + 1)}">${esc(a.targets.join("\n"))}</textarea><p class="small error" data-err="account-${a.id}"></p></div>`).join("") || '<p class="small">没有账号。</p>'}</fieldset>
    <fieldset><legend>${GROUPS.telegram}</legend>${by("telegram").map(fieldHtml).join("")}<p class="small">Token 和 Chat ID 不在网页里显示或修改。</p></fieldset>
    <div class="savebar"><button class="btn primary" type="submit">保存并生效</button><span class="small" id="cfg-msg"></span></div>`;
}

$("cfg-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!cfgLoaded) return;
  const values = {}, targets = {};
  for (const f of cfgLoaded.fields) {
    const el = $("f-" + f.key);
    let v = f.type === "bool" ? el.checked : f.type === "int" ? Number(el.value) : el.value;
    if (f.key === "CRON_RANDOM_WINDOW_SECONDS") v = Math.round(v * 60);
    const old = f.type === "int" ? Number(f.value) : f.value;
    if (v !== old) values[f.key] = v;  // 只提交改过的项，没动的原样保留
  }
  for (const a of cfgLoaded.accounts) {
    const names = $("acct-" + a.id).value.split("\n").map((x) => x.trim()).filter(Boolean);
    if (JSON.stringify(names) !== JSON.stringify(a.targets)) targets[a.id] = names;
  }
  document.querySelectorAll("[data-err]").forEach((p) => (p.textContent = ""));
  const msg = $("cfg-msg"); msg.className = "small"; msg.textContent = "保存中…";
  const r = await post("/api/config", { values, targets });
  if (r.status === 401) return showLogin();
  const out = await r.json();
  if (r.status === 400) {
    for (const [k, m] of Object.entries(out.errors)) { const p = document.querySelector(`[data-err="${k}"]`); if (p) p.textContent = m; }
    msg.className = "small bad"; msg.textContent = "有内容不合法，请看红字提示。";
    return;
  }
  msg.className = "small " + (out.ok ? "ok" : "bad");
  msg.textContent = out.message || out.error || "失败";
  if (out.ok) loadConfig().then(() => { $("cfg-msg").className = "small ok"; $("cfg-msg").textContent = out.message; });
});

const LOAD = { overview: loadOverview, runs: loadRuns, logs: loadLogs, config: loadConfig };
let timer;
function route() {
  const tab = LOAD[location.hash.slice(1)] ? location.hash.slice(1) : "overview";
  for (const t of Object.keys(LOAD)) $("tab-" + t).hidden = t !== tab;
  document.querySelectorAll("#links a").forEach((a) => a.classList.toggle("on", a.dataset.tab === tab));
  LOAD[tab]().catch(() => {});
  clearInterval(timer); clearInterval(tick);
  if (tab === "overview") tick = setInterval(drawClock, 1000);
  if (tab === "logs") timer = setInterval(() => $("log-auto").checked && loadLogs().catch(() => {}), 5000);
  window.scrollTo(0, 0);
}
let pollTimer;
function setRunning(on) {
  $("run-btn").disabled = on;
  $("run-btn").textContent = on ? "运行中…" : "立即运行";
  clearTimeout(pollTimer);
  if (on) pollTimer = setTimeout(() => LOAD[currentTab()]().catch(() => {}), 3000);
}
const currentTab = () => (LOAD[location.hash.slice(1)] ? location.hash.slice(1) : "overview");

$("run-btn").addEventListener("click", () => $("confirm").showModal());
$("confirm").addEventListener("close", async () => {
  if ($("confirm").returnValue !== "ok") return;
  const r = await post("/api/run");
  if (r.status === 401) return showLogin();
  if (!r.ok) alert((await r.json()).error || "启动失败");
  setRunning(true);
  location.hash = "#overview";
  loadOverview().catch(() => {});
});
$("login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const r = await post("/api/login", { password: $("pw").value });
  if (!r.ok) { $("login-err").textContent = (await r.json()).error || "登录失败"; return; }
  $("pw").value = ""; $("login-err").textContent = "";
  document.body.classList.remove("locked"); $("login").hidden = true;
  route();
});
$("logout").addEventListener("click", async () => { await post("/api/logout"); location.reload(); });

addEventListener("hashchange", route);
addEventListener("scroll", () => $("nav").classList.toggle("scrolled", scrollY > 4), { passive: true });
route();
