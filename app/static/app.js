// book-log 前端：书单 / 详情，hash 路由，无框架无构建
const $ = s => document.querySelector(s);
const view = $("#view");

// 封面真值 = 本地文件 raw/covers/<isbn>.*（/api/covers 拉一次集合作判据）；无文件退书名卡
const coverSet = new Set();
let coversLoaded = false;
async function ensureCovers() {   // 幂等：首次加载后缓存，新抓封面后 refreshCovers() 重拉
  try { const s = await api("/api/covers"); coverSet.clear(); s.forEach(x => coverSet.add(x)); coversLoaded = true; }
  catch (e) { /* 拉不到就当没封面，退书名卡 */ }
}
async function refreshCovers() { coverSet.clear(); await ensureCovers(); }
const coverSrc = b => (b.isbn && coverSet.has(b.isbn)) ? `/cover/${b.isbn}` : "";
const fmt = (v, d = 2) => (v == null ? "—" : Number(v).toFixed(d));
const yearOf = s => ((s || "").match(/\b(19\d{2}|20\d{2})\b/) || ["—"])[0];
const splitList = s => (s || "").split(/[,，、]/).map(x => x.trim()).filter(Boolean);
const numOrNull = s => (s == null || s === "" ? null : Number(s));

async function api(path, opts = {}) {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.status === 204 ? null : r.json();
}

function toast(msg, isErr, wide) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = isErr ? "err" : "";
  t.style.display = "block";
  clearTimeout(t._timer);
  t._timer = setTimeout(() => (t.style.display = "none"), wide ? 10000 : 3500);
}


const filters = { q: "", category: "", author: "", publisher: "", platform: "",
                  nationality: "",
                  status: "in_library", sort: "created", desc: "true", page: 1 };

const MONS = "January February March April May June July August September October November December".split(" ");
const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
// Notion 串（December 3, 2023 6:15 PM）↔ <input type=date> 的 YYYY-MM-DD
const dateOf = s => {
  if (!s) return "";
  const iso = String(s).match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (iso) return iso[0];
  const m = String(s).match(/([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})/);
  const mo = m ? MONS.findIndex(x => x.toLowerCase() === m[1].toLowerCase()) + 1 : 0;
  return mo ? `${m[3]}-${String(mo).padStart(2, "0")}-${String(m[2]).padStart(2, "0")}` : "";
};
const toNotion = iso => {
  const [y, mo, d] = iso.split("-").map(Number);
  return `${MONS[mo - 1]} ${d}, ${y}`;
};
const isoDate = s => /^\d{4}-\d{1,2}-\d{1,2}$/.test(s) && !isNaN(Date.parse(s));

