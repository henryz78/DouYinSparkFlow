const $ = (id) => document.getElementById(id);
const STATUS = { ok: "全部成功", partial: "部分成功", failed: "失败", error: "异常中断" };
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const pad = (n) => String(n).padStart(2, "0");
const hm = (iso) => { const d = new Date(iso); return `${pad(d.getHours())}:${pad(d.getMinutes())}`; };
const md = (iso) => { const d = new Date(iso); return `${d.getMonth() + 1} 月 ${d.getDate()} 日`; };
const get = (url) => fetch(url).then((r) => r.json());

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
  const [a, b, , cls] = HERO[s.state];
  $("hero").innerHTML = `${a}<br><em>${b}</em>`;
  $("today-eyebrow").className = "eyebrow " + cls;
  $("today-eyebrow").textContent = cls ? "需要你处理" : "今日";
  $("hero-sub").textContent =
    s.state === "pending" ? `预计 ${hm(s.next_start)} – ${hm(s.next_end)} 之间发送。`
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

const LOAD = { overview: loadOverview, runs: loadRuns, logs: loadLogs };
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
addEventListener("hashchange", route);
addEventListener("scroll", () => $("nav").classList.toggle("scrolled", scrollY > 4), { passive: true });
route();
