// CapCut Translate — 화면. 빌드 없음: 고치고 새로고침하면 끝.
const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

const S = {
  state: null,        // /api/state
  projects: [],
  selected: null,     // draft_id
  texts: null,        // /api/projects/:id/texts
  langs: new Set(JSON.parse(localStorageGet("langs") || '["en"]')),
  search: "",
};

function localStorageGet(k) { try { return localStorage.getItem("cl." + k); } catch { return null; } }
function localStorageSet(k, v) { try { localStorage.setItem("cl." + k, v); } catch {} }

async function api(path, body) {
  const r = await fetch("/api/" + path, body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
  return data;
}

function toast(msg, bad = false) {
  const t = $("#toast");
  t.textContent = msg; t.className = "toast" + (bad ? " bad" : ""); t.hidden = false;
  clearTimeout(toast._t); toast._t = setTimeout(() => (t.hidden = true), bad ? 6000 : 2500);
}

const fmtDate = (sec) => sec ? new Date(sec * 1000).toLocaleString("ko-KR", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }) : "";
const fmtDur = (s) => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")}`;
const langLabel = (code) => S.state?.languages.find((l) => l.code === code)?.label || code;

// ─── 상태 ─────────────────────────────────────────────────────────────────
async function loadState() {
  S.state = await api("state");
  const cp = $("#capcutPill");
  cp.textContent = S.state.capcut_running ? "CapCut 켜짐 — 닫아야 만들 수 있음" : "CapCut 꺼짐";
  cp.className = "pill " + (S.state.capcut_running ? "warn" : "ok");
  const ep = $("#enginePill");
  ep.textContent = { "openai-api": "번역: OpenAI API", "codex-cli": "번역: codex CLI", none: "번역 엔진 없음 — 설정" }[S.state.engine];
  ep.className = "pill " + (S.state.engine === "none" ? "bad" : "");
  renderActionbar();
}

async function loadProjects() {
  try {
    S.projects = (await api("projects")).projects;
  } catch (e) {
    S.projects = [];
    $("#projects").innerHTML = `<div class="muted small">${esc(e.message)}</div>`;
    return;
  }
  renderList();
}

// ─── 목록 ─────────────────────────────────────────────────────────────────
function renderList() {
  const q = S.search.trim().toLowerCase();
  const byId = Object.fromEntries(S.projects.map((p) => [p.id, p]));
  const roots = S.projects.filter((p) => !p.copy_of || !byId[p.copy_of]);
  const children = (id) => S.projects.filter((p) => p.copy_of === id);
  const match = (p) => !q || p.name.toLowerCase().includes(q);
  let html = "";
  for (const p of roots) {
    const kids = children(p.id);
    if (!match(p) && !kids.some(match)) continue;
    html += item(p, false, kids);
    for (const k of kids) html += item(k, true, []);
  }
  $("#projects").innerHTML = html || `<div class="muted small">프로젝트가 없습니다.</div>`;
}

function item(p, child, kids) {
  const badges = child ? `<span class="badge">${esc(p.lang?.toUpperCase())}</span>`
    : kids.map((k) => `<span class="badge">${esc(k.lang?.toUpperCase())}</span>`).join("");
  return `<div class="proj ${child ? "child" : ""} ${p.id === S.selected ? "sel" : ""}" data-id="${esc(p.id)}">
    <img class="thumb" loading="lazy" src="${p.has_cover ? "/cover/" + encodeURIComponent(p.id) : ""}" alt="">
    <div><div class="name">${esc(p.name)}</div>
    <div class="muted small">${fmtDate(p.modified)} · ${fmtDur(p.duration)}</div>
    <div>${badges}</div></div></div>`;
}

// ─── 상세 ─────────────────────────────────────────────────────────────────
async function select(id) {
  S.selected = id; S.texts = null;
  renderList(); renderDetail();
  try {
    S.texts = await api(`projects/${encodeURIComponent(id)}/texts`);
  } catch (e) { toast(e.message, true); }
  renderDetail();
}

function current() { return S.projects.find((p) => p.id === S.selected); }

function copyName(p, lang) {
  const pattern = $("#pattern")?.value || S.state.name_pattern;
  return pattern.replaceAll("{name}", p.name).replaceAll("{lang}", lang.toUpperCase());
}