async function booksView() {
  const f = FACETS = await api("/api/facets");
  const sel = (key, items, allLabel) => `
    <select data-f="${key}"><option value="">${allLabel}</option>
    ${items.map(v => `<option ${String(filters[key]) === String(v) ? "selected" : ""}>${v}</option>`).join("")}</select>`;
  view.innerHTML = `
    <div class="toolbar">
      <input id="f-q" placeholder="书名 / ISBN" value="${filters.q}">
      ${sel("author", f.authors, "作者")}
      ${sel("category", f.categories, "分类")}
      ${sel("nationality", f.nationalities, "国籍")}
      ${sel("publisher", f.publishers, "出版社")}
      ${sel("platform", f.platforms, "平台")}
      <select data-f="status"><option value="">全部状态</option>
        <option value="in_library" ${filters.status === "in_library" ? "selected" : ""}>在库</option>
        <option value="sold" ${filters.status === "sold" ? "selected" : ""}>已售</option></select>
      <button id="f-apply" class="primary right">筛选</button>
      <button id="f-new" class="btn-circle" title="登记新书" aria-label="登记新书">＋</button>
    </div>
    <div class="tbl-wrap"><table id="tbl"><colgroup>
      <col style="width:19.4%"><col style="width:10.8%"><col style="width:7%"><col style="width:12%">
      <col style="width:14%"><col style="width:6.5%"><col style="width:8.7%"><col style="width:6%">
      <col style="width:6%"><col style="width:9.6%">
    </colgroup><thead><tr>
      <th class="s" data-sort="title">书名</th><th>作者</th><th>国籍</th><th>分类</th><th>出版社</th>
      <th>平台</th>
      <th class="s" data-sort="price">价格</th><th class="s" data-sort="progress">进度</th>
      <th>状态</th>
      <th class="s" data-sort="read_at">阅读</th>
    </tr></thead><tbody></tbody></table></div>
    <div class="pager"><button id="pg-prev">上一页</button><span id="pg-info"></span>
      <button id="pg-next">下一页</button></div>
    <div id="book-form" class="panel hidden"></div>`;
  const apply = () => {
    filters.q = $("#f-q").value.trim();
    delete filters.year;                    // 年份下拉已删：顺手清掉分布面板可能残留的跳转筛选
    view.querySelectorAll("[data-f]").forEach(el => (filters[el.dataset.f] = el.value));
    filters.page = 1;
    loadBooks();
  };
  $("#f-apply").onclick = apply;
  $("#f-q").addEventListener("keydown", e => { if (e.key === "Enter") apply(); });
  view.querySelectorAll("[data-f]").forEach(s => s.addEventListener("change", apply));
  $("#f-new").onclick = showBookForm;
  $("#tbl thead").addEventListener("click", e => {
    const th = e.target.closest("th.s");
    if (th) sortBy(th.dataset.sort);
  });
  const tb = $("#tbl tbody");
  tb.addEventListener("click", e => {
    if (e.target.closest("a")) return;                       // 🌐 豆瓣链接自己走
    const fill = e.target.closest(".fill");
    if (fill) return openDimEditor(fill);
    const dt = e.target.closest("input.dt");
    if (dt) { openDtPicker(dt); return; }                    // 点输入框任意处弹原生日期选择器
    const title = e.target.closest("td.title");
    if (title) location.hash = `#/book/${title.closest("tr").dataset.id}`;
  });
  // 共享的原生日期选择器（藏屏外）：showPicker 弹出，显示格式由单元格的文本控制（yyyy-mm-dd）
  const dtPicker = document.createElement("input");
  dtPicker.type = "date";
  dtPicker.className = "dt-hidden";
  dtPicker.addEventListener("change", () => {
    const cell = dtPicker._cell;
    if (!cell) return;
    cell.value = dtPicker.value;
    inlineEdit(cell);
  });
  view.appendChild(dtPicker);
  tb.addEventListener("change", e => { if (e.target.dataset.field) inlineEdit(e.target); });
  $("#pg-prev").onclick = () => { if (filters.page > 1) { filters.page--; loadBooks(); } };
  $("#pg-next").onclick = () => { filters.page++; loadBooks(); };
  await loadBooks();
}

// 点列名排序：同列翻转方向；换列给一个顺手的默认方向（时间/数字降序在前，文字升序在前）
const SORT_DESC_FIRST = new Set(["price", "progress", "rating", "read_at", "created"]);
function sortBy(col) {
  if (filters.sort === col) filters.desc = filters.desc === "true" ? "false" : "true";
  else { filters.sort = col; filters.desc = SORT_DESC_FIRST.has(col) ? "true" : "false"; }
  filters.page = 1;
  loadBooks();
}
function renderSortMarks() {
  document.querySelectorAll("#tbl th.s").forEach(th => {
    const on = th.dataset.sort === filters.sort;
    th.classList.toggle("on", on);
    th.setAttribute("aria-sort", on ? (filters.desc === "true" ? "descending" : "ascending") : "none");
    const old = th.querySelector(".arr");
    if (old) old.remove();
    if (on) th.insertAdjacentHTML("beforeend", `<span class="arr">${filters.desc === "true" ? "↓" : "↑"}</span>`);
  });
}

