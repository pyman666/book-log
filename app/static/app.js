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

const baseOption = () => ({
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

function baseChart(el) { const c = echarts.init(el); charts.push(c); c.setOption(baseOption()); return c; }
function bareChart(el) { const c = echarts.init(el); charts.push(c); return c; }  // 日历类图不要默认直角坐标配置

// ---------- 仪表盘 ----------
async function dashboard() {
  charts.forEach(c => c.dispose()); charts = [];
  view.innerHTML = `
    <div class="ledger" id="ledger"></div>
    <div class="grid2">
      <section class="panel wide"><h2><span class="no">壹</span><span class="t">书架</span><span class="hint">点封面进详情，← → 翻书</span>
        <select id="shelf-year" class="inline right"></select><span id="shelf-stat" class="hint right"></span></h2>
        <div class="shelf">
          <button id="cf-prev" class="cf-arrow prev" aria-label="上一本">‹</button>
          <div class="cf-viewport"><div class="cf-stage" id="cf-stage"><div class="cf-floor"></div></div></div>
          <button id="cf-next" class="cf-arrow next" aria-label="下一本">›</button>
        </div>
        <div class="cf-cap"><span class="cf-title" id="cf-title"></span><span class="cf-meta" id="cf-meta"></span></div>
        <div class="cf-pos" id="cf-pos"></div></section>
      <section class="panel wide"><h2><span class="no">贰</span><span class="t">剁手日历</span><span class="hint">一天买几本</span><select id="heat-year" class="inline right"></select></h2>
        <div class="heat-wrap"><div class="chart" id="ch-heat"></div><div class="heat-stat" id="heat-stat"></div></div></section>
      <section class="panel span7"><h2><span class="no">叁</span><span class="t">口味光谱</span><span class="hint">读什么 · 什么语言 · 读完没</span></h2>
        <div id="spectrum-flags"></div><div class="chart" id="ch-spectrum"></div></section>
      <section class="panel span5"><h2><span class="no">肆</span><span class="t">评分 × 重要度</span><span class="hint">气泡=盈亏，红=亏 绿=赚</span></h2>
        <div class="chart" id="ch-quadrant"></div></section>
      <section class="panel"><h2><span class="no">伍</span><span class="t">分类目净花费</span><span class="hint">元，红=亏 绿=赚</span></h2><div class="chart" id="ch-cat"></div></section>
      <section class="panel"><h2><span class="no">陆</span><span class="t">年度读书量</span></h2><div class="chart" id="ch-year"></div></section>
      <section class="panel"><h2><span class="no">柒</span><span class="t">作者国籍</span><span class="hint">按关联书数 Top 12</span></h2><div class="chart" id="ch-nat"></div></section>
      <section class="panel"><h2><span class="no">捌</span><span class="t">作者分布</span><span class="hint">Top 10</span></h2><div class="chart" id="ch-author"></div></section>
      <section class="panel"><h2><span class="no">玖</span><span class="t">出版社分布</span><span class="hint">Top 10</span></h2><div class="chart" id="ch-publisher"></div></section>
      <section class="panel wide letter"><h2><span class="no">拾</span><span class="t">AI 年度画像</span>
        <select id="ai-year" class="inline right"></select>
        <button id="ai-gen" class="ghost right">生成</button><button id="ai-refresh" class="ghost right" title="重新生成">↻</button></h2>
        <div class="orn" aria-hidden="true">❦</div>
        <div id="ai-yearly" class="md"><span class="muted">点“生成”，AI 读完你那一年的书和笔记后给你画像（首次约半分钟）</span></div></section>
    </div>`;
  const [s, cat, year, author, publisher] = await Promise.all([
    api("/api/stats/summary"),
    api("/api/stats/group?by=category&agg=sum_price"),
    api("/api/stats/group?by=year&agg=count"),
    api("/api/stats/group?by=author&agg=count"),
    api("/api/stats/group?by=publisher&agg=count"),
  ]);
  const lg = (k, v, sub) =>
    `<div class="lg"><span class="k">${k}</span><span class="v">${v}</span>${sub ? `<span class="sub">${sub}</span>` : ""}</div>`;
  $("#ledger").innerHTML =
    `<div class="lg hero"><span class="k">净花费（元）</span><span class="v ${s.net > 0 ? "bad" : s.net < 0 ? "good" : ""}">${fmt(s.net)}</span><span class="sub">正=亏 负=赚</span></div>` +
    lg("在库", s.in_lib) + lg("已售", s.sold) + lg("读完", s.finished, "读完一本划掉一本") +
    lg("其中亏损", fmt(s.loss)) + lg("其中净赚", fmt(s.gain)) + lg("有价书数", s.priced);

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
  // 新面板：失败不互相阻塞（如 LLM 配额、封面未抓完）
  [panelHeatmap, panelSpectrum, panelQuadrant, panelNationalities, panelShelf, panelYearlyAI]
    .forEach(f => f().catch(e => console.warn(f.name, e)));
}

// ---------- 仪表盘面板（自取数据自渲染，互不依赖） ----------
async function panelHeatmap() {
  const daily = await api("/api/stats/daily");
  const years = [...new Set(Object.keys(daily).map(k => k.slice(0, 4)))].sort().reverse();
  // 默认选登记最多的年份（最新年份可能只有几本，打开就空）
  const days = y => Object.keys(daily).filter(k => k.startsWith(y)).length;
  const defaultYear = years.slice().sort((a, b) => days(b) - days(a))[0];
  const sel = $("#heat-year");
  sel.innerHTML = years.map(y => `<option>${y}</option>`).join("");
  sel.value = defaultYear;
  const c = bareChart($("#ch-heat"));   // 只建一次实例；换年只更新 option，避免重复 init 告警
  const draw = y => {
    const pts = Object.entries(daily).filter(([d]) => d.startsWith(y))
      .map(([d, v]) => [d, v.n, v.titles]);
    c.setOption({
      tooltip: { formatter: p => `${p.value[0]} · ${p.value[1]} 本<br>${p.value[2].join("、")}` },
      visualMap: { min: 1, max: Math.max(3, ...pts.map(p => p[1])), show: false,
        inRange: { color: ["--heat-1", "--heat-2", "--heat-3", "--heat-4"].map(cssVar) } },
      calendar: { range: +y, cellSize: [13, 13], left: "center", top: 30,
        itemStyle: { borderColor: cssVar("--page"), borderWidth: 2 },
        splitLine: { show: false },
        dayLabel: { color: cssVar("--muted"), fontSize: 10 },
        monthLabel: { color: cssVar("--muted"), fontSize: 10 },
        yearLabel: { show: false } },
      series: { type: "heatmap", coordinateSystem: "calendar", data: pts,
        emphasis: { itemStyle: { shadowBlur: 6, shadowColor: cssVar("--series-1") } } },
      animationDuration: 300, animationDurationUpdate: 250 },
    );
    const n = pts.reduce((s, p) => s + p[1], 0);
    const peak = pts.reduce((a, b) => (b[1] > (a ? a[1] : 0) ? b : a), null);
    $("#heat-stat").innerHTML =
      hstat("本年登记", n) + hstat("有购买的天数", pts.length) +
      (peak ? hstat(`最狠一天 ${peak[0].slice(5)}`, `${peak[1]} 本`) : "");
  };
  sel.onchange = () => draw(sel.value);
  draw(defaultYear);
}
const hstat = (k, v) => `<div><div class="k">${k}</div><div class="v">${v}</div></div>`;

// 口味光谱 8-slot 分类色：style.css 的 --cat-*（固定顺序，validate_palette.js 双模式过检）
const CAT = ["--cat-1", "--cat-2", "--cat-3", "--cat-4", "--cat-5", "--cat-6", "--cat-7", "--cat-8"];

async function panelSpectrum() {
  // 纯读：spectrum 不再阻塞等 LLM；未判定时照常画（语言轴启发式兜底）+ 提示条给显式触发入口
  const [axes, st] = await Promise.all([api("/api/stats/spectrum"), api("/api/ai/author-meta")]);
  drawSpectrum(axes);
  renderFlagsChip(st.pending);
}

function drawSpectrum(axes) {
  const el = $("#ch-spectrum");
  const old = echarts.getInstanceByDom(el);   // 重画（判定后刷新）时先 dispose，避免重复 init
  if (old) { old.dispose(); charts.splice(charts.indexOf(old), 1); }
  const keys = [...new Set(axes.flatMap(a => a.segments.map(s => s.key)))];
  const totals = axes.map(a => a.segments.reduce((s, x) => s + x.value, 0));
  const c = baseChart(el);
  c.setOption({
    color: keys.map((_, i) => cssVar(CAT[i % CAT.length])),
    legend: { bottom: 0, itemWidth: 12, itemHeight: 8, textStyle: { color: cssVar("--muted") } },
    grid: { left: 8, right: 40, top: 12, bottom: 40, containLabel: true },
    tooltip: { trigger: "axis", axisPointer: { type: "none" },
      formatter: ps => ps.filter(p => p.value > 0 && p.seriesName)   // 排除末端的无名总数 bar
        .map(p => `${p.marker}${p.seriesName}: ${Math.round(p.value)}`).join("<br>") },
    xAxis: { type: "value", max: v => Math.ceil(v.max * 1.18) },
    yAxis: { type: "category", data: axes.map(a => a.axis),
      axisLabel: { color: cssVar("--text-secondary") } },
    series: [
      ...keys.map(k => ({
        name: k, type: "bar", stack: "s", barWidth: 26,
        data: axes.map(a => (a.segments.find(s => s.key === k) || { value: 0 }).value),
        itemStyle: { borderRadius: 3 } })),
      // 选择性直标：只在每条 bar 末端标总数，分段精确值交给 tooltip
      { type: "bar", stack: "s-total", barWidth: 1, silent: true, tooltip: { show: false },
        data: totals, itemStyle: { color: "transparent" },
        label: { show: true, position: "right", color: cssVar("--text-secondary"),
          formatter: p => Math.round(p.value) } },
    ],
  });
}

let flagsBusy = false;
function renderFlagsChip(pending) {
  const box = $("#spectrum-flags");
  if (!pending) { box.innerHTML = ""; return; }
  if (flagsBusy) {
    box.innerHTML = `<div class="flag-chip"><span class="spin"></span><span class="muted">正在判定作者国籍…</span></div>`;
    return;
  }
  box.innerHTML = `<div class="flag-chip"><span class="muted">${pending} 位作者国籍未判定（语言轴暂按启发式）</span>
    <button class="ghost" id="flag-run">判定</button></div>`;
  $("#flag-run").onclick = async () => {
    flagsBusy = true; renderFlagsChip(pending);
    let st;
    try {
      st = await api("/api/ai/author-meta", { method: "POST" });
    } catch (e) {
      toast(e.message, true);
    } finally {
      flagsBusy = false;
    }
    if (st) drawSpectrum(await api("/api/stats/spectrum"));   // 成功：语言轴换成 LLM 判定值
    renderFlagsChip(st ? st.pending : pending);
  };
}

async function panelNationalities() {
  const rows = (await api("/api/stats/nationalities")).slice(0, 12).reverse();
  baseChart($("#ch-nat")).setOption({
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" },
      formatter: ps => { const r = rows[ps[0].dataIndex];
        return `${r.key}：${r.authors} 位作者 · 关联 ${r.books} 本书`; } },
    xAxis: { type: "value" },
    yAxis: { type: "category", data: rows.map(r => r.key),
      axisLabel: { color: cssVar("--text-secondary") } },
    series: [{ type: "bar", barMaxWidth: 14, data: rows.map(r => r.books),
      itemStyle: { color: cssVar("--series-2"), borderRadius: 3 },
      label: { show: true, position: "right", color: cssVar("--text-secondary") } }],
  });
}

async function panelQuadrant() {
  const pts = await api("/api/stats/quadrant");
  const avg = k => pts.length ? pts.reduce((s, p) => s + p[k], 0) / pts.length : null;
  const [ar, ai] = [avg("rating"), avg("importance")];
  const c = baseChart($("#ch-quadrant"));
  c.setOption({
    grid: { left: 8, right: 30, top: 30, bottom: 24, containLabel: true },
    tooltip: { confine: true,
      formatter: p => `${p.data.title}\n评分 ${p.data.value[0]} · 重要度 ${p.data.value[1]}` +
        (p.data.price != null ? `\n${p.data.price >= 0 ? "亏" : "赚"} ¥${Math.abs(p.data.price).toFixed(2)}` : "\n无价格") },
    xAxis: { type: "value", min: 1, max: 10, name: "评分", nameLocation: "middle", nameGap: 26,
      nameTextStyle: { color: cssVar("--muted") } },
    yAxis: { type: "value", min: 0, max: 1, name: "重要度", nameTextStyle: { color: cssVar("--muted") } },
    series: [{
      type: "scatter",
      data: pts.map(p => ({ title: p.title, id: p.id, price: p.price,
        value: [p.rating, p.importance],
        symbolSize: 12 + Math.sqrt(Math.abs(p.price || 0)) * 1.5,
        itemStyle: { opacity: .75,
          // 无价格 = 中性灰（不读作亏损）；负=赚 蓝；正=亏 红
          color: p.price == null ? cssVar("--muted")
            : p.price < 0 ? cssVar("--div-neg") : cssVar("--div-pos") } })),
      emphasis: { scale: 1.25 },
      markLine: ar == null ? undefined : { silent: true, symbol: "none",
        label: { color: cssVar("--muted"), fontSize: 10 },
        lineStyle: { type: "dashed", color: cssVar("--axis") },
        data: [{ xAxis: +ar.toFixed(1), label: { formatter: "平均评分", position: "end" } },
               { yAxis: +ai.toFixed(2), label: { formatter: "平均重要度", position: "start" } }] } },
    ],
  });
  c.on("click", p => { if (p.data && p.data.id) location.hash = `#/book/${p.data.id}`; });
}

// ---------- 书架（iPod Cover Flow 式 3D） ----------
const CF_OFF = [0, 150, 262, 348, 412, 462];        // 距中心各档的 x 偏移
const CF_Z = [80, -110, -240, -350, -440, -500];    // 逐档后退
const CF_OP = [1, .92, .78, .6, .45, .3];           // 逐档变淡
let cfAll = [], cfList = [], cfCenter = 0;
const cfNodes = new Map();

async function panelShelf() {
  const data = await api("/api/stats/wall");
  cfAll = data.items.slice().sort(
    (a, b) => (a.created || "").localeCompare(b.created || "") || a.id - b.id);
  $("#shelf-stat").textContent = `已抓封面 ${cfAll.length}/${data.total}`;
  const years = [...new Set(cfAll.map(b => yearOf(b.created)))].filter(y => y !== "—").sort().reverse();
  const sel = $("#shelf-year");
  sel.innerHTML = `<option value="">全部</option>` + years.map(y => `<option>${y}</option>`).join("");
  sel.onchange = () => setShelfList(sel.value);
  $("#cf-prev").onclick = () => cfNav(-1);
  $("#cf-next").onclick = () => cfNav(1);
  setShelfList("");
}

function setShelfList(year) {
  cfList = year ? cfAll.filter(b => yearOf(b.created) === year) : cfAll.slice();
  cfCenter = 0;
  $("#cf-stage").querySelectorAll(".cf-item").forEach(el => el.remove());
  cfNodes.clear();
  if (!cfList.length) {
    $("#cf-title").textContent = "";
    $("#cf-meta").innerHTML = `<span class="muted">这年没书（或封面还在抓）</span>`;
    $("#cf-pos").textContent = "";
    $("#cf-prev").disabled = $("#cf-next").disabled = true;
    return;
  }
  cfRender();
}

function cfNav(d) {
  const n = cfCenter + d;
  if (n < 0 || n >= cfList.length) return;
  cfCenter = n;
  cfRender();
}

function cfRender() {
  const stage = $("#cf-stage");
  const seen = new Set();
  for (let off = -5; off <= 5; off++) {
    const i = cfCenter + off;
    if (i < 0 || i >= cfList.length) continue;
    const b = cfList[i];
    let el = cfNodes.get(b.id);
    if (!el) {
      el = document.createElement("figure");
      el.className = "cf-item";
      el.innerHTML = `<img src="${b.cover_url}" alt="${b.title}">`;
      const img = el.firstElementChild;
      img.onerror = () => {   // CDN 偶发拒绝：退避重试两次，再不行淡显占位
        if (!img.dataset.r || +img.dataset.r < 2) {
          img.dataset.r = +img.dataset.r + 1;
          setTimeout(() => { img.src = b.cover_url; }, 600 * img.dataset.r);
        } else {
          img.style.opacity = .25;
        }
      };
      el.onclick = () => {   // 每次点击现读下标（节点跨翻页复用，off 会过期）
        const cur = +el.dataset.i;
        if (cur === cfCenter) location.hash = `#/book/${b.id}`;
        else { cfCenter = cur; cfRender(); }
      };
      cfNodes.set(b.id, el);
      stage.appendChild(el);
    }
    const a = Math.abs(off);
    el.dataset.i = i;
    el.style.transform = `translateX(${off < 0 ? -CF_OFF[a] : CF_OFF[a]}px)` +
      ` translateZ(${CF_Z[a]}px) rotateY(${off === 0 ? 0 : (off < 0 ? 58 : -58)}deg)`;
    el.style.opacity = CF_OP[a];
    el.style.zIndex = 100 - a * 10;
    el.classList.toggle("cf-active", off === 0);
    seen.add(b.id);
  }
  cfNodes.forEach((el, id) => { if (!seen.has(id)) { el.remove(); cfNodes.delete(id); } });
  const b = cfList[cfCenter];
  const title = $("#cf-title");
  title.textContent = b.title;
  title.onclick = () => location.hash = `#/book/${b.id}`;
  const parts = [];
  const y = yearOf(b.created);
  if (y !== "—") parts.push(y);
  if (b.rating) parts.push(`<span class="wr">★${(b.rating / 2).toFixed(1)}</span>`);
  $("#cf-meta").innerHTML = parts.join(" · ");
  $("#cf-pos").textContent = `${cfCenter + 1} / ${cfList.length}`;
  $("#cf-prev").disabled = cfCenter === 0;
  $("#cf-next").disabled = cfCenter === cfList.length - 1;
}

async function panelYearlyAI() {
  const { years } = await api("/api/ai/yearly");
  const sel = $("#ai-year"), box = $("#ai-yearly");
  const genBtn = $("#ai-gen"), refBtn = $("#ai-refresh");
  sel.innerHTML = years.map(y => `<option>${y}</option>`).join("");
  const show = y => {
    api(`/api/ai/yearly?year=${y}&pending=1`).then(r => r.text
      ? box.innerHTML = marked.parse(r.text)
      : box.innerHTML = `<span class="muted">${y} 年尚未生成，点右上“生成”（首次约半分钟）</span>`);
  };
  const run = fresh => {
    genBtn.disabled = refBtn.disabled = true;   // 生成中禁用，防连点并发两次模型调用
    box.innerHTML = `<span class="muted"><span class="spin"></span>AI 正在重读你 ${sel.value} 年的书…</span>`;
    api(`/api/ai/yearly?year=${sel.value}${fresh ? "&fresh=1" : ""}`)
      .then(r => box.innerHTML = marked.parse(r.text))
      .catch(e => box.innerHTML = `<span class="bad">${e.message}</span>`)
      .finally(() => { genBtn.disabled = refBtn.disabled = false; });
  };
  sel.onchange = () => show(sel.value);
  genBtn.onclick = () => run(0);
  refBtn.onclick = () => run(1);
  show(sel.value);
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
      <td class="title" onclick="location.hash='#/book/${b.id}'">${b.title}${b.douban_id ? ` <a class="dbk" title="豆瓣" href="https://book.douban.com/subject/${b.douban_id}/" target="_blank" onclick="event.stopPropagation()">🌐</a>` : ""}${b.status === "in_library" && !b.file_path ? '<span class="warn"> 无正文</span>' : ""}</td>
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
  <label>豆瓣编号（subject 号，可空）<input name="douban_id" pattern="[0-9]*" title="只填数字"></label>
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
  const dbk = b.douban_id
    ? `<a class="obs" href="https://book.douban.com/subject/${b.douban_id}/" target="_blank" rel="noopener">🌐 豆瓣</a>`
    : "";
  const coverBtn = (b.douban_id && !b.cover_url)
    ? `<button id="d-cover" class="ghost" type="button" title="从豆瓣抓封面">抓封面</button>` : "";
  view.innerHTML = `
    <div class="detail">
      <section class="panel meta">
        <h2>${b.title}${dbk}${obs}${coverBtn}</h2>
        <form id="d-form">${BOOK_FIELDS}
          <div class="row"><button class="primary" type="submit">保存</button>
          <button class="danger" type="button" id="d-del">删除记录</button></div>
        </form>
      </section>
      <section class="panel"><h2>正文</h2>
        <div class="md">${content ? marked.parse(content) : "<p class='muted'>无正文文件</p>"}</div>
      </section>
      ${b.file_path ? `<section class="panel wide"><h2>AI 读后摘要 <button id="sum-refresh" class="ghost right" title="重新生成">↻</button></h2>
        <div id="sum" class="md"><span class="muted"><span class="spin"></span>生成中…（首次约十几秒）</span></div></section>` : ""}
    </div>`;
  if (b.douban_id && !b.cover_url) {
    $("#d-cover").onclick = async () => {
      const btn = $("#d-cover");
      btn.disabled = true; btn.textContent = "抓取中…";
      try {
        await api(`/api/books/${id}/cover`, { method: "POST" });
        btn.remove();   // 成功后按钮消失；回仪表盘封面墙即可见
      } catch (e) {
        btn.disabled = false; btn.textContent = "抓封面";
        toast(e.message, true);
      }
    };
  }
  if (b.file_path) {
    const sum = $("#sum");
    const fetchSum = fresh => {
      const btn = $("#sum-refresh");
      if (btn) btn.disabled = true;
      api(`/api/books/${id}/summary${fresh ? "?fresh=1" : ""}`)
        .then(r => sum.innerHTML = marked.parse(r.summary))
        .catch(e => sum.innerHTML = `<span class="bad">${e.message}</span>`)
        .finally(() => { const b2 = $("#sum-refresh"); if (b2) b2.disabled = false; });
    };
    $("#sum-refresh").onclick = () => fetchSum(1);
    fetchSum(0);
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
// 系统主题切换时重建当前视图：图表颜色是 init 时读的 token，CSS 变量变了要重画
window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => route());
// 书架键盘翻页（焦点在输入控件时不抢）
document.addEventListener("keydown", e => {
  if (!$("#cf-stage")) return;
  const t = document.activeElement;
  if (t && /INPUT|SELECT|TEXTAREA/.test(t.tagName)) return;
  if (e.key === "ArrowLeft") cfNav(-1);
  else if (e.key === "ArrowRight") cfNav(1);
});
window.addEventListener("load", () => {
  $("#tagline").textContent =
    `本地读书笔记账本 · ${new Date().toLocaleDateString("zh-CN", { year: "numeric", month: "long", day: "numeric" })}`;
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
