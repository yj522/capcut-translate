// CapCut Translate — 화면. 빌드 없음: 고치고 새로고침하면 끝.
const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

const S = {
  state: null,        // /api/state
  projects: [],
  listError: null,
  selected: null,     // draft_id
  texts: null,        // /api/projects/:id/texts
  langs: new Set(JSON.parse(localStorageGet("langs") || '["en"]')),
  onlyMissing: false,
  withTts: localStorageGet("tts") !== "0", // 음성도 바꾸기(Typecast 키가 있을 때만 실제로 켜짐)
  voices: null,       // /api/tts/voices
  voicesError: null,
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

const ICON = {
  check: `<svg viewBox="0 0 24 24"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>`,
  folder: `<svg viewBox="0 0 24 24"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>`,
  trash: `<svg viewBox="0 0 24 24"><path d="M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3"/></svg>`,
  alert: `<svg viewBox="0 0 24 24"><path d="M12 3l10 18H2zM12 10v4M12 17.5v.01"/></svg>`,
  info: `<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 7.5v.01"/></svg>`,
  sparkle: `<svg viewBox="0 0 24 24"><path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8zM19 16l.8 2.2L22 19l-2.2.8L19 22l-.8-2.2L16 19l2.2-.8z"/></svg>`,
  copy: `<svg viewBox="0 0 24 24"><rect x="8" y="8" width="13" height="13" rx="2"/><path d="M16 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h3"/></svg>`,
  back: `<svg viewBox="0 0 24 24"><path d="M15 18l-6-6 6-6"/></svg>`,
};
const LOGO = `<span class="logo"><svg viewBox="0 0 24 24"><path d="M4 6h9M8.5 4v2c0 4-2 7-4.5 8.5M6 10c1 2.5 3.5 4.5 6 5.5"/><path d="M13 20l4-9 4 9M14.5 17h5"/></svg></span>`;

const fmtDate = (sec) => sec ? new Date(sec * 1000).toLocaleString("ko-KR", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "";
const fmtDur = (s) => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")}`;
const langLabel = (code) => S.state?.languages.find((l) => l.code === code)?.label || code;
const cover = (p) => p.has_cover ? `/cover/${encodeURIComponent(p.id)}?m=${p.modified}` : "";
const targetLangs = () => (S.state?.languages || []).filter((l) => l.code !== "ko");
const chosenLangs = () => targetLangs().map((l) => l.code).filter((c) => S.langs.has(c)); // 화면 순서대로

// ─── 상태 ─────────────────────────────────────────────────────────────────
async function loadState() {
  const prev = S.state;
  S.state = await api("state");
  const running = S.state.capcut_running;
  setPill($("#capcutPill"), running ? "warn" : "ok", running ? "CapCut 켜짐 — 닫아야 만들 수 있음" : "CapCut 꺼짐");
  const eng = { pearlstudio: ["ok", `번역: Pearl Studio${S.state.pearl_user ? " · " + S.state.pearl_user.username : ""}`],
    "openai-api": ["", "번역: OpenAI API"], "codex-cli": ["", "번역: codex CLI"], none: ["bad", "번역 엔진 없음 — 설정 필요"] }[S.state.engine];
  setPill($("#enginePill"), eng[0], eng[1]);
  if (!prev) renderDetail();
  else if (prev.capcut_running !== running || prev.engine !== S.state.engine) renderActionbar();
}

function setPill(el, cls, text) {
  el.className = "pill " + cls;
  el.querySelector("span").textContent = text;
}

async function loadProjects() {
  try {
    S.projects = (await api("projects")).projects;
    S.listError = null;
  } catch (e) {
    S.projects = []; S.listError = e.message;
  }
  if (S.selected && !current()) { S.selected = null; S.texts = null; }
  renderList();
}

// ─── 목록 ─────────────────────────────────────────────────────────────────
function renderList() {
  const box = $("#projects");
  if (S.listError) {
    $("#listHead").innerHTML = "";
    box.innerHTML = `<div class="list-empty">${esc(S.listError)}<br><button class="outline" data-action="settings">설정 열기</button></div>`;
    return;
  }
  const q = S.search.trim().toLowerCase();
  const byId = Object.fromEntries(S.projects.map((p) => [p.id, p]));
  const roots = S.projects.filter((p) => !p.copy_of || !byId[p.copy_of]);
  const children = (id) => S.projects.filter((p) => p.copy_of === id);
  const match = (p) => !q || p.name.toLowerCase().includes(q);
  let html = "", shown = 0;
  for (const p of roots) {
    const kids = children(p.id);
    if (!match(p) && !kids.some(match)) continue;
    shown++;
    html += `<div class="group">${item(p, false, kids)}${kids.map((k) => item(k, true, [])).join("")}</div>`;
  }
  $("#listHead").innerHTML = `<span>프로젝트 ${shown}</span><span>${S.projects.length - roots.length ? `사본 ${S.projects.length - roots.length}` : ""}</span>`;
  box.innerHTML = html || `<div class="list-empty">${q ? "검색 결과가 없습니다." : "CapCut 프로젝트가 없습니다."}</div>`;
}

function item(p, child, kids) {
  const sel = p.id === S.selected ? "sel" : "";
  if (child) {
    return `<div class="proj child ${sel}" data-id="${esc(p.id)}">
      <img class="thumb" loading="lazy" src="${cover(p)}" alt="">
      <div class="body"><div class="name">${esc(p.name)}</div></div>
      <span class="badge">${esc(p.lang?.toUpperCase())}</span></div>`;
  }
  const langs = [...new Set(kids.map((k) => k.lang?.toUpperCase()))];
  return `<div class="proj ${sel}" data-id="${esc(p.id)}">
    <img class="thumb" loading="lazy" src="${cover(p)}" alt="">
    <div class="body"><div class="name">${esc(p.name)}</div>
      <div class="meta">${fmtDate(p.modified)} · ${fmtDur(p.duration)}</div>
      ${langs.length ? `<div class="langs">${langs.map((l) => `<span class="badge">${esc(l)}</span>`).join("")}</div>` : ""}
    </div></div>`;
}

// ─── 상세 ─────────────────────────────────────────────────────────────────
async function select(id) {
  if (S.selected !== id) { S.selected = id; S.texts = null; S.onlyMissing = false; }
  renderList(); renderDetail();
  $("#detail").scrollTop = 0;
  try {
    S.texts = await api(`projects/${encodeURIComponent(id)}/texts`);
  } catch (e) { toast(e.message, true); }
  if (S.selected === id) renderDetail();
}

function current() { return S.projects.find((p) => p.id === S.selected); }

function copyName(p, lang) {
  const pattern = $("#pattern")?.value || S.state.name_pattern;
  return pattern.replaceAll("{name}", p.name).replaceAll("{lang}", lang.toUpperCase());
}

function renderDetail() {
  const d = $("#detail");
  if (!S.state) return;
  const p = current();
  const keepScroll = d.scrollTop;
  if (!p) d.innerHTML = welcome();
  else if (p.copy_of && S.projects.some((x) => x.id === p.copy_of)) d.innerHTML = copyView(p);
  else d.innerHTML = sourceView(p);
  d.scrollTop = keepScroll;
  renderActionbar();
}

function welcome() {
  const steps = [
    ["CapCut 을 닫습니다", "켜 둔 채 만들면 CapCut 이 종료할 때 목록에서 사라집니다."],
    ["왼쪽에서 프로젝트를 고릅니다", "원본은 건드리지 않고, 폴더를 통째로 복제합니다."],
    ["만들 언어를 고르고 번역을 확인합니다", "고친 문장은 저장돼 복제에 그대로 쓰입니다."],
    ["«복제 만들기» 를 누릅니다", "CapCut 을 켜면 «원래이름 [EN]» 같은 프로젝트가 보입니다."],
  ];
  return `<div class="welcome">${LOGO}
    <h2>CapCut 프로젝트를 다른 언어로</h2>
    <p>화면 글자와 자동 자막을 번역한 사본을 만듭니다.</p>
    <div class="card-s howto"><ol>${steps.map(([b, d], i) =>
      `<li><span class="num">${i + 1}</span><div><b>${b}</b><span class="d">${d}</span></div></li>`).join("")}</ol></div>
  </div>`;
}

function hero(p, kicker, actions) {
  const t = S.texts;
  const stats = t ? [
    [t.text_count, "화면 글자"],
    [t.texts.length, "번역할 문장"],
    ...(t.subtitle_count ? [[t.subtitle_count, "자동 자막"]] : []),
  ] : null;
  return `<div class="hero">
    <img class="cover" src="${cover(p)}" alt="">
    <div class="info">
      <div class="kicker">${kicker}</div>
      <h2>${esc(p.name)}</h2>
      <div class="stats">${stats ? stats.map(([n, l]) => `<div class="stat"><b>${n}</b><span>${l}</span></div>`).join("")
        : `<div class="stat"><b>…</b><span>읽는 중</span></div>`}</div>
      <div class="row">${actions}</div>
    </div></div>
    ${t?.tts_count && !p.copy_of && !ttsOn() ? `<div class="notice warn">${ICON.alert}<div>글자 읽어주기(TTS) 음성 <b>${t.tts_count}개</b>는 번역되지 않고 원래 언어 음성으로 남습니다. 아래 «④ 음성»에서 Typecast 로 바꿀 수 있습니다.</div></div>` : ""}`;
}

function sourceView(p) {
  const t = S.texts;
  const copies = S.projects.filter((x) => x.copy_of === p.id);
  const langs = chosenLangs();
  const have = new Set(copies.map((c) => c.lang));
  return `<div class="inner">
    ${hero(p, `<span>${fmtDate(p.modified)}</span><span>·</span><span>${fmtDur(p.duration)}</span>`,
      `<button class="outline" data-open="${esc(p.id)}">${ICON.folder}폴더 열기</button>`)}

    <div class="card-s step">
      <div class="step-head"><span class="num">1</span><h3>만들 언어</h3>
        <span class="sub">${langs.length ? `${langs.length}개 선택됨` : "하나 이상 고르세요"}</span>
        <div class="spacer"></div>
        ${langs.length ? `<button class="ghost small" data-action="clearLangs">모두 해제</button>` : ""}
      </div>
      <div class="chips">${targetLangs().map((l) =>
        `<button class="chip ${S.langs.has(l.code) ? "on" : ""}" data-lang="${l.code}">
          <span class="box">${ICON.check}</span>${esc(l.label)}<span class="code">${l.code.toUpperCase()}</span></button>`).join("")}
      </div>
    </div>

    <div class="card-s step">
      <div class="step-head"><span class="num">2</span><h3>사본 이름</h3><span class="sub">{name} = 원래 이름, {lang} = 언어 코드</span></div>
      <input id="pattern" value="${esc(S.state.name_pattern)}">
      <div class="names">${namesHtml(p, langs, have)}</div>
    </div>

    <div class="card-s step">
      <div class="step-head"><span class="num">3</span><h3>번역 확인·수정</h3>
        <span class="sub">선택 단계 — 고친 문장은 저장돼 복제에 그대로 쓰입니다</span></div>
      ${t && t.texts.length ? `<div class="row">
        <div class="progress">${langs.map((l) => progressChip(t, l)).join("")}</div>
        <div class="spacer"></div>
        <label class="toggle"><input type="checkbox" id="onlyMissing" ${S.onlyMissing ? "checked" : ""}>번역 안 된 것만</label>
        <button class="outline" id="btnPreview" ${!langs.length || S.state.engine === "none" ? "disabled" : ""}>${ICON.sparkle}번역 미리보기</button>
      </div>` : ""}
      ${t ? table(t, langs) : `<div class="empty-row">텍스트 읽는 중…</div>`}
    </div>

    ${t?.tts_count ? ttsStep(t, langs) : ""}

    ${fontStep(p, langs)}

    ${copies.length ? `<div class="card-s step">
      <div class="step-head"><h3>이 프로젝트의 사본</h3><span class="sub">${copies.length}개 · 이 앱이 만든 사본만 지울 수 있습니다</span></div>
      <div class="copies">${copies.map((c) => `<div class="copy">
        <span class="badge">${esc(c.lang?.toUpperCase())}</span>
        <span class="name">${esc(c.name)}</span>
        <span class="when">${fmtDate(c.modified)}</span>
        <button class="ghost" data-id="${esc(c.id)}">보기</button>
        <button class="ghost" data-open="${esc(c.id)}" title="폴더 열기">${ICON.folder}</button>
        <button class="ghost danger" data-delete="${esc(c.id)}" title="삭제">${ICON.trash}</button></div>`).join("")}
      </div></div>` : ""}
  </div>
  <div id="actionbar" class="actionbar"></div>`;
}

function namesHtml(p, langs, have) {
  if (!langs.length) return `<div class="muted small">언어를 고르면 만들어질 이름이 여기 보입니다.</div>`;
  return langs.map((l) => `<div class="nm"><span class="badge">${l.toUpperCase()}</span>
    <span class="t">${esc(copyName(p, l))}</span>
    ${have.has(l) ? `<span class="dup">이미 있음 — 하나 더 만듭니다</span>` : ""}</div>`).join("");
}

function progressChip(t, l) {
  const n = t.texts.length, done = t.texts.filter((s) => t.translations?.[l]?.[s]).length;
  const c = 2 * Math.PI * 8, off = c * (1 - done / Math.max(1, n));
  return `<span class="prog ${done === n ? "full" : ""}"><svg class="ring" viewBox="0 0 22 22">
    <circle class="bg" cx="11" cy="11" r="8"/><circle class="fg" cx="11" cy="11" r="8" stroke-dasharray="${c}" stroke-dashoffset="${off}"/></svg>
    ${esc(langLabel(l))} <b>${done}/${n}</b></span>`;
}

function table(t, langs) {
  if (!t.texts.length) return `<div class="empty-row">번역할 텍스트가 없습니다.</div>`;
  if (!langs.length) return `<div class="empty-row">위에서 언어를 고르면 번역 표가 나옵니다.</div>`;
  const missing = (src) => langs.some((l) => !t.translations?.[l]?.[src]);
  const rows = t.texts.map((src, i) => [src, i]).filter(([src]) => !S.onlyMissing || missing(src));
  if (!rows.length) return `<div class="empty-row">모두 번역됐습니다.</div>`;
  const head = `<tr><th></th><th>원문</th>${langs.map((l) => `<th>${esc(langLabel(l))}</th>`).join("")}</tr>`;
  const narr = Object.fromEntries((t.narration || []).map((n) => [n.text, n]));
  const body = rows.map(([src, i]) => {
    const n = narr[src];
    const row = `<tr class="${n ? "narr" : ""}"><td class="idx">${i + 1}</td><td class="src">${n
      ? `<span class="badge">내레이션 · ${(n.start / 1e6).toFixed(1)}초</span><br>` : ""}${esc(src)}</td>${langs.map((l) => {
      const v = t.translations?.[l]?.[src];
      return `<td class="cell"><textarea rows="${Math.max(1, src.split("\n").length)}" data-i="${i}" data-l="${l}"
        class="${v ? "" : "missing"}" placeholder="번역 전 — 직접 쓰거나 미리보기">${esc(v || "")}</textarea></td>`;
    }).join("")}</tr>`;
    if (!n) return row;
    // 내레이션 문장 아래: 화면 자막 조각에 실제로 들어갈 글자(문장 번역을 나눈 것 — 문장을 고치면 다시 나눔)
    return row + n.parts.map((part, k) => `<tr class="piece"><td></td><td class="src">↳ ${esc(part)}</td>${langs.map((l) => {
      const pcs = n.pieces?.[l];
      return `<td class="cell piece-cell">${pcs ? esc(pcs[k] ?? "")
        : `<span class="muted small">${t.translations?.[l]?.[src] ? "번역 미리보기를 누르면 나눠집니다" : "문장을 먼저 번역하세요"}</span>`}</td>`;
    }).join("")}</tr>`).join("");
  }).join("");
  return `<div class="table-wrap"><table>${head}${body}</table></div>`;
}

function copyView(p) {
  const src = S.projects.find((x) => x.id === p.copy_of);
  const t = S.texts;
  return `<div class="inner">
    ${hero(p, `<span class="badge">${esc(p.lang?.toUpperCase())}</span><span>${esc(langLabel(p.lang))} 사본</span><span>·</span><span>${fmtDate(p.modified)}</span>`,
      `<button class="outline" data-id="${esc(src.id)}">${ICON.back}원본 보기</button>
       <button class="outline" data-open="${esc(p.id)}">${ICON.folder}폴더 열기</button>
       <button class="outline danger" data-delete="${esc(p.id)}">${ICON.trash}사본 삭제</button>`)}
    <div class="notice info">${ICON.info}<div>이 프로젝트는 «${esc(src.name)}» 를 ${esc(langLabel(p.lang))}로 복제한 사본입니다. 다른 언어가 필요하면 <button class="link" data-id="${esc(src.id)}">원본</button>에서 만드세요.</div></div>
    <div class="card-s step">
      <div class="step-head"><h3>사본의 화면 글자</h3><span class="sub">번역을 고치려면 원본에서 고친 뒤 이 사본을 지우고 다시 만드세요</span></div>
      ${t ? (t.texts.length ? `<div class="textlist">${t.texts.map((s, i) => `<div class="tl"><span class="i">${i + 1}</span><span>${esc(s)}</span></div>`).join("")}</div>`
        : `<div class="empty-row">글자가 없습니다.</div>`) : `<div class="empty-row">텍스트 읽는 중…</div>`}
    </div>
  </div>`;
}

// ─── 음성(TTS) ────────────────────────────────────────────────────────────
const ttsOn = () => S.withTts && S.state?.has_typecast;

// ─── 글꼴 ─────────────────────────────────────────────────────────────────
// 한국어 전용 글꼴에는 일본어 글자가 없다 → 원본 글꼴마다 그 언어에서 쓸 글꼴·크기 배율을 고른다.
const FONT_SAMPLE = { ja: "今日の唇 かわいすぎ？" };
S.fonts = {}; // lang → /api/projects/:id/fonts/:lang

function fontStep(p, langs) {
  const lang = langs.find((l) => FONT_SAMPLE[l]);
  if (!lang) return "";
  const f = S.fonts[lang];
  if (!f || f.project !== p.id) { loadFonts(p.id, lang); return ""; }
  const faces = f.choices.filter((c) => c.ready)
    .map((c) => `@font-face{font-family:"cl-${c.file}";src:url("/font-file/${lang}/${encodeURIComponent(c.file)}")}`).join("");
  return `<style>${faces}</style><div class="card-s step">
    <div class="step-head"><span class="num">5</span><h3>글꼴 · ${esc(langLabel(lang))}</h3>
      <span class="sub">원본 글꼴에 ${esc(langLabel(lang))} 글자가 없어 바꿔 넣습니다 — 고른 짝은 다른 영상에도 씁니다</span>
      <div class="spacer"></div>
      <label class="toggle" title="번역이 길어 원문보다 넓어지면 제목·글자 크기를 그만큼 줄입니다(최소 70%, 자막 조각은 제외)">
        <input type="checkbox" id="autoFit" ${f.auto_fit ? "checked" : ""}>길면 크기 자동 줄이기</label>
    </div>
    <div class="fonts">${f.fonts.map((x) => {
      const cur = x.map?.font || "", scale = x.map?.scale ?? 1;
      const ready = f.choices.find((c) => c.file === cur)?.ready;
      const sample = esc(S.texts?.translations?.[lang]?.[x.sample] || FONT_SAMPLE[lang]);
      return `<div class="fontrow">
        <div class="vmeta"><b>${esc(x.title || "이름 없는 글꼴")}</b>
          <span class="muted small">${x.count}곳 · 크기 ${x.sizes.join(", ")} · «${esc(x.sample)}»</span></div>
        <select data-fontkey="${esc(x.key)}" data-flang="${lang}">
          <option value="">— 바꾸지 않음 —</option>
          ${f.choices.map((c) => `<option value="${esc(c.file)}" ${c.file === cur ? "selected" : ""}>${esc(c.name)}</option>`).join("")}
        </select>
        <label class="scale">크기 <input type="number" min="0.5" max="1.5" step="0.05" value="${scale}" data-fontscale="${esc(x.key)}"> 배</label>
        <div class="fontprev" style="font-family:'cl-${esc(cur)}',sans-serif;font-size:${Math.round(22 * scale)}px">${cur ? (ready ? sample : `<span class="muted small">복제할 때 글꼴을 내려받습니다</span>`) : `<span class="muted small">원래 글꼴 그대로</span>`}</div>
      </div>`;
    }).join("")}</div>
  </div>`;
}

async function loadFonts(id, lang) {
  if (loadFonts.busy) return;
  loadFonts.busy = true;
  try { S.fonts[lang] = { ...(await api(`projects/${encodeURIComponent(id)}/fonts/${lang}`)), project: id }; }
  catch (e) { toast(e.message, true); }
  loadFonts.busy = false;
  renderDetail();
}

async function saveFont(key, lang) {
  const row = document.querySelector(`[data-fontkey="${CSS.escape(key)}"]`).closest(".fontrow");
  const font = row.querySelector("select").value;
  const scale = parseFloat(row.querySelector("[data-fontscale]").value) || 1;
  try {
    await api("font", { lang, key, font, scale });
    S.fonts[lang] = null;
    loadFonts(S.selected, lang);
  } catch (e) { toast(e.message, true); }
}

function ttsStep(t, langs) {
  if (!S.state.has_typecast) {
    return `<div class="card-s step">
      <div class="step-head"><span class="num">4</span><h3>음성 바꾸기</h3><span class="sub">바꿀 수 있는 음성 ${t.tts_count}개</span></div>
      <div class="notice info">${ICON.info}<div>Typecast API 키를 넣으면 번역문으로 음성을 새로 만들어 사본의 음성을 바꿉니다.
        <button class="link" data-action="settings">설정 열기</button></div></div></div>`;
  }
  if (S.withTts && !S.voices && !S.voicesError) loadVoices();
  const lang = langs[0];
  return `<div class="card-s step">
    <div class="step-head"><span class="num">4</span><h3>음성 바꾸기</h3>
      <span class="sub">CapCut 목소리마다 Typecast 목소리를 정하면 다음부터 기억합니다</span>
      <div class="spacer"></div>
      <label class="toggle"><input type="checkbox" id="withTts" ${S.withTts ? "checked" : ""}>음성도 번역 언어로 바꾸기</label>
    </div>
    ${S.withTts ? `${S.voicesError ? `<div class="notice warn">${ICON.alert}<div>${esc(S.voicesError)}</div></div>` : ""}
    <div class="voices">${t.tts.map((it) => {
      const tr = lang && S.texts.translations?.[lang]?.[it.text];
      return `<div class="voice">
        <div class="vmeta"><b>${it.kind === "narration" ? `내레이션 · ${esc(it.tone)} · ${(it.start / 1e6).toFixed(1)}초부터` : esc(it.tone || "이름 없는 목소리")}</b><span class="muted small">${(it.duration / 1e6).toFixed(1)}초 · ${esc((it.text || "연결된 글자 없음").replace(/\n/g, " "))}</span></div>
        <select data-tone="${esc(it.tone)}">${voiceOptions(it.voice)}</select>
        <button class="outline" data-preview="${esc(it.id)}" ${!it.voice || !tr ? "disabled" : ""}
          title="${!tr ? "먼저 이 문장을 번역하세요" : `${esc(langLabel(lang))} 번역문으로 들어 보기`}">▶ 들어 보기</button>
      </div>`;
    }).join("")}</div>
    <div class="muted small">번역 음성이 원래보다 길면 재생 속도를 조금(최대 1.15배) 올리고, 그래도 넘치면 그 자리에서 영상을 늘립니다. 만든 음성은 저장해 두고 다시 쓰므로 같은 문장은 크레딧이 다시 들지 않습니다.</div>` : ""}
  </div>`;
}

function voiceOptions(selected) {
  if (!S.voices) return `<option value="${esc(selected)}">${selected ? esc(selected) : "목소리 불러오는 중…"}</option>`;
  const label = { male: "남성", female: "여성" };
  const groups = {};
  for (const v of S.voices) (groups[label[v.gender] || "기타"] ||= []).push(v);
  return `<option value="">— 바꾸지 않음 —</option>` + Object.entries(groups).map(([g, vs]) =>
    `<optgroup label="${g}">${vs.map((v) => `<option value="${esc(v.id)}" ${v.id === selected ? "selected" : ""}>${esc(v.name)}${v.age ? ` · ${esc(v.age)}` : ""}</option>`).join("")}</optgroup>`).join("");
}

async function loadVoices() {
  if (loadVoices.busy) return;
  loadVoices.busy = true;
  try { S.voices = (await api("tts/voices")).voices; }
  catch (e) { S.voicesError = e.message; }
  loadVoices.busy = false;
  renderDetail();
}

async function previewVoice(id) {
  const it = S.texts.tts.find((x) => x.id === id);
  const lang = chosenLangs()[0];
  const text = S.texts.translations?.[lang]?.[it.text];
  const btn = document.querySelector(`[data-preview="${CSS.escape(id)}"]`);
  btn.disabled = true; btn.textContent = "만드는 중…";
  try {
    const r = await api("tts/preview", { text, voice: it.voice, lang });
    new Audio(r.url).play();
    toast(`${langLabel(lang)} 음성 ${r.duration.toFixed(1)}초 (원래 ${(it.duration / 1e6).toFixed(1)}초)`);
  } catch (e) { toast(e.message, true); }
  btn.disabled = false; btn.textContent = "▶ 들어 보기";
}

// ─── 하단 실행 바 ─────────────────────────────────────────────────────────
function renderActionbar() {
  const bar = $("#actionbar");
  if (!bar) return;
  const p = current();
  const n = chosenLangs().length;
  const running = S.state.capcut_running;
  const noEngine = S.state.engine === "none";
  let msg, warn = false;
  if (running) { msg = `${ICON.alert}<span>CapCut 이 켜져 있습니다. 닫은 뒤 만드세요 — 켜진 채 만들면 CapCut 종료 때 목록에서 사라집니다.</span>`; warn = true; }
  else if (noEngine) { msg = `${ICON.alert}<span>번역 엔진이 없습니다. 설정에서 OpenAI API 키를 넣거나 codex CLI 에 로그인하세요.</span>`; warn = true; }
  else if (!n) msg = "<span>만들 언어를 고르세요.</span>";
  else msg = `<span>원본은 그대로 두고 <b>${n}개</b>의 새 프로젝트를 만듭니다. 번역 안 된 문장은 자동으로 번역합니다.${ttsOn() && S.texts?.tts_count ? " 음성도 Typecast 로 바꿉니다." : ""}</span>`;
  bar.innerHTML = `<div class="wrap"><div class="msg ${warn ? "warn" : ""}">${msg}</div>
    <button id="btnCreate" class="primary big" ${!p || !n || running || noEngine ? "disabled" : ""}>${ICON.copy}${n ? `${n}개 언어로 ` : ""}복제 만들기</button></div>`;
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
      $("#jobElapsed").textContent = `${Math.round(Date.now() / 1000 - j.started)}초`;
      if (j.state === "done") return j.result;
      if (j.state === "failed") throw new Error(j.error);
      await new Promise((r) => setTimeout(r, document.hidden ? 3000 : 700));
    }
  } finally { m.hidden = true; }
}