let FACETS = null;                     // 维度全量值：弹层候选池
const rowItems = new Map();            // id → 行数据；就地提交后回写 + 局部重绘该行

const dimBtn = (b, dim, val) =>
  `<td><button class="fill" data-id="${b.id}" data-dim="${dim}" title="点击编辑">${
    val ? esc(val) : '<span class="dull">＋ 添加</span>'}</button></td>`;

function bookRow(b) {
  return `
    <tr data-id="${b.id}">
      <td class="title">${esc(b.title)}${b.douban_id ? ` <a class="dbk" title="豆瓣" href="https://book.douban.com/subject/${b.douban_id}/" target="_blank" rel="noopener">🌐</a>` : ""}${b.status === "in_library" && !b.note_file ? '<span class="warn"> 无正文</span>' : ""}</td>
      ${dimBtn(b, "authors", (b.authors || []).join("、"))}
      <td><button class="fill" data-id="${b.id}" data-dim="nationality"
        title="按作者设置国籍（作者跨书共享，改动全局生效）">${
        (b.nationalities || []).join("、") ? esc(b.nationalities.join("、")) : '<span class="dull">＋ 添加</span>'}</button></td>
      ${dimBtn(b, "categories", (b.categories || []).join("、"))}
      ${dimBtn(b, "publishers", (b.publishers || []).join("、"))}
      ${dimBtn(b, "platform", b.platform)}
      <td><input class="inline" data-field="price" value="${b.price ?? ""}" placeholder="—" aria-label="价格"></td>
      <td><input class="inline" data-field="progress" value="${b.progress ?? ""}" placeholder="—" aria-label="进度"></td>
      <td><select class="inline st${b.status ? " has" : ""}" data-field="status" title="点击切换 在库 / 已售" aria-label="状态">
        <option value="in_library" ${b.status === "in_library" ? "selected" : ""}>在库</option>
        <option value="sold" ${b.status === "sold" ? "selected" : ""}>已售</option></select></td>
      <td><input type="text" class="inline dt${dateOf(b.read_at) ? " has" : ""}" data-field="read_at"
        value="${dateOf(b.read_at)}" aria-label="读完日期（yyyy-mm-dd，点击可选）" spellcheck="false"></td>
    </tr>`;
}

async function loadBooks() {
  const p = new URLSearchParams();
  Object.entries(filters).forEach(([k, v]) => { if (v !== "" && v != null) p.set(k, v); });
  const data = await api(`/api/books?${p}`);
  rowItems.clear();
  data.items.forEach(b => rowItems.set(b.id, b));
  $("#tbl tbody").innerHTML = data.items.map(bookRow).join("") ||
    `<tr><td colspan="11" class="dull" style="text-align:center;padding:28px">没有符合这些条件的书——换个筛选，或点右上「＋」登记新书。</td></tr>`;
  const pages = Math.max(1, Math.ceil(data.total / data.page_size));
  $("#pg-info").textContent = `共 ${data.total} 本 · 第 ${data.page}/${pages} 页`;
  $("#pg-prev").disabled = data.page <= 1;
  $("#pg-next").disabled = data.page >= pages;
  renderSortMarks();
}

function paintRow(b) {
  const tr = $(`#tbl tr[data-id="${b.id}"]`);
  if (tr) tr.outerHTML = bookRow(b);   // 事件走 tbody 委托，重绘不掉监听
}

