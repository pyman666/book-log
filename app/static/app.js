// book-log 前端：仪表盘 / 书单 / 详情，hash 路由，无框架无构建
const $ = s => document.querySelector(s);
const view = $("#view");
let charts = [];

const cssVar = n => getComputedStyle(document.body).getPropertyValue(n).trim();
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

function baseChart(el) {
  const c = echarts.init(el);
  charts.push(c);
  c.setOption({
    backgroundColor: "transparent",
    textStyle: { color: cssVar("--text-secondary"),
      fontFamily: "system-ui, -apple-system, 'Segoe UI', sans-serif" },
    grid: { left: 8, right: 24, top: 16, bottom: 8, containLabel: true },
    tooltip: {},
    xAxis: { axisLine: { lineStyle: { color: cssVar("--axis") } },
      axisLabel: { color: cssVar("--muted") }, splitLine: { show: false } },
    yAxis: { axisLine: { show: false }, axisLabel: { color: cssVar("--muted") },
      splitLine: { lineStyle: { color: cssVar("--grid") } } },
  });
  return c;
}

// ---------- 仪表盘 ----------
async function dashboard() {
  charts.forEach(c => c.dispose()); charts = [];
  view.innerHTML = `
    <div class="cards" id="cards"></div>
    <div class="grid2">
      <section class="panel"><h2>分类目净花费（元，红=亏 蓝=赚）</h2><div class="chart" id="ch-cat"></div></section>
      <section class="panel"><h2>年度读书量</h2><div class="chart" id="ch-year"></div></section>
      <section class="panel"><h2>作者分布（Top 10）</h2><div class="chart" id="ch-author"></div></section>
      <section class="panel"><h2>出版社分布（Top 10）</h2><div class="chart" id="ch-publisher"></div></section>
    </div>`;
  const [s, cat, year, author, publisher] = await Promise.all([
    api("/api/stats/summary"),
    api("/api/stats/group?by=category&agg=sum_price"),
    api("/api/stats/group?by=year&agg=count"),
    api("/api/stats/group?by=author&agg=count"),
    api("/api/stats/group?by=publisher&agg=count"),
  ]);
  const card = (k, v, sub, cls) =>
    `<div class="card"><span class="k">${k}</span><span class="v ${cls || ""}">${v}</span>${sub ? `<span class="sub">${sub}</span>` : ""}</div>`;
  $("#cards").innerHTML =
    card("在库", s.in_lib) + card("已售", s.sold) + card("读完", s.finished, "progress=100") +
    card("净花费（元）", fmt(s.net), "正=亏 负=赚", s.net > 0 ? "bad" : s.net < 0 ? "good" : "") +
    card("其中亏损（元）", fmt(s.loss)) + card("其中净赚（元）", fmt(s.gain)) + card("有价书数", s.priced);

  // 分类目净花费：diverging 横向条形（按值升序，最大在上）
  const catData = cat.filter(x => x.value != null).sort((a, b) => a.value - b.value);
  baseChart($("#ch-cat")).setOption({
    tooltip: { trigger: "axis", valueFormatter: v => `${v} 元` },
    xAxis: { type: "value" },
    yAxis: { type: "category", data: catData.map(x => x.key),
      axisLabel: { color: cssVar("--text-secondary") } },
    series: [{ type: "bar", barMaxWidth: 16,
      data: catData.map(x => ({ value: x.value,
        itemStyle: { color: x.value >= 0 ? cssVar("--div-pos") : cssVar("--div-neg"), borderRadius: 3 } })),
      label: { show: true, position: "right", color: cssVar("--text-secondary"),
        formatter: p => p.value } }],
  });
  // 年度读书量：折线（2px 线、8px 点、hover 十字线）
  const yearData = year.filter(x => x.key !== "未知").sort((a, b) => Number(a.key) - Number(b.key));
  baseChart($("#ch-year")).setOption({
    tooltip: { trigger: "axis" },
    xAxis: { type: "category", data: yearData.map(x => x.key) },
    series: [{ type: "line", data: yearData.map(x => x.value), symbolSize: 8,
      lineStyle: { width: 2, color: cssVar("--series-1") },
      itemStyle: { color: cssVar("--series-1") } }],
  });
  // 作者分布：横向条 Top10 + 直接标数值
  const aData = [...author].sort((a, b) => b.value - a.value).slice(0, 10).reverse();
  baseChart($("#ch-author")).setOption({
    tooltip: { trigger: "axis" },
    xAxis: { type: "value" },
    yAxis: { type: "category", data: aData.map(x => x.key),
      axisLabel: { color: cssVar("--text-secondary") } },
    series: [{ type: "bar", barMaxWidth: 16, data: aData.map(x => x.value),
      itemStyle: { color: cssVar("--series-2"), borderRadius: 3 },
      label: { show: true, position: "right", color: cssVar("--text-secondary"),
        formatter: p => p.value } }],
  });
  // 出版社分布：横向条 Top10 + 直接标数值
  const pData = [...publisher].sort((a, b) => b.value - a.value).slice(0, 10).reverse();
  baseChart($("#ch-publisher")).setOption({
    tooltip: { trigger: "axis" },
    xAxis: { type: "value" },
    yAxis: { type: "category", data: pData.map(x => x.key),
      axisLabel: { color: cssVar("--text-secondary") } },
    series: [{ type: "bar", barMaxWidth: 16, data: pData.map(x => x.value),
      itemStyle: { color: cssVar("--series-5"), borderRadius: 3 },
      label: { show: true, position: "right", color: cssVar("--text-secondary"),
        formatter: p => p.value } }],
  });
}