function renderDetail() {
  const p = current();
  const d = $("#detail");
  if (!p) { d.innerHTML = `<div class="empty">왼쪽에서 프로젝트를 고르세요.</div>`; renderActionbar(); return; }
  const t = S.texts;
  const copies = S.projects.filter((x) => x.copy_of === p.id);
  const langs = [...S.langs];
  d.innerHTML = `
    <div class="head">
      <img src="${p.has_cover ? "/cover/" + encodeURIComponent(p.id) : ""}" alt="">
      <div>
        <h2>${esc(p.name)}</h2>
        <div class="muted">${fmtDate(p.modified)} · ${fmtDur(p.duration)}${p.copy_of ? ` · ${esc(langLabel(p.lang))} 사본` : ""}</div>
        <div class="stats">${t ? `
          <span class="pill">텍스트 ${t.text_count}개</span>
          <span class="pill">번역할 문장 ${t.texts.length}개</span>
          ${t.subtitle_count ? `<span class="pill">자동 자막 ${t.subtitle_count}개</span>` : ""}
          ${t.tts_count ? `<span class="pill warn">글자 읽어주기 음성 ${t.tts_count}개 — 음성은 원어 그대로 남음</span>` : ""}`
          : `<span class="pill">텍스트 읽는 중…</span>`}
        </div>
        <div class="row"><button class="ghost" data-open="${esc(p.id)}">폴더 열기</button></div>
      </div>
    </div>

    <div class="section">
      <h3>① 만들 언어</h3>
      <div class="chips">${S.state.languages.filter((l) => l.code !== "ko").map((l) =>
        `<button class="chip ${S.langs.has(l.code) ? "on" : ""}" data-lang="${l.code}">${esc(l.label)}</button>`).join("")}
      </div>
    </div>

    <div class="section">
      <h3>② 사본 이름</h3>
      <input id="pattern" value="${esc(S.state.name_pattern)}">
      <div class="names muted small">${langs.map((l) => "→ " + esc(copyName(p, l))).join("<br>") || "언어를 고르세요."}</div>
    </div>

    <div class="section">
      <div class="row" style="justify-content:space-between">
        <h3>③ 번역 확인·수정 <span class="muted small">(고친 문장은 저장돼 복제에 그대로 쓰입니다)</span></h3>
        <button class="ghost" id="btnPreview" ${!t || !langs.length ? "disabled" : ""}>번역 미리보기</button>
      </div>
      ${t ? table(t, langs) : ""}
    </div>

    ${copies.length ? `<div class="section copies"><h3>이 프로젝트의 사본</h3>
      ${copies.map((c) => `<div class="copy"><span class="badge">${esc(c.lang?.toUpperCase())}</span>
        <span class="name">${esc(c.name)}</span>
        <button class="ghost" data-open="${esc(c.id)}">폴더</button>
        <button class="danger" data-delete="${esc(c.id)}">삭제</button></div>`).join("")}</div>` : ""}
  `;
  renderActionbar();
}

function table(t, langs) {
  if (!t.texts.length) return `<div class="muted">번역할 텍스트가 없습니다.</div>`;
  const head = `<tr><th>원문</th>${langs.map((l) => `<th>${esc(langLabel(l))}</th>`).join("")}</tr>`;
  const rows = t.texts.map((src, i) => `<tr><td class="src">${esc(src)}</td>${langs.map((l) => {
    const v = t.translations?.[l]?.[src];
    return `<td><textarea rows="${Math.max(1, src.split("\n").length)}" data-i="${i}" data-l="${l}"
      class="${v ? "" : "missing"}" placeholder="번역 전">${esc(v || "")}</textarea></td>`;
  }).join("")}</tr>`).join("");
  return `<table>${head}${rows}</table>`;
}

// ─── 하단 실행 바 ─────────────────────────────────────────────────────────
function renderActionbar() {
  let bar = $("#actionbar");
  if (!bar) {
    bar = document.createElement("div");
    bar.id = "actionbar"; bar.className = "actionbar";
    document.body.appendChild(bar);
  }
  const p = current();
  if (!p || !S.state) { bar.hidden = true; return; }
  bar.hidden = false;
  const n = S.langs.size;
  const running = S.state.capcut_running;
  bar.innerHTML = `<div class="msg ${running ? "" : "muted"}">${running
    ? "⚠ CapCut 이 켜져 있습니다. 닫은 뒤 만드세요 — 켜진 채 만들면 CapCut 종료 때 목록에서 사라집니다."
    : n ? `원본은 그대로 두고 ${n}개의 새 프로젝트를 만듭니다. 번역 안 된 문장은 자동으로 번역합니다.` : "언어를 고르세요."}</div>
    <button id="btnCreate" ${!n || running || S.state.engine === "none" ? "disabled" : ""}>${n || ""}개 언어로 복제 만들기</button>`;
}

// ─── 작업 진행 ────────────────────────────────────────────────────────────
async function runJob(jobId) {
  const m = $("#jobModal"); m.hidden = false;
  try {
    for (;;) {
      const j = await api("jobs/" + jobId);
      $("#jobTitle").textContent = j.title;
      $("#jobLabel").textContent = j.label;
      $("#jobDetail").textContent = j.detail;
      $("#jobBar").style.width = `${Math.round((j.step / Math.max(1, j.total)) * 100)}%`;
      $("#jobElapsed").textContent = `${Math.round(Date.now() / 1000 - j.started)}초 경과`;
      if (j.state === "done") return j.result;
      if (j.state === "failed") throw new Error(j.error);
      await new Promise((r) => setTimeout(r, document.hidden ? 3000 : 700));
    }
  } finally { m.hidden = true; }
}