function openDtPicker(cell) {
  const picker = document.querySelector(".dt-hidden");
  if (!picker) return;
  const s = cell.value.trim().replace(/[\/\s.]/g, "-");
  picker._cell = cell;
  picker.value = isoDate(s) ? s : "";
  // 原生弹层锚定在输入框位置——先把隐框挪到目标格子上（透明占位），弹层才不会飞出屏外
  const r = cell.getBoundingClientRect();
  Object.assign(picker.style, { left: r.left + "px", top: r.top + "px",
    width: r.width + "px", height: r.height + "px" });
  picker.addEventListener("blur", function reset() {
    Object.assign(picker.style, { left: "-9999px", top: "0", width: "1px", height: "" });
    picker.removeEventListener("blur", reset);
  });
  requestAnimationFrame(() => { try { picker.showPicker(); } catch { /* 不支持就手动键入 */ } });
}
async function inlineEdit(el) {
  const id = el.closest("tr").dataset.id;
  const field = el.dataset.field;
  let v;
  if (field === "status") v = el.value;
  else if (field === "read_at") {
    const s = el.value.trim().replace(/[\/\s.]/g, "-");      // 宽容：2024/03/05 也收，统一成 yyyy-mm-dd
    if (!s) v = null;                                        // 清空 = 没读
    else if (!isoDate(s)) { toast("日期按 yyyy-mm-dd 写，如 2024-03-05", true); return; }
    else { el.value = s; v = toNotion(s); }                  // 存库仍为 Notion 串
  }
  else v = numOrNull(el.value);
  try {
    const fresh = await api(`/api/books/${id}`, { method: "PUT", body: JSON.stringify({ [field]: v }) });
    const b = rowItems.get(+id);
    if (b) {
      Object.assign(b, { [field]: v }, { nationalities: fresh.nationalities });
      if (field === "read_at") paintRow(b);   // 日期有无值切换日历图标（.has 类）
    }
    toast("已保存");
  } catch (e) { toast(e.message, true); }
}