async function reloadTexts(id) {
  S.texts = await api(`projects/${encodeURIComponent(id)}/texts`);
  renderDetail();
}

async function preview() {
  const p = current();
  try {
    const { job } = await api("translate", { id: p.id, langs: chosenLangs() });
    await runJob(job);
    await reloadTexts(p.id);
    toast("번역을 불러왔습니다. 칸을 눌러 고칠 수 있습니다.");
  } catch (e) { toast(e.message, true); }
}

async function create() {
  const p = current();
  try {
    const { job } = await api("copies", { id: p.id, langs: chosenLangs(), pattern: $("#pattern").value, tts: ttsOn() && !!S.texts?.tts_count });
    const res = await runJob(job);
    await loadProjects();
    await reloadTexts(p.id);
    const notes = res.copies.flatMap((c) => c.notes || []);
    const voices = res.copies.reduce((a, c) => a + (c.voices || 0), 0);
    toast(`${res.copies.length}개 만들었습니다${voices ? ` (음성 ${voices}개 교체)` : ""}. CapCut 을 켜면 목록에 보입니다.`
      + (notes.length ? "\n⚠ " + [...new Set(notes)].join("\n⚠ ") : ""), notes.length > 0);
  } catch (e) { toast(e.message, true); await loadState(); }
}