async function preview() {
  const p = current();
  try {
    const { job } = await api("translate", { id: p.id, langs: [...S.langs] });
    await runJob(job);
    S.texts = await api(`projects/${encodeURIComponent(p.id)}/texts`);
    renderDetail();
    toast("번역을 불러왔습니다. 칸을 눌러 고칠 수 있습니다.");
  } catch (e) { toast(e.message, true); }
}

async function create() {
  const p = current();
  try {
    const { job } = await api("copies", { id: p.id, langs: [...S.langs], pattern: $("#pattern").value });
    const res = await runJob(job);
    await loadProjects();
    S.texts = await api(`projects/${encodeURIComponent(p.id)}/texts`);
    renderDetail();
    toast(`${res.copies.length}개 만들었습니다. CapCut 을 켜면 목록에 보입니다.`);
  } catch (e) { toast(e.message, true); await loadState(); }
}

// ─── 이벤트 ───────────────────────────────────────────────────────────────
document.addEventListener("click", async (e) => {
  const el = e.target.closest("[data-id],[data-lang],[data-open],[data-delete],#btnPreview,#btnCreate,[data-close]");
  if (!el) return;
  if (el.dataset.close !== undefined) { el.closest(".modal").hidden = true; return; }
  if (el.id === "btnPreview") return preview();
  if (el.id === "btnCreate") return create();
  if (el.dataset.lang) {
    S.langs.has(el.dataset.lang) ? S.langs.delete(el.dataset.lang) : S.langs.add(el.dataset.lang);
    localStorageSet("langs", JSON.stringify([...S.langs]));
    return renderDetail();
  }
  if (el.dataset.open) return api("open", { id: el.dataset.open }).catch((er) => toast(er.message, true));
  if (el.dataset.delete) {
    const c = S.projects.find((x) => x.id === el.dataset.delete);
    if (!confirm(`«${c.name}» 사본을 지울까요? 폴더째 삭제되고 되돌릴 수 없습니다.`)) return;
    try { await api("delete", { id: c.id }); await loadProjects(); renderDetail(); toast("삭제했습니다."); }
    catch (er) { toast(er.message, true); }
    return;
  }
  if (el.dataset.id) return select(el.dataset.id);
});

document.addEventListener("input", (e) => {
  if (e.target.id === "pattern") {
    const p = current();
    document.querySelector(".names").innerHTML = [...S.langs].map((l) => "→ " + esc(copyName(p, l))).join("<br>");
  }
  if (e.target.id === "search") { S.search = e.target.value; renderList(); }
});

document.addEventListener("change", async (e) => {
  const ta = e.target;
  if (ta.tagName !== "TEXTAREA" || ta.dataset.l === undefined) return;
  const src = S.texts.texts[+ta.dataset.i], lang = ta.dataset.l, dst = ta.value;
  if (!dst.trim()) return;
  try {
    await api("translation", { lang, src, dst });
    ((S.texts.translations[lang] ||= {}))[src] = dst;
    ta.classList.remove("missing");
  } catch (er) { toast(er.message, true); }
});

$("#btnRefresh").onclick = async () => { await loadState(); await loadProjects(); if (S.selected) select(S.selected); };
$("#btnOpenRoot").onclick = () => api("open", {}).catch((e) => toast(e.message, true));
$("#btnSettings").onclick = () => {
  const f = $("#settingsForm");
  f.draft_root.value = S.state.root || "";
  f.openai_api_key.value = "";
  f.openai_api_key.placeholder = S.state.has_key ? "저장됨 — 바꾸려면 새 키 입력" : "sk-…";
  f.openai_model.value = S.state.openai_model;
  f.name_pattern.value = S.state.name_pattern;
  $("#rootHint").textContent = "자동 후보: " + S.state.candidates.join("  |  ");
  $("#settingsModal").hidden = false;
};
$("#settingsForm").onsubmit = async (e) => {
  e.preventDefault();
  const f = e.target;
  const body = { draft_root: f.draft_root.value, openai_model: f.openai_model.value, name_pattern: f.name_pattern.value };
  if (f.openai_api_key.value.trim()) body.openai_api_key = f.openai_api_key.value;
  try {
    await api("settings", body);
    $("#settingsModal").hidden = true;
    await loadState(); await loadProjects(); renderDetail();
    toast("저장했습니다.");
  } catch (er) { toast(er.message, true); }
};

// CapCut 켜짐/꺼짐은 계속 확인(창이 보일 때만).
setInterval(() => { if (!document.hidden) loadState().catch(() => {}); }, 4000);

(async () => {
  try { await loadState(); await loadProjects(); }
  catch (e) { toast("서버에 연결하지 못했습니다: " + e.message, true); }
})();