// ---------- 书单 ----------
const filters = { q: "", category: "", author: "", publisher: "", platform: "",
                  status: "in_library", sort: "id", desc: "true", page: 1 };

async function booksView() {
  charts.forEach(c => c.dispose()); charts = [];
  const f = await api("/api/facets");
  const sel = (key, items, allLabel) => `
    <select data-f="${key}"><option value="">${allLabel}</option>
    ${items.map(v => `<option ${filters[key] === v ? "selected" : ""}>${v}</option>`).join("")}</select>`;
  view.innerHTML = `
    <div class="toolbar">
      <input id="f-q" placeholder="书名 / ISBN" value="${filters.q}">
      ${sel("category", f.categories, "全部分类")}
      ${sel("author", f.authors, "全部作者")}
      ${sel("publisher", f.publishers, "全部出版社")}
      ${sel("platform", f.platforms, "全部平台")}
      <select data-f="status"><option value="">全部状态</option>
        <option value="in_library" ${filters.status === "in_library" ? "selected" : ""}>在库</option>
        <option value="sold" ${filters.status === "sold" ? "selected" : ""}>已售</option></select>
      <select data-f="sort">
        ${["id:录入", "title:书名", "price:价格", "rating:评分", "progress:进度",
          "created:创建", "last_modified:更新"].map(s => {
          const [v, l] = s.split(":");
          return `<option value="${v}" ${filters.sort === v ? "selected" : ""}>${l}</option>`;
        }).join("")}
      </select>
      <label style="font-size:12px;color:var(--muted)"><input type="checkbox" id="f-desc"
        ${filters.desc === "true" ? "checked" : ""}> 降序</label>
      <button id="f-apply" class="primary">筛选</button>
      <button id="f-new">+ 新书</button>
    </div>
    <table id="tbl"><thead><tr>
      <th>书名</th><th>作者</th><th>分类</th><th>出版社</th><th>平台</th>
      <th>价格</th><th>进度</th><th>评分</th><th>状态</th><th>创建</th>
    </tr></thead><tbody></tbody></table>
    <div class="pager"><button id="pg-prev">上一页</button><span id="pg-info"></span>
      <button id="pg-next">下一页</button></div>
    <div id="book-form" class="panel hidden"></div>`;
  $("#f-apply").onclick = () => {
    filters.q = $("#f-q").value.trim();
    filters.desc = $("#f-desc").checked ? "true" : "false";
    view.querySelectorAll("[data-f]").forEach(el => (filters[el.dataset.f] = el.value));
    filters.page = 1;
    loadBooks();
  };
  $("#f-new").onclick = showBookForm;
  $("#pg-prev").onclick = () => { if (filters.page > 1) { filters.page--; loadBooks(); } };
  $("#pg-next").onclick = () => { filters.page++; loadBooks(); };
  await loadBooks();
}

async function loadBooks() {
  const p = new URLSearchParams();
  Object.entries(filters).forEach(([k, v]) => { if (v !== "" && v != null) p.set(k, v); });
  const data = await api(`/api/books?${p}`);
  $("#tbl tbody").innerHTML = data.items.map(b => `
    <tr data-id="${b.id}">
      <td class="title" onclick="location.hash='#/book/${b.id}'">${b.title}${b.status === "in_library" && !b.file_path ? '<span class="warn"> 无正文</span>' : ""}</td>
      <td>${(b.authors || []).join("、") || "—"}</td>
      <td>${(b.categories || []).join("、") || "—"}</td>
      <td>${(b.publishers || []).join("、") || "—"}</td>
      <td>${b.platform || "—"}</td>
      <td><input class="inline" data-field="price" value="${b.price ?? ""}" placeholder="—"></td>
      <td><input class="inline" data-field="progress" value="${b.progress ?? ""}" placeholder="—" style="width:52px"></td>
      <td><input class="inline" data-field="rating" value="${b.rating ?? ""}" placeholder="—" style="width:52px"></td>
      <td><select class="inline" data-field="status">
        <option value="in_library" ${b.status === "in_library" ? "selected" : ""}>在库</option>
        <option value="sold" ${b.status === "sold" ? "selected" : ""}>已售</option></select></td>
      <td>${yearOf(b.created)}</td>
    </tr>`).join("");
  const pages = Math.max(1, Math.ceil(data.total / data.page_size));
  $("#pg-info").textContent = `共 ${data.total} 本 · 第 ${data.page}/${pages} 页`;
  $("#pg-prev").disabled = data.page <= 1;
  $("#pg-next").disabled = data.page >= pages;
  $("#tbl tbody").querySelectorAll("input.inline").forEach(i => (i.onchange = () => inlineEdit(i)));
  $("#tbl tbody").querySelectorAll("select[data-field=status]").forEach(s => (s.onchange = () => inlineEdit(s)));
}