async function openFolder(id) {
  try { await api("open", id ? { id } : {}); }
  catch (e) { toast(e.message, true); }
}

function openSettings() {
  const f = $("#settingsForm");
  f.draft_root.value = S.state.root || "";
  f.openai_api_key.value = "";
  f.openai_api_key.placeholder = S.state.has_key ? "저장됨 — 바꾸려면 새 키 입력" : "sk-…";
  f.openai_model.value = S.state.openai_model;
  f.name_pattern.value = S.state.name_pattern;
  f.typecast_api_key.value = "";
  f.typecast_api_key.placeholder = S.state.has_typecast ? "저장됨 — 바꾸려면 새 키 입력" : "Typecast 개발자 콘솔에서 발급";
  f.typecast_model.value = S.state.typecast_model;
  f.codex_token.value = "";
  f.codex_token.placeholder = S.state.has_codex_token ? "저장됨 — 바꾸려면 새 토큰 입력" : "codex 액세스 토큰";
  f.codex_model.value = S.state.codex_model;
  f.codex_effort.value = S.state.codex_effort;
  $("#codexHint").textContent = "codex 로그인 상태 확인 중…";
  api("codex").then((c) => {
    $("#codexHint").textContent = !c.installed ? "codex CLI 가 없습니다 — npm install -g @openai/codex"
      : `지금: ${c.status}. 저장한 토큰은 로그인이 풀리면 번역할 때 자동으로 다시 씁니다.`;
  }).catch(() => { $("#codexHint").textContent = "codex 상태를 확인하지 못했습니다."; });
  f.pearl_server.value = S.state.pearl_server;
  $("#pearlHint").textContent = "확인 중…";
  $("#pearlLogin").hidden = false; $("#pearlLogout").hidden = true;
  api("pearl").then((p) => {
    $("#pearlHint").textContent = p.logged_in ? `${p.user.username} (${p.user.role}) 로 로그인됨`
      : p.expired ? "로그인이 만료됐습니다. 다시 로그인하세요." : "로그인하지 않음 — 이 PC 엔진으로 번역합니다.";
    $("#pearlLogin").textContent = p.logged_in ? "다시 로그인" : "로그인";
    $("#pearlLogout").hidden = !S.state.pearl_user;
  }).catch(() => { $("#pearlHint").textContent = "Pearl Studio 서버에 연결하지 못했습니다."; });
  $("#rootHint").textContent = "자동으로 찾는 곳: " + S.state.candidates.join("  ·  ");
  $("#settingsModal").hidden = false;
  f.draft_root.focus();
}

