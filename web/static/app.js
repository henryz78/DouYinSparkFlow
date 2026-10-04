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

const HERO = {
  ok: ["今天", "已发送", "", ""],
  partial: ["今天", "部分发送", "", "alert"],
  failed: ["今天", "发送失败", "", "alert"],
  pending: ["今天", "还没到点", "", ""],
  missing: ["今天", "没有记录", "", "alert"],
};

async function loadOverview() {
  const [s, runs] = await Promise.all([get("/api/summary"), get("/api/runs?limit=5")]);
  const [a, b, , cls] = HERO[s.state];
  $("hero").innerHTML = `${a}<br><em>${b}</em>`;
  $("today-eyebrow").className = "eyebrow " + cls;
  $("today-eyebrow").textContent = cls ? "需要你处理" : "今日";
  $("hero-sub").textContent =
    s.state === "pending" ? `预计 ${hm(s.next_start)} – ${hm(s.next_end)} 之间发送。`
    : s.state === "missing" ? "发送窗口已过，今天还没有运行记录。去日志里看看容器有没有在跑。"
    : `已发送 ${s.sent} / ${s.targets} 位好友，${hm(s.finished)} 完成。${s.problems.length ? "问题：" + s.problems.join("；") : ""}`;
  $("s-streak").textContent = s.streak;
  $("s-best").textContent = `历史最长 ${s.best_streak} 天`;
  $("s-rate").textContent = s.rate_30 == null ? "–" : s.rate_30 + "%";
  $("s-days").textContent = `已记录 ${s.days_recorded} 天`;
  $("s-next").textContent = `${dayWord(s.next_start)} ${hm(s.next_start)}`;
  $("s-next-sub").textContent = s.next_end !== s.next_start ? `随机窗口至 ${hm(s.next_end)}` : "定点发送";
  $("recent").innerHTML = runs.length ? runs.map(rowHtml).join("") : '<li class="empty">还没有运行记录。下一次运行后会出现在这里。</li>';
}

let runsCache = [], runFilter = "all";
function drawRuns() {
  const list = runsCache.filter((r) => runFilter === "all" || (runFilter === "ok" ? r.status === "ok" : r.status !== "ok"));
  $("run-count").textContent = `${list.length} 条`;
  $("run-list").innerHTML = list.length ? list.map(rowHtml).join("") : '<li class="empty">没有符合条件的记录。</li>';
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
  clearInterval(timer);
  if (tab === "logs") timer = setInterval(() => $("log-auto").checked && loadLogs().catch(() => {}), 5000);
  window.scrollTo(0, 0);
}
addEventListener("hashchange", route);
addEventListener("scroll", () => $("nav").classList.toggle("scrolled", scrollY > 4), { passive: true });
route();