// ---------- 行内维度弹层：作者/分类/出版社多选（可新建），平台单选 ----------
let pop = null, popClosed = { at: 0, anchor: null };
function closePop() {
  if (!pop) return;
  const { el, anchor, outside, onScroll } = pop;
  document.removeEventListener("mousedown", outside, true);
  removeEventListener("scroll", onScroll, true);
  el.remove();
  popClosed = { at: Date.now(), anchor };
  pop = null;
}
function positionPop(el, anchor) {
  const r = anchor.getBoundingClientRect();
  el.style.left = "0px"; el.style.top = "0px";
  const w = Math.max(240, Math.min(r.width + 60, 380));
  el.style.width = w + "px";
  const h = el.offsetHeight;
  const x = Math.max(8, Math.min(r.left, innerWidth - w - 8));
  const y = r.bottom + 6 + h > innerHeight - 8 ? Math.max(8, r.top - h - 6) : r.bottom + 6;
  el.style.left = x + "px"; el.style.top = y + "px";
}
function openDimEditor(btn) {
  if (popClosed.anchor === btn && Date.now() - popClosed.at < 300) return;  // 外点关闭后紧跟的 click 不重开
  closePop();
  const b = rowItems.get(+btn.dataset.id);
  if (!b) return;
  const el = document.createElement("div");
  el.className = "pop";
  document.body.appendChild(el);
  if (btn.dataset.dim === "nationality") renderNationality(el, b);
  else if (btn.dataset.dim === "platform") renderSingle(el, b, "platform");
  else renderMulti(el, b, btn.dataset.dim);
  pop = {
    el, anchor: btn,
    outside: ev => { if (!el.contains(ev.target)) closePop(); },
    onScroll: closePop,
  };
  positionPop(el, btn);
  addEventListener("scroll", pop.onScroll, true);
  setTimeout(() => document.addEventListener("mousedown", pop.outside, true));
  el.addEventListener("keydown", e => { if (e.key === "Escape") closePop(); });
  const q = el.querySelector(".pop-q");
  if (q) q.focus();
}
function renderMulti(el, b, dim) {
  const cur = new Set(b[dim] || []);
  el.innerHTML = `<input class="pop-q" placeholder="模糊匹配 · Enter 添加新值" autocomplete="off"><div class="pop-list"></div>`;
  const q = el.querySelector(".pop-q"), list = el.querySelector(".pop-list");
  const draw = () => {
    const s = q.value.trim().toLowerCase();
    const pool = FACETS[dim] || [];
    const item = (n, on) => `<label class="pop-item"><input type="checkbox" ${on ? "checked" : ""}><span>${esc(n)}</span></label>`;
    const sel = [...cur].filter(n => !s || n.toLowerCase().includes(s));           // 已选置顶
    const rest = pool.filter(n => !cur.has(n) && (!s || n.toLowerCase().includes(s)));
    list.innerHTML = sel.map(n => item(n, true)).join("") + rest.map(n => item(n, false)).join("")
      || `<div class="pop-empty">无匹配 · 按 Enter 新建「${esc(q.value.trim())}」</div>`;
    list.querySelectorAll(".pop-item input").forEach(cb => cb.onchange = () => {
      const n = cb.parentElement.querySelector("span").textContent;
      cb.checked ? cur.add(n) : cur.delete(n);
      commitDim(b, dim, [...cur]);   // 每勾一下即落账；弹层保持打开可连续勾
      draw();
    });
  };
  q.oninput = draw;
  q.onkeydown = e => {
    if (e.key !== "Enter") return;
    const n = q.value.trim();
    if (!n) return;
    cur.add(n);
    commitDim(b, dim, [...cur]);
    q.value = "";
    draw();
  };
  draw();
}
// 国籍弹层：按作者逐个设国籍（作者行跨书共享，改一处全局生效；单作者书 = 一行下拉）
function renderNationality(el, b) {
  const aus = b.authors || [];
  if (!aus.length) {
    el.innerHTML = '<div class="pop-empty">这本书没作者——国籍跟着作者走，先去作者列补人。</div>';
    return;
  }
  const nats = FACETS.nationalities || [];
  const cur = n => (b.author_nationalities || {})[n] || "";
  el.innerHTML = aus.map(n => {
    const v = cur(n);
    const list = [""];
    nats.forEach(x => { if (x !== v) list.push(x); });
    if (v && !list.includes(v)) list.push(v);
    const opts = list.map(o => `<option value="${esc(o)}" ${o === v ? "selected" : ""}>${esc(o) || "未知"}</option>`).join("");
    return `<label class="pop-row"><span class="pop-name" title="${esc(n)}">${esc(n)}</span>` +
      `<select data-a="${esc(n)}">${opts}</select></label>`;
  }).join("");
  el.querySelectorAll("select").forEach(s => s.onchange = () => {
    const map = Object.fromEntries(aus.map(n => [n, cur(n)]));
    map[s.dataset.a] = s.value;
    commitNat(b, map);
  });
}
async function commitNat(b, map) {
  try {
    const fresh = await api(`/api/books/${b.id}/author-nationalities`,
      { method: "PUT", body: JSON.stringify({ nationalities: map }) });
    Object.assign(b, fresh);
    paintRow(b);
  } catch (e) { toast(e.message, true); }
}
function renderSingle(el, b, dim) {
  const poolKey = dim === "platform" ? "platforms" : dim;  // 字段单数，FACETS 键是复数
  const cur = b[dim];
  const opts = ["— 清空", ...(FACETS[poolKey] || []).filter(p => p !== cur)];
  el.innerHTML = `<div class="pop-list">${opts.map(o =>
    `<div class="pop-item${o === cur ? " on" : ""}"><span>${esc(o)}</span></div>`).join("")}</div>`;
  el.querySelectorAll(".pop-item").forEach(it => it.onclick = () => {
    const t = it.querySelector("span").textContent;
    commitDim(b, dim, t === "— 清空" ? null : t);
    closePop();
  });
}
async function commitDim(b, dim, value) {
  try {
    const fresh = await api(`/api/books/${b.id}`, { method: "PUT", body: JSON.stringify({ [dim]: value }) });
    Object.assign(b, { [dim]: value }, { nationalities: fresh.nationalities });  // 作者变了国籍跟着动
    paintRow(b);
  } catch (e) { toast(e.message, true); }
}