// ─── 이벤트 ───────────────────────────────────────────────────────────────
document.addEventListener("click", async (e) => {
  if (e.target.classList.contains("modal") && e.target.id === "settingsModal") { e.target.hidden = true; return; }
  const el = e.target.closest("[data-id],[data-lang],[data-open],[data-delete],[data-action],[data-preview],#btnPreview,#btnCreate,[data-close]");
  if (!el) return;
  if (el.dataset.close !== undefined) { el.closest(".modal").hidden = true; return; }
  if (el.id === "btnPreview") return preview();
  if (el.id === "btnCreate") return create();
  if (el.dataset.action === "settings") return openSettings();
  if (el.dataset.action === "clearLangs") { S.langs.clear(); localStorageSet("langs", "[]"); return renderDetail(); }
  if (el.dataset.lang) {
    S.langs.has(el.dataset.lang) ? S.langs.delete(el.dataset.lang) : S.langs.add(el.dataset.lang);
    localStorageSet("langs", JSON.stringify([...S.langs]));
    return renderDetail();
  }
  if (el.dataset.open) return openFolder(el.dataset.open);
  if (el.dataset.preview) return previewVoice(el.dataset.preview);
  if (el.dataset.delete) {
    const c = S.projects.find((x) => x.id === el.dataset.delete);
    if (!confirm(`«${c.name}» 사본을 지울까요?\n폴더째 삭제되고 되돌릴 수 없습니다.`)) return;
    try {
      await api("delete", { id: c.id });
      if (S.selected === c.id) { S.selected = c.copy_of; S.texts = null; }
      await loadProjects();
      if (S.selected) await select(S.selected); else renderDetail();
      toast("삭제했습니다.");
    } catch (er) { toast(er.message, true); }
    return;
  }
  if (el.dataset.id) return select(el.dataset.id);
});

