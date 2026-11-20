"use strict";

const $ = (id) => document.getElementById(id);
const view = $("view");
const money = (n) => "NT$ " + n.toLocaleString("zh-TW");
let site, active, revision = 0;
let token = sessionStorage.getItem("tea-session") || "";
let day = new Intl.DateTimeFormat("sv-SE", {
  timeZone: "Asia/Taipei", year: "numeric", month: "2-digit", day: "2-digit"
}).format(new Date());

function el(tag, text, cls) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (cls) node.className = cls;
  return node;
}
function button(text, action, cls) {
  const b = el("button", text, cls);
  b.type = "button";
  b.addEventListener("click", action);
  return b;
}
function message(text = "", bad = false) {
  $("notice").className = text ? (bad ? "notice bad" : "notice") : "";
  $("notice").textContent = text;
}
function heading(text, note) {
  const head = el("div", undefined, "section-head");
  head.append(el("h2", text));
  if (note) head.append(el("span", note, "sub"));
  return head;
}
function loginDialog() {
  $("login-error").textContent = "";
  if (!$("login").open) $("login").showModal();
  $("password").focus();
}
async function api(path, body) {
  const headers = {};
  if (token) headers.Authorization = "Bearer " + token;
  if (body) headers["Content-Type"] = "application/json";
  const response = await fetch(path, {method: body ? "POST" : "GET", headers,
    body: body ? JSON.stringify(body) : undefined});
  const data = await response.json();
  if (!response.ok) {
    if (response.status === 401 && path !== "/api/login") {
      signOut();
      loginDialog();
    }
    const error = new Error(data.error || "服務暫時無法使用");
    error.status = response.status;
    throw error;
  }
  return data;
}
function signOut() {
  token = "";
  sessionStorage.removeItem("tea-session");
  navigate(site.role === "hq" ? "report" : "menu");
}
function menuView() {
  for (const [kind, title] of [["共通", "品牌經典"], ["特色", "本店限定"]]) {
    const items = site.menu.filter((p) => p.kind === kind);
    view.append(heading(title, items.length + " 款飲品"));
    const list = el("div", undefined, "list");
    if (!items.length) list.append(el("p", "本店尚未推出限定飲品。", "item empty"));
    for (const product of items) {
      const line = el("div", undefined, "item");
      const price = el("span", undefined, "price");
      price.append(el("small", "NT$"), String(product.price));
      line.append(el("span", product.name, "drink"), price);
      list.append(line);
    }
    view.append(list);
  }
}
function specialView() {
  view.append(heading("新增本店限定"));
  const form = el("form", undefined, "panel form");
  const field = (label, type) => {
    const l = el("label", label), input = el("input");
    input.required = true;
    input.type = type;
    l.append(input); form.append(l);
    return input;
  };
  const name = field("飲品名稱", "text"), price = field("單價（新臺幣）", "number");
  name.maxLength = 40; price.min = 1; price.max = 9999; price.step = 1;
  const save = el("button", "加入本店菜單");
  form.append(save); view.append(form);
  form.onsubmit = async (e) => {
    e.preventDefault(); save.disabled = true;
    try {
      await api("/api/specials", {name: name.value.trim(), price: Number(price.value)});
      site = await api("/api/site");
      navigate("menu"); message("已將飲品加入本店限定菜單。");
    } catch (err) { message(err.message, true); }
    finally { save.disabled = false; }
  };
}
function requestId() {
  // getRandomValues also works during an HTTP localhost demonstration.
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 15) | 64;
  bytes[8] = (bytes[8] & 63) | 128;
  const hex = Array.from(bytes, b => b.toString(16).padStart(2, "0")).join("");
  return [hex.slice(0,8), hex.slice(8,12), hex.slice(12,16), hex.slice(16,20), hex.slice(20)].join("-");
}
function salesView() {
  view.append(heading("門市收銀", "完成收款後登錄"));
  const key = "tea-pending-" + site.id;
  const pending = JSON.parse(sessionStorage.getItem(key) || "null");
  if (pending) view.append(el("p", "上筆交易等待確認。點選下方按鈕，以原交易編號核對入帳結果。", "warn"));
  const form = el("form"), list = el("div", undefined, "list");
  const fields = new Map();
  const total = el("strong");
  function recalc() {
    const sum = site.menu.reduce((s, p) => s + p.price * (Number(fields.get(p.id).value) || 0), 0);
    total.textContent = money(sum);
  }
  for (const p of site.menu) {
    const row = el("label", undefined, "item"), input = el("input", undefined, "qty");
    input.type = "number"; input.min = 0; input.max = 999; input.step = 1;
    input.value = pending?.items.find(i => i.id === p.id)?.qty || 0;
    input.disabled = !!pending;
    input.setAttribute("aria-label", p.name + "杯數");
    input.oninput = recalc;
    fields.set(p.id, input);
    row.append(el("span", p.name + " · " + money(p.price)), input); list.append(row);
  }
  const box = el("div", undefined, "total"), save = el("button", pending ? "確認上筆交易" : "確認收款並入帳");
  box.append(el("span", "收款總額"), total);
  form.append(list, box, save); view.append(form); recalc();
  form.onsubmit = async (e) => {
    e.preventDefault();
    const items = site.menu.map(p => ({id:p.id, qty:Number(fields.get(p.id).value)})).filter(i => i.qty > 0);
    if (!items.length) { message("請先輸入至少一杯飲品。", true); return; }
    const payload = pending || {request_id:requestId(), items};
    sessionStorage.setItem(key, JSON.stringify(payload)); save.disabled = true;
    try {
      const sale = await api("/api/sales", payload);
      sessionStorage.removeItem(key);
      if (active === "sales") navigate("sales");
      message("已入帳 " + money(sale.total) + "，交易編號 " + sale.id.slice(0,8) + "。");
    } catch (err) {
      if (err.status === 400) sessionStorage.removeItem(key);
      if (active === "sales" && token) navigate("sales");
      message(err.message, true);
    } finally { save.disabled = false; }
  };
}
function table(columns, rows) {
  const wrap = el("div", undefined, "sheet list"), t = el("table"), head = t.createTHead().insertRow();
  for (const col of columns) { const cell = el("th", col); cell.scope = "col"; head.append(cell); }
  const body = t.createTBody();
  for (const row of rows) {
    const tr = body.insertRow();
    for (const value of row) tr.insertCell().textContent = value;
  }
  wrap.append(t); return wrap;
}
async function reportView(version) {
  const hq = site.role === "hq";
  view.append(heading(hq ? "全店營收" : "本店營收"));
  if (!token) {
    view.append(button("以老闆身分登入", loginDialog));
    return;
  }
  const controls = el("div", undefined, "section-head"), label = el("label", "營業日（台灣時間）");
  const date = el("input"); date.type = "date"; date.value = day;
  date.onchange = () => { if (date.value) { day = date.value; navigate("report"); } };
  label.append(date); controls.append(label, button("重新查詢", () => navigate("report"), "outline"));
  view.append(controls);
  const loading = el("p", "正在查詢營收…", "empty");
  view.append(loading);
  try {
    const data = await api("/api/report?day=" + encodeURIComponent(day));
    if (version !== revision) return;
    loading.remove();
    if (hq && !data.complete) view.append(el("p",
      "已取得 " + data.reporting + "／" + data.branches.length + " 間門市。小計僅含已回報門市。", "warn"));
    const metrics = el("div", undefined, "metrics");
    const empty = hq && data.reporting === 0;
    for (const [name, value] of [[hq && !data.complete ? "已回報營收小計" : "營收", money(data.revenue)],
                                ["交易筆數", data.orders], ["售出杯數", data.cups]]) {
      const metric = el("div", undefined, "metric");
      metric.append(el("small", name), el("strong", empty ? "—" : value)); metrics.append(metric);
    }
    view.append(metrics);
    if (hq) {
      view.append(heading("各店明細"),
        table(["門市", "狀態", "交易", "杯數", "營收"], data.branches.map(r =>
          [r.name, r.available ? "已回報" : "暫無回報", r.orders ?? "—", r.cups ?? "—", r.available ? money(r.revenue) : "—"])));
    } else {
      view.append(heading("品項銷售"));
      view.append(data.products.length ? table(["飲品", "售出杯數", "銷售額"],
        data.products.map(r => [r.name, r.cups, money(r.revenue)])) : el("p", "這一天尚無交易。", "panel empty"));
    }
  } catch (err) { if (version === revision) { loading.remove(); message(err.message, true); } }
}
function navigate(page) {
  active = page; const version = ++revision;
  message(); view.replaceChildren();
  const hq = site.role === "hq", tabs = $("tabs");
  $("account").hidden = false;
  $("account").textContent = token ? "登出" : hq ? "老闆登入" : "店長登入";
  $("login-title").textContent = hq ? "老闆登入" : "店長登入";
  tabs.replaceChildren(); tabs.hidden = !token || hq;
  if (!tabs.hidden) for (const [id, label] of [["menu","公開菜單"],["sales","收銀"],["specials","新增飲品"],["report","營收"]]) {
    const tab = button(label, () => navigate(id));
    if (id === page) tab.setAttribute("aria-current", "page");
    tabs.append(tab);
  }
  if (page === "menu") menuView();
  else if (page === "sales") salesView();
  else if (page === "specials") specialView();
  else reportView(version);
}
$("account").onclick = () => token ? signOut() : loginDialog();
$("cancel").onclick = () => $("login").close();
$("login-form").onsubmit = async (e) => {
  e.preventDefault();
  try {
    const result = await api("/api/login", {password:$("password").value});
    token = result.token; sessionStorage.setItem("tea-session", token);
    $("password").value = ""; $("login").close();
    navigate(site.role === "hq" ? "report" : "sales");
  } catch (err) { $("login-error").textContent = err.message; }
};
(async () => {
  try {
    site = await api("/api/site");
    document.title = site.name + "｜茶序";
    $("site-name").textContent = site.name;
    $("context").textContent = site.role === "hq" ? "茶序 · 營運管理" : "茶序 · 門市茶單";
    navigate(site.role === "hq" ? "report" : "menu");
  } catch (err) { $("site-name").textContent = "服務暫時無法載入"; message(err.message, true); }
})();