const BOOK_FIELDS = `
  <label>书名 *<input name="title"></label>
  <label>作者（逗号分隔）<input name="authors"></label>
  <label>出版社（逗号分隔）<input name="publishers"></label>
  <label>分类（逗号分隔）<input name="categories"></label>
  <label>平台<select name="platform"></select></label>
  <label>ISBN<input name="isbn"></label>
  <label>豆瓣编号（subject 号，可空）<input name="douban_id" pattern="[0-9]*" title="只填数字"></label>
  <label>价格（正=亏 负=赚，空=无）<input name="price" type="number" step="0.01"></label>
  <label>进度（100读完/0未读/-1售出）<input name="progress" type="number"></label>
  <label>评分（1-10）<input name="rating" type="number" min="1" max="10"></label>
  <label>重要度（0-1）<input name="importance" type="number" step="0.1" min="0" max="1"></label>
  <label>状态<select name="status">
    <option value="in_library">在库</option><option value="sold">已售</option></select></label>
  <label>创建时间（如 April 27, 2024 11:32 AM，可空）<input name="created"></label>
  <label>阅读时间（可空；留空则聚合时按创建时间归年）<input name="read_at"></label>`;

async function fillDimSelects(form) {
  const f = await api("/api/facets");
  form.elements.platform.innerHTML = `<option value="">—</option>` +
    f.platforms.map(v => `<option>${v}</option>`).join("");
}

function formPayload(form) {
  // 必须走 form.elements[n]：form.title / form.status 会被 form 元素自身属性遮蔽
  const g = n => form.elements[n].value.trim();
  return {
    title: g("title"), authors: splitList(g("authors")), publishers: splitList(g("publishers")),
    categories: splitList(g("categories")), platform: g("platform") || null, isbn: g("isbn") || null,
    douban_id: g("douban_id") || null,
    price: numOrNull(g("price")), progress: numOrNull(g("progress")), rating: numOrNull(g("rating")),
    importance: numOrNull(g("importance")), status: g("status") || "in_library",
    created: g("created") || null, read_at: g("read_at") || null,
  };
}

async function showBookForm() {
  const box = $("#book-form");
  box.classList.remove("hidden");
  box.innerHTML = `<h2>新书</h2><form id="n-form">${BOOK_FIELDS}
    <div class="row"><button class="primary" type="submit">保存</button>
    <button type="button" id="n-cancel">取消</button></div></form>`;
  const form = box.querySelector("#n-form");
  await fillDimSelects(form);
  $("#n-cancel").onclick = () => box.classList.add("hidden");
  form.onsubmit = async e => {
    e.preventDefault();
    const payload = formPayload(form);
    if (!payload.title) return toast("书名必填", true);
    try {
      await api("/api/books", { method: "POST", body: JSON.stringify(payload) });
      box.classList.add("hidden");
      toast("已添加");
      await loadBooks();
    } catch (err) { toast(err.message, true); }
  };
  box.scrollIntoView();
}