document.addEventListener("input", (e) => {
  if (e.target.id === "pattern") {
    const p = current();
    const have = new Set(S.projects.filter((x) => x.copy_of === p.id).map((c) => c.lang));
    $(".names").innerHTML = namesHtml(p, chosenLangs(), have);
  }
  if (e.target.id === "search") { S.search = e.target.value; renderList(); }
});

document.addEventListener("change", async (e) => {
  if (e.target.id === "onlyMissing") { S.onlyMissing = e.target.checked; return renderDetail(); }
  if (e.target.dataset.fontkey !== undefined) return saveFont(e.target.dataset.fontkey, e.target.dataset.flang);
  if (e.target.dataset.fontscale !== undefined) {
    return saveFont(e.target.dataset.fontscale, e.target.closest(".fontrow").querySelector("select").dataset.flang);
  }
  if (e.target.id === "autoFit") {
    try { await api("settings", { auto_fit: e.target.checked }); Object.values(S.fonts).forEach((f) => f && (f.auto_fit = e.target.checked)); }
    catch (er) { toast(er.message, true); }
    return;
  }
  if (e.target.id === "withTts") {
    S.withTts = e.target.checked; localStorageSet("tts", S.withTts ? "1" : "0");
    return renderDetail();
  }
  if (e.target.dataset.tone !== undefined) {
    const tone = e.target.dataset.tone, voice = e.target.value;
    try {
      await api("tts/voice", { tone, voice });
      S.texts.tts.forEach((it) => { if (it.tone === tone) it.voice = voice; });
      renderDetail();
    } catch (er) { toast(er.message, true); }
    return;
  }
  const ta = e.target;
  if (ta.tagName !== "TEXTAREA" || ta.dataset.l === undefined) return;
  const src = S.texts.texts[+ta.dataset.i], lang = ta.dataset.l, dst = ta.value;
  if (!dst.trim()) return;
  try {
    await api("translation", { lang, src, dst });
    ((S.texts.translations[lang] ||= {}))[src] = dst;
    if ((S.texts.narration || []).some((n) => n.text === src)) {  // 내레이션 문장 → 화면 자막 조각도 다시 나눔
      toast("자막 조각을 문장에 맞춰 다시 나누는 중…");
      await api("split", { id: S.selected, lang });
      await reloadTexts(S.selected);
      toast("자막 조각을 다시 나눴습니다.");
      return;
    }
    ta.classList.remove("missing"); ta.classList.add("saved");
    setTimeout(() => ta.classList.remove("saved"), 1200);
    document.querySelector(".progress").innerHTML = chosenLangs().map((l) => progressChip(S.texts, l)).join("");
  } catch (er) { toast(er.message, true); }
});

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") $("#settingsModal").hidden = true;
});