async function inlineEdit(el) {
  const id = el.closest("tr").dataset.id;
  const field = el.dataset.field;
  const v = field === "status" ? el.value : numOrNull(el.value);
  try {
    await api(`/api/books/${id}`, { method: "PUT", body: JSON.stringify({ [field]: v }) });
    toast("已保存");
  } catch (e) { toast(e.message, true); }
}

const BOOK_FIELDS = `
  <label>书名 *<input name="title"></label>
  <label>作者（逗号分隔）<input name="authors"></label>
  <label>出版社（逗号分隔）<input name="publishers"></label>
  <label>分类（逗号分隔）<input name="categories"></label>
  <label>平台<select name="platform"></select></label>
  <label>ISBN<input name="isbn"></label>
  <label>价格（正=亏 负=赚，空=无）<input name="price" type="number" step="0.01"></label>
  <label>进度（100读完/0未读/-1售出）<input name="progress" type="number"></label>
  <label>评分（1-10）<input name="rating" type="number" min="1" max="10"></label>
  <label>重要度（0-1）<input name="importance" type="number" step="0.1" min="0" max="1"></label>
  <label>状态<select name="status">
    <option value="in_library">在库</option><option value="sold">已售</option></select></label>
  <label>创建时间（如 April 27, 2024 11:32 AM，可空）<input name="created"></label>`;

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
    price: numOrNull(g("price")), progress: numOrNull(g("progress")), rating: numOrNull(g("rating")),
    importance: numOrNull(g("importance")), status: g("status") || "in_library",
    created: g("created") || null,
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
  charts.forEach(c => c.dispose()); charts = [];
  const b = await api(`/api/books/${id}`);
  let content = "";
  try {
    const r = await fetch(`/api/books/${id}/content`);
    if (r.ok) content = await r.text();
  } catch (e) { /* 无正文 */ }
  const obs = b.file_path
    ? `<a class="obs" href="obsidian://open?vault=Books&file=${encodeURIComponent(b.file_path)}">📖 在 Obsidian 打开</a>`
    : "";
  view.innerHTML = `
    <div class="detail">
      <section class="panel meta">
        <h2>${b.title}${obs}</h2>
        <form id="d-form">${BOOK_FIELDS}
          <div class="row"><button class="primary" type="submit">保存</button>
          <button class="danger" type="button" id="d-del">删除记录</button></div>
        </form>
      </section>
      <section class="panel"><h2>正文</h2>
        <div class="md">${content ? marked.parse(content) : "<p class='muted'>无正文文件</p>"}</div>
      </section>
    </div>`;
  const form = $("#d-form");
  const el = n => form.elements[n];
  el("title").value = b.title; el("title").disabled = true;   // 书名不可改（避免破坏关联）
  el("authors").value = (b.authors || []).join("、");
  el("publishers").value = (b.publishers || []).join("、");
  el("categories").value = (b.categories || []).join("、");
  el("platform").value = b.platform || "";
  el("isbn").value = b.isbn || "";
  el("price").value = b.price ?? "";
  el("progress").value = b.progress ?? "";
  el("rating").value = b.rating ?? "";
  el("importance").value = b.importance ?? "";
  el("status").value = b.status;
  el("created").value = b.created || "";
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
    if (!confirm("删除该书目记录？（raw/ 正文文件不受影响）")) return;
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
  else dashboard();
}

window.addEventListener("hashchange", route);
window.addEventListener("resize", () => charts.forEach(c => c.resize()));
window.addEventListener("load", () => {
  $("#btn-sync").onclick = async () => {
    try {
      const r = await api("/api/sync", { method: "POST" });
      toast(`Sync 完成：新增 ${r.created.length}，文件缺失 ${r.missing.length}` +
        (r.created.length ? `（${r.created.join("、")}）` : ""), false, true);
    } catch (e) { toast(e.message, true, true); }
  };
  $("#btn-push").onclick = async () => {
    try {
      const r = await api("/api/git/push", { method: "POST" });
      toast(r.output, !r.ok, true);
    } catch (e) { toast(e.message, true, true); }
  };
  route();
});