// ---------- 详情 ----------
async function bookDetail(id) {
  const b = await api(`/api/books/${id}`);
  let content = "";
  try {
    const r = await fetch(`/api/books/${id}/content`);
    if (r.ok) content = await r.text();
  } catch (e) { /* 无正文 */ }
  const obs = b.note_file
    ? `<a class="obs" href="obsidian://open?vault=Books&file=${encodeURIComponent("raw/books/" + b.note_file)}">📖 在 Obsidian 打开</a>`
    : "";
  const dbk = b.douban_id
    ? `<a class="obs" href="https://book.douban.com/subject/${b.douban_id}/" target="_blank" rel="noopener">🌐 豆瓣</a>`
    : "";
  if (!coversLoaded) await ensureCovers();
  const hasCover = b.isbn && coverSet.has(b.isbn);
  const coverImg = hasCover
    ? `<img class="d-cover" src="/cover/${b.isbn}" alt="${b.title} 封面">` : "";
  const coverBtn = (b.douban_id && !hasCover)
    ? `<button id="d-cover" class="ghost" type="button" title="从豆瓣拓封面并落盘">抓封面</button>` : "";
  view.innerHTML = `
    <div class="detail">
      <section class="panel meta">
        ${coverImg}
        <h2>${b.title}${dbk}${obs}${coverBtn}</h2>
        <form id="d-form">${BOOK_FIELDS}
          <div class="row"><button class="primary" type="submit">保存</button>
          <button class="danger" type="button" id="d-del">删除记录</button></div>
        </form>
      </section>
      <section class="panel"><h2>正文 <span class="muted note-src" title="文件按「书名.md / 书名（作者）.md」命名法推导，不入库">${
        b.note_file ? esc(b.note_file) : "未匹配到 raw/books/ 文件 · 请按书名命名笔记"}</span></h2>
        <div class="md">${content ? marked.parse(content) : "<p class='muted'>无正文文件</p>"}</div>
      </section>
      
    </div>`;
  if (b.douban_id && !hasCover) {
    $("#d-cover").onclick = async () => {
      const btn = $("#d-cover");
      btn.disabled = true; btn.textContent = "抓取中…";
      try {
        const r = await api(`/api/books/${id}/cover`, { method: "POST" });
        if (r.has_cover) { await refreshCovers(); bookDetail(id); }   // 落盘→重渲染显示封面
        else { btn.textContent = "豆瓣无封面"; btn.disabled = true; } // 占位图/无 isbn，人工补
      } catch (e) {
        btn.disabled = false; btn.textContent = "抓封面";
        toast(e.message, true);
      }
    };
  }
  const form = $("#d-form");
  const el = n => form.elements[n];
  el("title").value = b.title; el("title").disabled = true;   // 书名不可改（避免破坏关联）
  el("authors").value = (b.authors || []).join("、");
  el("publishers").value = (b.publishers || []).join("、");
  el("categories").value = (b.categories || []).join("、");
  el("platform").value = b.platform || "";
  el("isbn").value = b.isbn || "";
  el("douban_id").value = b.douban_id || "";
  el("price").value = b.price ?? "";
  el("progress").value = b.progress ?? "";
  el("rating").value = b.rating ?? "";
  el("importance").value = b.importance ?? "";
  el("status").value = b.status;
  el("created").value = b.created || "";
  el("read_at").value = b.read_at || "";
  await fillDimSelects(form);
  form.onsubmit = async e => {
    e.preventDefault();
    try {
      const payload = formPayload(form);
      delete payload.title;                                  // PUT 不允许改标题
      await api(`/api/books/${id}`, { method: "PUT", body: JSON.stringify(payload) });
      toast("已保存");
    } catch (err) { toast(err.message, true); }
  };
  $("#d-del").onclick = async () => {
    if (!confirm("删除该书目记录？（raw/books/ 正文文件不受影响）")) return;
    await api(`/api/books/${id}`, { method: "DELETE" });
    location.hash = "#/books";
  };
}

// ---------- 路由 & 全局按钮 ----------
function route() {
  const h = location.hash || "#/";
  const m = h.match(/^#\/book\/(\d+)/);
  if (m) bookDetail(m[1]);
  else if (h === "#/books") booksView();
  else booksView();
}

window.addEventListener("hashchange", route);
window.addEventListener("load", () => {
  $("#tagline").textContent =
    `本地读书笔记账本 · ${new Date().toLocaleDateString("zh-CN", { year: "numeric", month: "long", day: "numeric" })}`;
  route();
});