$("#btnRefresh").onclick = async () => {
  await loadState(); await loadProjects();
  if (S.selected) select(S.selected);
  toast("새로 불러왔습니다.");
};
$("#btnOpenRoot").onclick = () => openFolder();
$("#btnSettings").onclick = openSettings;
$("#settingsForm").onsubmit = async (e) => {
  e.preventDefault();
  const f = e.target;
  const body = { draft_root: f.draft_root.value, openai_model: f.openai_model.value, name_pattern: f.name_pattern.value,
    typecast_model: f.typecast_model.value, pearl_server: f.pearl_server.value, codex_model: f.codex_model.value, codex_effort: f.codex_effort.value };
  if (f.codex_token.value.trim()) body.codex_token = f.codex_token.value;
  if (f.typecast_api_key.value.trim()) body.typecast_api_key = f.typecast_api_key.value;
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

$("#pearlLogin").onclick = () => { location.href = "/auth/login"; };
$("#pearlLogout").onclick = async () => {
  try { await api("pearl/logout", {}); await loadState(); openSettings(); toast("로그아웃했습니다."); }
  catch (er) { toast(er.message, true); }
};

(async () => {
  const q = new URLSearchParams(location.search);  // Pearl Studio 로그인에서 돌아온 경우
  if (q.has("login") || q.has("login_error")) {
    history.replaceState(null, "", "/");
    if (q.get("login") === "ok") toast("Pearl Studio 에 로그인했습니다. 이제 번역은 서버가 합니다.");
    else toast("로그인 실패: " + q.get("login_error"), true);
  }
  try { await loadState(); await loadProjects(); renderDetail(); }
  catch (e) { toast("서버에 연결하지 못했습니다: " + e.message, true); }
})();
