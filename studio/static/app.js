import { attachHover, breakdownGroups, CHARTS, createFrames, exportPng, formatTime, moneyNode, moneyWords, renderForScreen, renderVideo, saveBlob, tableFor, VALUE_PARTS, valuePart, VIDEO_HOLD_SECONDS, VideoCancelled } from "./charts.js";
import { COINS } from "./coins.js";
import { drawVisual, QUALITY_COLORS, shownLines, valueWords, visualBlob } from "./visuals.js";

const FORMATS = [["short", "Shorts"], ["long", "Longform"]];
const STATUSES = [["idea", "Idea"], ["scripting", "Scripting"], ["recording", "Recording"], ["editing", "Editing"], ["published", "Published"]];
const SOURCES = [["forever", "Forever"], ["tbc", "TBC Anniversary"], ["mock", "Mock data"]];
const WORDS_PER_SECOND = 2.5;
const SHORT_TARGET_SECONDS = 45;

const sidebar = document.getElementById("sidebar");
const main = document.getElementById("main");
const tooltip = document.getElementById("tooltip");
const dialog = document.getElementById("dialog");
const toast = document.getElementById("toast");

const state = { tree: [], sources: [], collapsed: loadCollapsed(), episode: null, addingTo: null };

function loadCollapsed() {
  try { return new Set(JSON.parse(localStorage.getItem("collapsed") || "[]")); } catch { return new Set(); }
}
function saveCollapsed() {
  try { localStorage.setItem("collapsed", JSON.stringify([...state.collapsed])); } catch { /* A convenience only. */ }
}

// DOM helper. Text always goes in as text nodes, so titles can never become markup.
function h(tag, props = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (key.startsWith("on")) el.addEventListener(key.slice(2).toLowerCase(), value);
    else if (key === "class") el.className = value;
    else if (key in el && key !== "list") el[key] = value;
    else if (value !== false && value != null) el.setAttribute(key, value);
  }
  el.append(...children.flat(Infinity).filter((c) => c !== null && c !== undefined && c !== false));
  return el;
}

const ICONS = {
  plus: "M8 3v10M3 8h10",
  trash: "M3 4.5h10M6.5 4.5V3h3v1.5M4.5 4.5l.6 8.5h5.8l.6-8.5",
  caret: "M4 6l4 4 4-4",
  grip: "M6 3.5h.01M10 3.5h.01M6 8h.01M10 8h.01M6 12.5h.01M10 12.5h.01",
};
function icon(name) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 16 16");
  svg.setAttribute("aria-hidden", "true");
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("d", ICONS[name]);
  path.setAttribute("fill", "none");
  path.setAttribute("stroke", "currentColor");
  path.setAttribute("stroke-width", name === "grip" ? "2.2" : "1.5");
  path.setAttribute("stroke-linecap", "round");
  path.setAttribute("stroke-linejoin", "round");
  svg.append(path);
  return svg;
}

let toastTimer;
function showError(message) {
  toast.textContent = message;
  toast.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { toast.hidden = true; }, 6000);
}

async function api(method, path, body) {
  const response = await fetch(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    keepalive: method !== "GET", // Lets a save finish if the tab is closing.
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
  return data;
}

// Runs an action, turning a failure into a visible message rather than a silent no-op.
async function attempt(action) {
  try {
    return await action();
  } catch (err) {
    showError(err.message);
    return undefined;
  }
}

function ask({ title, message, list, confirm, danger }) {
  return new Promise((resolve) => {
    const close = (answer) => { dialog.close(); resolve(answer); };
    dialog.replaceChildren(...[
      h("h2", {}, title),
      message ? h("p", {}, message) : null,
      list?.length ? h("ul", {}, list.map((item) => h("li", {}, item))) : null,
      h("div", { class: "dialog-actions" },
        h("button", { class: "button", onclick: () => close(false) }, "Cancel"),
        h("button", { class: `button ${danger ? "danger" : "primary"}`, onclick: () => close(true) }, confirm)),
    ].filter(Boolean));
    dialog.oncancel = () => resolve(false);
    dialog.showModal();
  });
}

// Routes: #/episode/3/script and #/sources.
function route() {
  const parts = location.hash.replace(/^#\/?/, "").split("/");
  if (parts[0] === "episode" && parts[1]) return { view: "episode", id: Number(parts[1]), tab: parts[2] || "script" };
  if (parts[0] === "sources") return { view: "sources" };
  return { view: "home" };
}
const go = (hash) => { location.hash = hash; };

async function refreshTree() {
  state.tree = (await api("GET", "/api/tree")).series;
  renderSidebar();
}
async function refreshSources() {
  state.sources = (await api("GET", "/api/sources")).sources;
}

// ---------- Drag and drop ----------

// Reorders children of one or several lists. `onDrop` receives the list dropped into.
function sortable(list, { item, group, onDrop, handle }) {
  const clear = () => document.querySelectorAll(".drop-before,.drop-after,.drop-into").forEach((el) => el.classList.remove("drop-before", "drop-after", "drop-into"));
  list.addEventListener("dragstart", (e) => {
    const target = e.target.closest?.(item);
    if (!target || !list.contains(target)) return;
    if (handle && !target.dataset.armed) { e.preventDefault(); return; }
    sortable.current = { el: target, group };
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", target.dataset.id);
    requestAnimationFrame(() => target.classList.add("dragging"));
  });
  list.addEventListener("dragover", (e) => {
    const drag = sortable.current;
    if (!drag || drag.group !== group) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    clear();
    const over = e.target.closest?.(item);
    if (over && over !== drag.el) {
      const box = over.getBoundingClientRect();
      over.classList.add(e.clientY < box.top + box.height / 2 ? "drop-before" : "drop-after");
    }
  });
  list.addEventListener("drop", (e) => {
    const drag = sortable.current;
    if (!drag || drag.group !== group) return;
    e.preventDefault();
    e.stopPropagation();
    const over = e.target.closest?.(item);
    if (over && over !== drag.el) {
      const box = over.getBoundingClientRect();
      over.parentNode.insertBefore(drag.el, e.clientY < box.top + box.height / 2 ? over : over.nextSibling);
    } else if (!over) {
      list.append(drag.el);
    }
    clear();
    onDrop(list, drag.el);
  });
  list.addEventListener("dragend", (e) => {
    e.target.closest?.(item)?.classList.remove("dragging");
    const dragged = e.target.closest?.(item);
    if (handle && dragged) {
      dragged.draggable = false;
      delete dragged.dataset.armed;
    }
    clear();
    sortable.current = null;
  });
}

const orderOf = (list) => [...list.children].map((el) => Number(el.dataset.id));

async function saveEpisodeOrder(list) {
  await attempt(() => api("POST", `/api/series/${list.dataset.series}/order`, { ids: orderOf(list) }));
  await refreshTree();
  if (state.episode) await reloadEpisodeHead();
}

// ---------- Sidebar ----------

function inlineEdit(host, value, onCommit) {
  const input = h("input", { type: "text", class: "inline-input", value, "aria-label": "Name" });
  let finished = false;
  const finish = (commit) => {
    if (finished) return;
    finished = true;
    const next = input.value.trim();
    if (commit && next && next !== value) onCommit(next);
    else renderSidebar();
  };
  input.addEventListener("keydown", (e) => {
    e.stopPropagation();
    if (e.key === "Enter") finish(true);
    if (e.key === "Escape") finish(false);
  });
  input.addEventListener("blur", () => finish(true));
  host.replaceChildren(input);
  input.focus();
  input.select();
}

function renderSidebar() {
  const current = route();
  const sectionFor = ([format, label]) => {
    const series = state.tree.filter((s) => s.format === format);
    return h("section", { class: "side-section" },
      h("div", { class: "side-heading" }, label,
        h("button", { class: "icon-button", title: `Add a series or title to ${label}`, "aria-label": `Add a series or title to ${label}`,
          onclick: () => { state.addingTo = format; renderSidebar(); } }, icon("plus"))),
      state.addingTo === format ? addSeriesRow(format) : null,
      series.length || state.addingTo === format ? null : h("p", { class: "side-empty" }, "Nothing here yet"),
      series.map((s) => seriesBlock(s, current)));
  };
  const records = (id) => state.sources.find((s) => s.id === id)?.records ?? 0;
  sidebar.replaceChildren(
    h("div", { class: "brand" }, brandMark(), "Ledger Studio"),
    h("div", { class: "side-scroll" }, FORMATS.map(sectionFor)),
    h("div", { class: "side-foot" },
      h("button", { class: `nav-link${current.view === "sources" ? " active" : ""}`, onclick: () => go("#/sources") },
        h("span", {}, "Data sources"),
        h("span", { class: "nav-sources", title: "Records in Forever, TBC and Mock" },
          `${compact(records("forever"))} / ${compact(records("tbc"))} / ${compact(records("mock"))}`))),
  );
}

function compact(value) {
  return value >= 1000 ? `${(value / 1000).toFixed(1)}k` : String(value);
}

function brandMark() {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 16 16");
  svg.setAttribute("class", "brand-mark");
  svg.setAttribute("aria-hidden", "true");
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("d", "M1 13l4-5 3 3 6-8");
  path.setAttribute("fill", "none");
  path.setAttribute("stroke", "currentColor");
  path.setAttribute("stroke-width", "2");
  path.setAttribute("stroke-linecap", "round");
  path.setAttribute("stroke-linejoin", "round");
  svg.append(path);
  return svg;
}

function addSeriesRow(format) {
  const input = h("input", { type: "text", class: "inline-input", placeholder: "Series or title name", "aria-label": "New series or title name" });
  let done = false;
  const finish = async (commit) => {
    if (done) return;
    done = true;
    state.addingTo = null;
    const name = input.value.trim();
    if (commit && name) await attempt(() => api("POST", "/api/series", { name, format }));
    await refreshTree();
  };
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") finish(true);
    if (e.key === "Escape") finish(false);
  });
  input.addEventListener("blur", () => finish(true));
  setTimeout(() => input.focus());
  return h("div", { class: "side-add" }, input);
}

function seriesBlock(series, current) {
  const closed = state.collapsed.has(series.id);
  const nameEl = h("span", { class: "series-name", title: `${series.name}. Double-click to rename.` }, series.name);
  const row = h("div", { class: "series-row", "data-series": series.id },
    h("button", { class: `icon-button caret${closed ? " closed" : ""}`, "aria-label": closed ? "Expand" : "Collapse", "aria-expanded": String(!closed),
      onclick: () => {
        if (closed) state.collapsed.delete(series.id); else state.collapsed.add(series.id);
        saveCollapsed();
        renderSidebar();
      } }, icon("caret")),
    nameEl,
    h("button", { class: "icon-button row-action", title: "Add episode", "aria-label": `Add episode to ${series.name}`,
      onclick: async () => {
        const created = await attempt(() => api("POST", `/api/series/${series.id}/episodes`, {}));
        if (created) {
          state.collapsed.delete(series.id);
          saveCollapsed();
          await refreshTree();
          state.focusTitle = true;
          go(`#/episode/${created.id}/script`);
        }
      } }, icon("plus")),
    h("button", { class: "icon-button row-action", title: "Delete", "aria-label": `Delete ${series.name}`,
      onclick: async () => {
        const count = series.episodes.length;
        const sure = await ask({ title: `Delete ${series.name}?`, danger: true, confirm: "Delete",
          message: count ? `This also deletes its ${count} episode${count === 1 ? "" : "s"}, with their scripts and shots.` : "It has no episodes." });
        if (sure && await attempt(() => api("DELETE", `/api/series/${series.id}`)) !== undefined) {
          if (series.episodes.some((e) => e.id === route().id)) go("#/");
          await refreshTree();
        }
      } }, icon("trash")));
  nameEl.addEventListener("dblclick", () => inlineEdit(nameEl, series.name, async (name) => {
    await attempt(() => api("PATCH", `/api/series/${series.id}`, { name }));
    await refreshTree();
    if (state.episode) await reloadEpisodeHead();
  }));
  // Dropping on the series row adds the episode to the end, which also fills an empty series.
  row.addEventListener("dragover", (e) => {
    if (sortable.current?.group !== "episodes") return;
    e.preventDefault();
    row.classList.add("drop-into");
  });
  row.addEventListener("dragleave", () => row.classList.remove("drop-into"));
  row.addEventListener("drop", async (e) => {
    const drag = sortable.current;
    if (drag?.group !== "episodes") return;
    e.preventDefault();
    row.classList.remove("drop-into");
    const ids = series.episodes.map((ep) => ep.id).filter((id) => id !== Number(drag.el.dataset.id));
    await attempt(() => api("POST", `/api/series/${series.id}/order`, { ids: [...ids, Number(drag.el.dataset.id)] }));
    await refreshTree();
    if (state.episode) await reloadEpisodeHead();
  });
  const block = h("div", {}, row);
  if (!closed) {
    const list = h("ul", { class: "episode-list", "data-series": series.id },
      series.episodes.map((episode) => episodeItem(episode, series, current)));
    sortable(list, { item: ".episode-item", group: "episodes", onDrop: saveEpisodeOrder });
    block.append(list);
  }
  return block;
}

function episodeItem(episode, series, current) {
  const titleEl = h("span", { class: "episode-title", title: "Drag to reorder. Double-click to rename." }, episode.title);
  const li = h("li", {
    class: `episode-item${current.view === "episode" && current.id === episode.id ? " active" : ""}`,
    draggable: "true", tabIndex: 0, "data-id": episode.id,
    title: "Alt + Up or Down moves this episode",
    onclick: () => go(`#/episode/${episode.id}/${route().tab || "script"}`),
    onkeydown: async (e) => {
      if (e.target !== li) return;
      if (e.key === "Enter") go(`#/episode/${episode.id}/${route().tab || "script"}`);
      if (e.altKey && (e.key === "ArrowUp" || e.key === "ArrowDown")) {
        e.preventDefault();
        const ids = series.episodes.map((ep) => ep.id);
        const from = ids.indexOf(episode.id), to = from + (e.key === "ArrowUp" ? -1 : 1);
        if (to < 0 || to >= ids.length) return;
        ids.splice(to, 0, ids.splice(from, 1)[0]);
        await attempt(() => api("POST", `/api/series/${series.id}/order`, { ids }));
        await refreshTree();
        sidebar.querySelector(`.episode-item[data-id="${episode.id}"]`)?.focus();
      }
    },
  }, h("span", { class: `status-dot ${episode.status}`, title: label(STATUSES, episode.status) }), titleEl);
  titleEl.addEventListener("dblclick", (e) => {
    e.stopPropagation();
    li.draggable = false;
    inlineEdit(titleEl, episode.title, async (title) => {
      await attempt(() => api("PATCH", `/api/episodes/${episode.id}`, { title }));
      await refreshTree();
      if (state.episode?.id === episode.id) await reloadEpisodeHead();
    });
  });
  return li;
}

const label = (pairs, key) => pairs.find(([k]) => k === key)?.[1] ?? key;

// ---------- Episode ----------

const wordCount = (text) => (text.trim().match(/\S+/g) || []).length;
const secondsFor = (text) => Math.round(wordCount(text) / WORDS_PER_SECOND);

const saver = { timers: new Map(), pending: new Map() };
function saveLater(key, action, delay = 450) {
  clearTimeout(saver.timers.get(key));
  saver.pending.set(key, action);
  setSaveState("Saving…");
  saver.timers.set(key, setTimeout(() => flushOne(key), delay));
}
async function flushOne(key) {
  clearTimeout(saver.timers.get(key));
  saver.timers.delete(key);
  const action = saver.pending.get(key);
  saver.pending.delete(key);
  if (!action) return;
  const ok = await attempt(async () => { await action(); return true; });
  setSaveState(ok ? "Saved" : "Not saved");
}
const flushSaves = () => Promise.all([...saver.pending.keys()].map(flushOne));
function setSaveState(text) {
  document.querySelectorAll("[data-save-state]").forEach((el) => { el.textContent = text; });
}
window.addEventListener("beforeunload", () => { flushSaves(); });

async function reloadEpisodeHead() {
  const episode = await attempt(() => api("GET", `/api/episodes/${state.episode.id}`));
  if (episode) {
    state.episode.series_name = episode.series_name;
    state.episode.format = episode.format;
    state.episode.title = episode.title;
    const crumb = main.querySelector(".crumb");
    if (crumb) crumb.textContent = `${episode.series_name}  ·  ${episode.format === "short" ? "Short" : "Longform"}`;
    const input = main.querySelector(".title-input");
    if (input && document.activeElement !== input) input.value = episode.title;
  }
}

async function renderEpisode(id, tab) {
  const episode = await attempt(() => api("GET", `/api/episodes/${id}`));
  if (!episode) return renderHome();
  state.episode = episode;
  const patch = (fields) => api("PATCH", `/api/episodes/${id}`, fields);

  const title = h("input", { type: "text", class: "title-input", value: episode.title, "aria-label": "Episode title",
    oninput: (e) => {
      const value = e.target.value.trim();
      if (!value) return;
      episode.title = value;
      saveLater(`title-${id}`, async () => { await patch({ title: value }); await refreshTree(); });
    },
    onblur: (e) => { if (!e.target.value.trim()) e.target.value = episode.title; } });

  const status = h("select", { "aria-label": "Status", onchange: async (e) => {
    episode.status = e.target.value;
    await attempt(() => patch({ status: e.target.value }));
    await refreshTree();
  } }, STATUSES.map(([value, text]) => h("option", { value, selected: value === episode.status }, text)));

  const tabButton = (key, text) => h("button", { role: "tab", "aria-selected": String(tab === key), onclick: () => go(`#/episode/${id}/${key}`) }, text);
  const pane = h("div", {});
  const visualsTab = tabButton("visuals", `Visuals (${episode.visuals.length})`);
  main.replaceChildren(h("div", { class: "page" },
    h("p", { class: "crumb" }, `${episode.series_name}  ·  ${episode.format === "short" ? "Short" : "Longform"}`),
    h("div", { class: "episode-head" }, title, status,
      h("button", { class: "button danger", onclick: async () => {
        const sure = await ask({ title: `Delete ${episode.title}?`, message: "Its script and shots are deleted too. Ledger data is not affected.", confirm: "Delete", danger: true });
        if (sure && await attempt(() => api("DELETE", `/api/episodes/${id}`)) !== undefined) {
          await refreshTree();
          go("#/");
        }
      } }, "Delete")),
    h("div", { class: "tabs", role: "tablist" },
      tabButton("script", "Script"), tabButton("shots", `Shots (${episode.shots.length})`), tabButton("data", "Data"),
      visualsTab,
      h("span", { class: "tab-note", "data-save-state": "" })),
    pane));
  if (state.focusTitle) {
    state.focusTitle = false;
    title.focus();
    title.select();
  }
  if (tab === "shots") renderShots(pane, episode);
  else if (tab === "data") await renderData(pane, episode);
  else if (tab === "visuals") renderVisuals(pane, episode, visualsTab);
  else renderScript(pane, episode);
}

function runtimeLine(episode, text) {
  const seconds = secondsFor(text);
  const over = episode.format === "short" && seconds > SHORT_TARGET_SECONDS;
  return [h("span", {}, `${wordCount(text)} words`),
    h("span", { class: over ? "meta-over" : "" }, `About ${seconds} seconds spoken`),
    episode.format === "short" ? h("span", { class: over ? "meta-over" : "" }, over ? `Over the ${SHORT_TARGET_SECONDS} second target` : `Target: under ${SHORT_TARGET_SECONDS} seconds`) : null];
}

function renderScript(pane, episode) {
  const meta = h("div", { class: "script-meta" });
  const paint = () => meta.replaceChildren(...runtimeLine(episode, box.value).filter(Boolean));
  const box = h("textarea", { class: "script-box", value: episode.script, placeholder: "Write the script here. Each sentence becomes a shot.", "aria-label": "Script",
    oninput: (e) => {
      episode.script = e.target.value;
      paint();
      saveLater(`script-${episode.id}`, () => api("PATCH", `/api/episodes/${episode.id}`, { script: episode.script }));
    } });
  paint();
  pane.replaceChildren(box, meta);
}

// Compares words regardless of order, because reordering shots is not a change of script.
function scriptMatchesShots(episode) {
  const words = (text) => (text.match(/\S+/g) || []).sort().join(" ");
  return words(episode.script) === words(episode.shots.map((s) => s.voiceover).join(" "));
}

function autoGrow(textarea) {
  textarea.style.height = "auto";
  textarea.style.height = `${textarea.scrollHeight + 2}px`;
}

function renderShots(pane, episode) {
  const rebuild = async () => {
    await flushSaves();
    const preview = await attempt(() => api("POST", `/api/episodes/${episode.id}/shots/rebuild`, { dry_run: true }));
    if (!preview) return;
    if (preview.dropped.length) {
      const sure = await ask({ title: "Remove shots that left the script?", confirm: "Update shots", danger: true,
        message: "These shots have visuals, but their lines are no longer in the script:", list: preview.dropped });
      if (!sure) return;
    }
    await attempt(() => api("POST", `/api/episodes/${episode.id}/shots/rebuild`, {}));
    await renderEpisode(episode.id, "shots");
  };
  const notice = !scriptMatchesShots(episode) && episode.script.trim()
    ? h("div", { class: "notice" }, h("span", {}, episode.shots.length ? "The script and these shots no longer match." : "This script has no shots yet."),
      h("button", { class: "button", onclick: rebuild }, episode.shots.length ? "Update shots from script" : "Create shots from script"))
    : null;

  const total = () => episode.shots.reduce((sum, shot) => sum + Math.max(1, secondsFor(shot.voiceover)), 0);
  const totalNote = h("span", { class: "figure-note" });
  const paintTotal = () => {
    const done = episode.shots.filter((s) => s.done).length;
    totalNote.textContent = `${episode.shots.length} shots  ·  about ${total()} seconds  ·  ${done} done`;
  };
  paintTotal();

  const list = h("div", { class: "shot-list" });
  episode.shots.forEach((shot, index) => list.append(shotRow(shot, index, episode, paintTotal)));
  sortable(list, { item: ".shot-row", group: "shots", handle: true, onDrop: async (container) => {
    const ids = orderOf(container);
    const byId = new Map(episode.shots.map((s) => [s.id, s]));
    episode.shots = ids.map((id) => byId.get(id));
    await attempt(() => api("POST", `/api/episodes/${episode.id}/shots/order`, { ids }));
    [...container.children].forEach((row, i) => { row.querySelector(".num").textContent = String(i + 1); });
  } });

  pane.replaceChildren(notice ?? "",
    episode.shots.length ? h("div", { class: "shot-table" },
      h("div", { class: "shot-head" }, h("span", {}), h("span", {}, "#"), h("span", {}, "Voiceover"), h("span", {}, "Visual"), h("span", {}, "Chart"), h("span", { style: "text-align:right" }, "Secs"), h("span", {}, "Done"), h("span", {})),
      list) : h("div", { class: "empty-state" }, h("h2", {}, "No shots yet"), h("p", {}, "Write the script first, or add a shot by hand.")),
    h("div", { class: "shots-foot" },
      h("button", { class: "button", onclick: async () => {
        await attempt(() => api("POST", `/api/episodes/${episode.id}/shots`, {}));
        await renderEpisode(episode.id, "shots");
      } }, "Add shot"),
      h("span", { class: "spacer" }), totalNote));
  requestAnimationFrame(() => list.querySelectorAll("textarea").forEach(autoGrow));
}

function shotRow(shot, index, episode, paintTotal) {
  const secs = h("span", { class: "secs" }, String(Math.max(1, secondsFor(shot.voiceover))));
  const patch = (fields) => api("PATCH", `/api/shots/${shot.id}`, fields);
  const area = (field, placeholder, extra) => h("textarea", { rows: 1, value: shot[field], placeholder, "aria-label": `${placeholder}, shot ${index + 1}`,
    oninput: (e) => {
      shot[field] = e.target.value;
      autoGrow(e.target);
      if (field === "voiceover") {
        secs.textContent = String(Math.max(1, secondsFor(shot.voiceover)));
        paintTotal();
      }
      saveLater(`shot-${shot.id}-${field}`, () => patch({ [field]: shot[field] }));
    }, ...extra });
  const row = h("div", { class: "shot-row", "data-id": shot.id },
    h("button", { class: "grip", "aria-label": `Drag to reorder shot ${index + 1}`, title: "Drag to reorder. Alt + Up or Down also moves it.",
      onpointerdown: () => { row.draggable = true; row.dataset.armed = "1"; },
      onpointerup: () => { row.draggable = false; delete row.dataset.armed; },
      onkeydown: async (e) => {
        if (!e.altKey || (e.key !== "ArrowUp" && e.key !== "ArrowDown")) return;
        e.preventDefault();
        const ids = episode.shots.map((s) => s.id);
        const to = ids.indexOf(shot.id) + (e.key === "ArrowUp" ? -1 : 1);
        if (to < 0 || to >= ids.length) return;
        ids.splice(to, 0, ids.splice(ids.indexOf(shot.id), 1)[0]);
        await attempt(() => api("POST", `/api/episodes/${episode.id}/shots/order`, { ids }));
        await renderEpisode(episode.id, "shots");
        main.querySelector(`.shot-row[data-id="${shot.id}"] .grip`)?.focus();
      } }, icon("grip")),
    h("span", { class: "num" }, String(index + 1)),
    h("div", { class: "voice" }, area("voiceover", "Voiceover")),
    h("div", { class: "visual" }, area("visual", "What's on screen")),
    h("div", { class: "chart-cell chart-actions" },
      h("select", { "aria-label": `Chart for shot ${index + 1}`, title: "A chart this shot uses. Export it from the Data tab.",
        onchange: async (e) => {
          shot.chart = e.target.value;
          await attempt(() => patch({ chart: shot.chart }));
        } },
        h("option", { value: "", selected: !shot.chart }, "No chart"),
        Object.entries(CHARTS).map(([value, text]) => h("option", { value, selected: shot.chart === value }, text)))),
    secs,
    h("label", { class: "check" }, h("input", { type: "checkbox", checked: shot.done, "aria-label": `Shot ${index + 1} done`,
      onchange: async (e) => {
        shot.done = e.target.checked;
        paintTotal();
        await attempt(() => patch({ done: shot.done }));
      } })),
    h("button", { class: "icon-button", title: "Delete shot", "aria-label": `Delete shot ${index + 1}`,
      onclick: async () => {
        await attempt(() => api("DELETE", `/api/shots/${shot.id}`));
        await renderEpisode(episode.id, "shots");
      } }, icon("trash")));
  return row;
}

// ---------- Data ----------

async function renderData(pane, episode) {
  const refreshAll = async () => { await refreshSources(); renderSidebar(); await draw(); };
  const patch = async (fields) => {
    Object.assign(episode, fields);
    await attempt(() => api("PATCH", `/api/episodes/${episode.id}`, fields));
  };
  const filters = h("div", { class: "filters" });
  const figures = h("div", { class: "figures" });
  pane.replaceChildren(filters, figures);

  async function drawFilters(windows) {
    const windowOptions = (kind, heading) => {
      const items = windows.filter((w) => w.kind === kind);
      return items.length ? h("optgroup", { label: heading }, items.map((w) => h("option", { value: w.id, selected: w.id === episode.window }, w.label))) : null;
    };
    filters.replaceChildren(...[
      h("div", { class: "segmented", role: "group", "aria-label": "Data source" }, SOURCES.map(([id, text]) => h("button", { "aria-pressed": String(episode.source === id),
        onclick: async () => {
          if (episode.source === id) return;
          // Windows and items belong to one source, so a new source starts afresh.
          const { name, ...item } = episode.chart_settings.item ?? {};
          const { names, ...compare } = episode.chart_settings.compare ?? {};
          const chart_settings = { ...episode.chart_settings, ...(name === undefined ? {} : { item }), ...(names === undefined ? {} : { compare }) };
          await patch({ source: id, window: "all", chart_settings });
          await draw();
        } }, text))),
      windows.length ? h("span", { class: "filter-label" }, "Window") : null,
      windows.length ? h("select", { "aria-label": "Window", onchange: async (e) => { await patch({ window: e.target.value }); await draw(); } },
        windowOptions("marker", "Episode markers"), windowOptions("day", "Calendar days"), windowOptions("all", "Everything")) : null,
      windows.length ? h("div", { class: "segmented", role: "group", "aria-label": "Range for the line charts" },
        [["window", "This window"], ["to_date", "All up to its end"]].map(([id, text]) => h("button", { "aria-pressed": String(episode.range === id),
          onclick: async () => { await patch({ range: id }); await draw(); } }, text))) : null,
      h("span", { class: "spacer" }),
      h("button", { class: "button quiet", onclick: refreshAll }, "Refresh"),
    ].filter(Boolean));
  }

  async function draw() {
    figures.classList.add("loading");
    const loaded = await attempt(async () => {
      const [{ windows }, data] = await Promise.all([
        api("GET", `/api/data/${episode.source}/windows`),
        api("GET", `/api/data/${episode.source}/figures?window=${encodeURIComponent(episode.window)}&range=${episode.range}`),
      ]);
      return { windows, data };
    });
    figures.classList.remove("loading");
    if (!loaded) return;
    const { windows, data } = loaded;
    await drawFilters(windows);
    if (data.empty) {
      figures.replaceChildren(h("div", { class: "empty-state" },
        h("h2", {}, `No ${label(SOURCES, episode.source)} data yet`),
        h("p", {}, episode.source === "forever"
          ? "It appears here automatically once the addon is enabled in Forever and the game saves, on /reload or logout."
          : "Point the studio at this client's SavedVariables file."),
        h("button", { class: "button", onclick: () => go("#/sources") }, "Open data sources")));
      return;
    }
    const ctx = { source: episode.source, windowLabel: data.window.label };
    figures.replaceChildren(
      data.window_missing ? h("div", { class: "notice" }, `The saved window "${data.window_missing.replace(/^\w+:/, "")}" is not in this data, so this shows all recorded history.`) : "",
      highlightsCard(data.highlights || [], data.window),
      // A server started before a chart existed doesn't send it; the others still draw.
      ...["start", "auction", "value", "revenue", "costs"].filter((kind) => data[kind]).map((kind) => figureCard(kind, data, ctx, episode)),
      itemSection(episode, ctx));
  }
  await draw();
}

// ---------- Item analysis ----------

function choiceLabel(choice) {
  const parts = [["sold", choice.sold], ["farmed", choice.farmed], ["crafted", choice.crafted], ["bought", choice.bought]]
    .filter(([, count]) => count).map(([word, count]) => `${word} ${count.toLocaleString("en-US")}`);
  if (!choice.bought && choice.purchases) parts.push("bought");
  if (!parts.length && choice.listed) parts.push(`listed ${choice.listed.toLocaleString("en-US")}`);
  return parts.length ? `${choice.name}  ·  ${parts.join(", ")}` : choice.name;
}

// Changes one chart's saved settings, keeping the rest.
function saveChartSetting(episode, kind, changes) {
  const settings = episode.chart_settings;
  episode.chart_settings = { ...settings, [kind]: { ...(settings[kind] ?? {}), ...changes } };
  saveLater(`charts-${episode.id}`, () => api("PATCH", `/api/episodes/${episode.id}`, { chart_settings: episode.chart_settings }));
}

// One item analysed, or several compared side by side, chosen per episode.
function itemSection(episode, ctx) {
  const controls = h("div", { class: "item-controls" });
  const body = h("div");
  const view = () => episode.chart_settings.item?.view ?? "one";
  const viewButtons = [["one", "One item"], ["compare", "Compare items"]].map(([id, text]) => h("button", { onclick: () => {
    if (view() === id) return;
    saveChartSetting(episode, "item", { view: id });
    show();
  } }, text));
  const section = h("section", { class: "item-section", "aria-label": "Item analysis" },
    h("div", { class: "filters item-picker" }, h("h2", {}, "Item analysis"),
      h("div", { class: "segmented", role: "group", "aria-label": "Item view" }, viewButtons), controls), body);

  function show() {
    viewButtons.forEach((button, i) => button.setAttribute("aria-pressed", String((i === 1) === (view() === "compare"))));
    controls.replaceChildren();
    body.replaceChildren();
    (view() === "compare" ? compareItems : oneItem)(episode, ctx, section, controls, body);
  }
  show();
  return section;
}

// One item at a time. Items are listed by what they sold for.
function oneItem(episode, ctx, section, controls, body) {
  const picker = h("select", { class: "item-select", "aria-label": "Item to analyse", disabled: true });
  controls.replaceChildren(h("span", { class: "filter-label" }, "Item"), picker);

  async function load(name) {
    section.classList.add("loading");
    const query = `window=${encodeURIComponent(episode.window)}&name=${encodeURIComponent(name || "")}`;
    const result = await attempt(() => api("GET", `/api/data/${episode.source}/item?${query}`));
    section.classList.remove("loading");
    if (!result || result.empty || !picker.isConnected) return;
    const chosen = result.item?.name;
    const options = result.choices.map((choice) => h("option", { value: choice.name, selected: choice.name === chosen }, choiceLabel(choice)));
    if (chosen && !result.choices.some((choice) => choice.name === chosen)) {
      options.unshift(h("option", { value: chosen, selected: true }, `${chosen}  ·  nothing in this window`));
    }
    picker.replaceChildren(...options);
    picker.disabled = !options.length;
    body.replaceChildren(result.item
      ? figureCard("item", { window: result.window, item: result.item }, ctx, episode)
      : h("p", { class: "hl-empty" }, "No item was sold, farmed, crafted or bought in this window."));
  }

  picker.addEventListener("change", () => {
    saveChartSetting(episode, "item", { name: picker.value });
    load(picker.value);
  });
  load(episode.chart_settings.item?.name);
}

// Several items side by side, in the order they were added. Until any are chosen the
// best sellers are shown, and choosing starts from them.
function compareItems(episode, ctx, section, controls, body) {
  const chips = h("div", { class: "compare-chips" });
  const picker = h("select", { class: "item-select compare-add", "aria-label": "Add an item to compare", disabled: true });
  controls.replaceChildren(chips, picker);
  let shown = [];

  const choose = (names) => {
    saveChartSetting(episode, "compare", { names });
    load();
  };

  async function load() {
    section.classList.add("loading");
    const names = episode.chart_settings.compare?.names;
    const params = new URLSearchParams({ window: episode.window });
    if (names) {
      params.set("chosen", "1");
      names.forEach((name) => params.append("name", name));
    }
    const result = await attempt(() => api("GET", `/api/data/${episode.source}/compare?${params}`));
    section.classList.remove("loading");
    if (!result || result.empty || !picker.isConnected) return;
    shown = result.items.map((row) => row.name);
    chips.replaceChildren(...result.items.map((row) => h("span", { class: "compare-chip" },
      row.icon ? h("img", { class: "item-icon", src: row.icon, alt: "" }) : h("span", { class: "item-icon" }),
      h("span", { class: "compare-chip-name" }, row.name),
      h("button", { class: "icon-button", "aria-label": `Stop comparing ${row.name}`, title: "Remove",
        onclick: () => choose(shown.filter((name) => name !== row.name)) }, "×"))));
    const full = shown.length >= result.limit;
    const left = result.choices.filter((choice) => !shown.includes(choice.name));
    picker.replaceChildren(
      h("option", { value: "", selected: true }, full ? `Up to ${result.limit} items` : left.length ? "Add an item…" : "No other items in this window"),
      ...left.map((choice) => h("option", { value: choice.name }, choiceLabel(choice))));
    picker.disabled = full || !left.length;
    body.replaceChildren(result.items.length
      ? figureCard("compare", { window: result.window, items: result.items }, ctx, episode)
      : h("p", { class: "hl-empty" }, "Add items above to compare them."));
  }

  picker.addEventListener("change", () => {
    if (picker.value) choose([...shown, picker.value]);
  });
  load();
}

// ---------- Highlights ----------

const clockTime = (seconds) => new Date(seconds * 1000).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
const dayName = (seconds) => new Date(seconds * 1000).toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" });
function duration(seconds) {
  const hours = Math.floor(seconds / 3600), minutes = Math.floor(seconds / 60) % 60, rest = seconds % 60;
  const pad = (n) => String(n).padStart(2, "0");
  return hours ? `${hours}:${pad(minutes)}:${pad(rest)}` : `${minutes}:${pad(rest)}`;
}
const place = (item) => [item.zone, item.subzone].filter(Boolean).join(", ");
const shortName = (name) => (name || "").split("-")[0];

// Moments marked in game, on their own timeline so they never sit on the gold. The
// clock time and the time into the marker are what find the moment in the footage.
function highlightsCard(list, range) {
  const span = Math.max(1, range.end - range.start);
  const rows = list.map((item) => h("tr", {},
    h("td", { class: "num" }, String(item.number)),
    h("td", {}, h("span", { class: "hl-day" }, dayName(item.time)), " ", clockTime(item.time)),
    h("td", { class: "num" }, item.since == null ? "" : `+${duration(item.since)}`),
    h("td", {}, item.note || ""),
    h("td", { class: "hl-muted" }, place(item)),
    h("td", { class: "hl-muted" }, shortName(item.character))));
  const showTip = (item, event) => {
    tooltip.replaceChildren(
      h("div", { class: "tip-title" }, `Highlight ${item.number}  ·  ${dayName(item.time)} ${clockTime(item.time)}`),
      item.note ? h("div", {}, item.note) : "",
      h("div", { class: "tip-label" }, [item.since == null ? "" : `+${duration(item.since)} into ${item.marker}`, place(item), shortName(item.character)].filter(Boolean).join("  ·  ")));
    tooltip.hidden = false;
    const box = tooltip.getBoundingClientRect();
    tooltip.style.left = `${Math.min(innerWidth - box.width - 8, event.clientX + 14)}px`;
    tooltip.style.top = `${Math.max(8, event.clientY - box.height - 10)}px`;
  };
  const ticks = list.map((item, i) => h("button", {
    class: "hl-tick", style: `left: ${((item.time - range.start) / span) * 100}%`,
    "aria-label": `Highlight ${item.number} at ${clockTime(item.time)}${item.note ? `: ${item.note}` : ""}`,
    onmouseenter: (e) => showTip(item, e), onmousemove: (e) => showTip(item, e), onmouseleave: () => { tooltip.hidden = true; },
    onclick: () => {
      rows.forEach((row) => row.classList.remove("hl-picked"));
      rows[i].classList.add("hl-picked");
      rows[i].scrollIntoView({ block: "nearest", behavior: reducedMotion() ? "auto" : "smooth" });
    } }));
  const copyButton = h("button", { class: "button quiet", disabled: !list.length, onclick: async () => {
    const text = list.map((item) => [clockTime(item.time), item.since == null ? "" : `+${duration(item.since)}`,
      `Highlight ${item.number}`, item.note || "", place(item)].filter(Boolean).join("  ")).join("\n");
    await attempt(async () => {
      await navigator.clipboard.writeText(text);
      copyButton.textContent = "Copied";
      setTimeout(() => { copyButton.textContent = "Copy list"; }, 1500);
    });
  } }, "Copy list");
  return h("section", { class: "figure-card highlights-card", "aria-label": "Highlights" },
    h("div", { class: "hl-head" },
      h("h2", {}, "Highlights"),
      h("span", { class: "hl-muted" }, list.length ? `${list.length} in this window` : "None in this window"),
      h("span", { class: "spacer" }), copyButton),
    h("div", { class: "hl-track" }, ticks),
    h("div", { class: "hl-ends" }, h("span", {}, `${dayName(range.start)} ${clockTime(range.start)}`), h("span", {}, `${dayName(range.end)} ${clockTime(range.end)}`)),
    list.length
      ? h("div", { class: "table-wrap" }, h("table", { class: "data-table" },
        h("thead", {}, h("tr", {}, ["#", "Time", "Into marker", "Note", "Where", "Character"].map((c, i) => h("th", { class: i === 0 || i === 2 ? "num" : "", scope: "col" }, c)))),
        h("tbody", {}, rows)))
      : h("p", { class: "hl-empty" }, "In game, mark a moment with the Forever Ledger key binding, Shift-click on the minimap button, or /fl highlight with an optional note."));
}

const DURATIONS = [1.5, 3, 5, 8, 12];
const AXIS_MODES = [["zero", "Zero"], ["fit", "Fit"], ["custom", "Custom"]];
const reducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

// Plays a figure's frames, and keeps its button and scrubber in step.
function createPlayer(onFrame, onState) {
  let progress = 1, playing = false, seconds = 3, last = 0, raf = 0;
  const tick = (now) => {
    if (!playing) return;
    progress = Math.min(1, progress + (now - last) / (seconds * 1000));
    last = now;
    onFrame(progress);
    onState(progress, playing);
    if (progress >= 1) {
      playing = false;
      onState(progress, playing);
      return;
    }
    raf = requestAnimationFrame(tick);
  };
  const stop = () => {
    playing = false;
    cancelAnimationFrame(raf);
  };
  return {
    play(fromStart = false) {
      stop();
      if (fromStart || progress >= 1) progress = 0;
      onFrame(progress);
      playing = true;
      last = performance.now();
      onState(progress, playing);
      raf = requestAnimationFrame(tick);
    },
    pause() {
      stop();
      onState(progress, playing);
    },
    seek(value) {
      stop();
      progress = value;
      onFrame(progress);
      onState(progress, playing);
    },
    setSeconds(value) { seconds = value; },
    setFrames(next) { onFrame = next; },
    stop,
    get playing() { return playing; },
  };
}

function figureCard(kind, data, ctx, episode) {
  const settings = () => ({ mode: "zero", gold: 0, seconds: 3, ...episode.chart_settings[kind] });
  const saveSettings = (changes) => {
    episode.chart_settings = { ...episode.chart_settings, [kind]: { ...settings(), ...changes } };
    saveLater(`charts-${episode.id}`, () => api("PATCH", `/api/episodes/${episode.id}`, { chart_settings: episode.chart_settings }));
  };
  let tall = false;

  const holder = h("div", { class: "figure-holder" });
  const playButton = h("button", { class: "button play-button", onclick: () => {
    if (player.playing) player.pause(); else player.play();
  } }, "Play");
  const scrubber = h("input", { type: "range", class: "scrubber", min: 0, max: 1000, value: 1000, "aria-label": `Position in the ${CHARTS[kind]} animation`,
    oninput: (e) => player.seek(Number(e.target.value) / 1000) });
  const player = createPlayer(() => {}, (progress, playing) => {
    scrubber.value = String(Math.round(progress * 1000));
    playButton.textContent = playing ? "Pause" : progress >= 1 ? "Replay" : "Play";
  });
  player.setSeconds(settings().seconds);

  const axisWarning = h("span", { class: "axis-warning", hidden: true }, "Above the data, so ignored");

  function paint() {
    const { svg, hover, anim, axis } = renderForScreen(kind, data, ctx, { tall, axis: settings() });
    holder.classList.toggle("tall", tall);
    holder.innerHTML = svg; // Built by charts.js, which escapes every label.
    const svgEl = holder.firstElementChild;
    svgEl.setAttribute("aria-label", CHARTS[kind]);
    svgEl.removeAttribute("width");
    svgEl.removeAttribute("height");
    attachHover(svgEl, hover, tooltip);
    player.setFrames(createFrames(svgEl, anim));
    player.seek(1);
    axisWarning.hidden = !axis.ignored;
  }

  const pressed = (button, on) => button.setAttribute("aria-pressed", String(on));

  const viewButtons = [["wide", "Wide"], ["tall", "Vertical"]].map(([id, label2]) => {
    const button = h("button", { onclick: () => {
      tall = id === "tall";
      viewButtons.forEach((b, i) => pressed(b, (i === 1) === tall));
      paint();
    } }, label2);
    pressed(button, id === "wide");
    return button;
  });

  const customInput = h("input", { type: "number", class: "axis-input", min: 0, step: "any", value: settings().gold || "", placeholder: "0",
    "aria-label": `${CHARTS[kind]} axis start in gold`,
    oninput: (e) => {
      const gold = Number(e.target.value);
      if (!Number.isFinite(gold) || gold < 0) return;
      saveSettings({ mode: "custom", gold });
      paint();
    } });
  const customField = h("span", { class: "axis-custom" }, customInput, h("img", { class: "coin", src: COINS.gold, alt: "gold" }));
  const axisButtons = AXIS_MODES.map(([mode, label2]) => {
    const button = h("button", { onclick: () => {
      saveSettings({ mode });
      paintAxisMode();
      paint();
      if (mode === "custom") customInput.focus();
    } }, label2);
    return button;
  });
  function paintAxisMode() {
    const { mode } = settings();
    axisButtons.forEach((button, i) => pressed(button, AXIS_MODES[i][0] === mode));
    customField.hidden = mode !== "custom";
  }
  paintAxisMode();

  const durationSelect = h("select", { "aria-label": `${CHARTS[kind]} animation length`, onchange: (e) => {
    const seconds = Number(e.target.value);
    player.setSeconds(seconds);
    saveSettings({ seconds });
    paintVideoTitle();
  } }, DURATIONS.map((seconds) => h("option", { value: seconds, selected: seconds === settings().seconds }, `${seconds} s`)));

  const tableHost = h("div", { class: "table-wrap", hidden: true });
  const tableButton = h("button", { class: "button quiet", "aria-expanded": "false", onclick: () => {
    const opening = tableHost.hidden;
    if (opening && !tableHost.firstChild) tableHost.append(dataTable(tableFor(kind, data, settings())));
    tableHost.hidden = !opening;
    tableButton.setAttribute("aria-expanded", String(opening));
    tableButton.textContent = opening ? "Hide table" : "Show table";
  } }, "Show table");

  const size = episode.format === "short" ? "1080 \u00d7 1920" : "1920 \u00d7 1080";
  const shape = episode.format === "short" ? "vertical" : "widescreen";
  // A value chart showing one part says which in its file name.
  const chartName = () => (kind === "value" && valuePart(settings()) !== "total" ? `${kind}-${valuePart(settings())}` : kind);
  const fileName = (extension) => `${`${episode.title}-${chartName()}-${episode.source}`.replace(/[^\w-]+/g, "-").toLowerCase()}.${extension}`;
  const exportButton = h("button", { class: "button", title: `The finished chart as a ${shape} image`, onclick: async () => {
    await attempt(() => exportPng(kind, data, ctx, episode.format, settings(), fileName("png")));
  } }, "Export PNG");

  // Clicking again while a video is being made cancels it.
  let videoJob = null;
  const videoLabel = "Export MP4";
  const videoButton = h("button", { class: "button video-button", onclick: async () => {
    if (videoJob) {
      videoJob.abort();
      return;
    }
    videoJob = new AbortController();
    videoButton.textContent = "Cancel 0%";
    try {
      const blob = await renderVideo(kind, data, ctx, episode.format, settings(), settings().seconds, {
        signal: videoJob.signal,
        onProgress: (share) => { videoButton.textContent = `Cancel ${Math.floor(share * 100)}%`; },
      });
      saveBlob(blob, fileName("mp4"));
    } catch (err) {
      if (!(err instanceof VideoCancelled)) showError(err.message);
    } finally {
      videoJob = null;
      videoButton.textContent = videoLabel;
    }
  } }, videoLabel);
  const paintVideoTitle = () => {
    videoButton.title = `The animation as a ${shape} video: ${settings().seconds} seconds, then the finished chart for ${VIDEO_HOLD_SECONDS} more`;
  };
  paintVideoTitle();

  const breakdown = kind === "costs" || kind === "revenue";
  const characterRow = breakdown ? characterPicker(data[kind], settings, saveSettings, () => {
    paint();
    if (tableHost.firstChild) tableHost.replaceChildren(dataTable(tableFor(kind, data, settings())));
  }) : "";
  const partRow = kind === "value" ? valuePartPicker(settings, saveSettings, paint) : "";

  const card = h("article", { class: "figure-card" }, holder, characterRow, partRow,
    h("div", { class: "figure-foot" },
      playButton, scrubber, durationSelect,
      h("div", { class: "segmented", role: "group", "aria-label": "Chart layout" }, viewButtons),
      // Bars of cost and item counts always start from nothing, so those have no axis choice.
      ...(breakdown || kind === "item" || kind === "compare" ? [] : [
        h("span", { class: "foot-label" }, "Axis from"),
        h("div", { class: "segmented", role: "group", "aria-label": "Where the vertical axis starts" }, axisButtons),
        customField, axisWarning]),
      h("span", { class: "spacer" }), tableButton, h("span", { class: "foot-label" }, size), exportButton, videoButton),
    tableHost);

  paint();
  // Each chart draws itself the first time it comes into view.
  if (!reducedMotion() && "IntersectionObserver" in window) {
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) {
        observer.disconnect();
        player.play(true);
      }
    }, { threshold: 0.35 });
    observer.observe(card);
  }
  return card;
}

// The value chart's choice of the total or one of the parts it adds up.
function valuePartPicker(settings, saveSettings, redraw) {
  const keys = Object.keys(VALUE_PARTS);
  const buttons = keys.map((key) => h("button", { onclick: () => {
    saveSettings({ show: key });
    paintPicker();
    redraw();
  } }, VALUE_PARTS[key].label));
  const paintPicker = () => buttons.forEach((button, i) => button.setAttribute("aria-pressed", String(keys[i] === valuePart(settings()))));
  paintPicker();
  return h("div", { class: "figure-options" },
    h("div", { class: "segmented", role: "group", "aria-label": "Figure to show" }, buttons));
}

// A breakdown chart's choice of everyone together or chosen characters, each shown with
// the colour its bars get. None ticked is never allowed: the last tick stays.
function characterPicker(breakdown, settings, saveSettings, redraw) {
  const characters = breakdown.characters ?? [];
  const everyone = characters.map((c) => c.id);
  const modeButtons = [[false, "All characters"], [true, "By character"]].map(([split, text]) => h("button", { onclick: () => {
    saveSettings({ split });
    update();
  } }, text));
  const chips = h("div", { class: "character-chips" });
  const allButton = h("button", { class: "button quiet", onclick: () => { saveSettings({ characters: [] }); update(); } }, "Tick all");

  function toggle(id, on) {
    const stored = settings().characters ?? [];
    const base = stored.length ? stored : everyone;
    const next = on ? [...new Set([...base, id])] : base.filter((other) => other !== id);
    if (!next.some((other) => everyone.includes(other))) {
      paintPicker();
      return;
    }
    saveSettings({ characters: everyone.every((other) => next.includes(other)) ? [] : next });
    update();
  }

  function paintPicker() {
    const { split, characters: chosen = [] } = settings();
    modeButtons.forEach((button, i) => button.setAttribute("aria-pressed", String((i === 1) === Boolean(split))));
    const groups = breakdownGroups(breakdown, settings()) ?? [];
    chips.hidden = !split;
    allButton.hidden = !split || !chosen.length || everyone.every((id) => chosen.includes(id));
    chips.replaceChildren(...(characters.length ? characters.map((c) => {
      const swatch = h("span", { class: "chip-swatch" });
      const colour = groups.find((g) => g.ids.includes(c.id))?.color;
      if (colour) swatch.style.background = colour;
      return h("label", { class: "character-chip" },
        h("input", { type: "checkbox", checked: !chosen.length || chosen.includes(c.id), "aria-label": `Show ${c.name}`,
          onchange: (e) => toggle(c.id, e.target.checked) }),
        swatch, c.name);
    }) : [h("span", { class: "foot-label" }, "No character has any in this window")]));
  }

  function update() {
    paintPicker();
    redraw();
  }

  paintPicker();
  return h("div", { class: "figure-options" },
    h("div", { class: "segmented", role: "group", "aria-label": "Show figures for" }, modeButtons), chips, allButton);
}

function dataTable({ columns, numeric, rows }) {
  const cls = (i) => (numeric.includes(i) ? "num" : "");
  const cell = (value) => {
    if (value && typeof value === "object" && "copper" in value) return moneyNode(value.copper, { signed: value.signed });
    if (value && typeof value === "object") {
      return h("span", { class: "item-cell" }, value.icon ? h("img", { class: "item-icon", src: value.icon, alt: "" }) : h("span", { class: "item-icon" }), value.text);
    }
    return value;
  };
  return h("table", { class: "data-table" },
    h("thead", {}, h("tr", {}, columns.map((c, i) => h("th", { class: cls(i), scope: "col" }, c)))),
    h("tbody", {}, rows.map((row) => h("tr", {}, row.map((value, i) => h("td", { class: cls(i) }, cell(value)))))));
}

// ---------- Visuals ----------

const COPPER_PER = { gold: 10000, silver: 100, copper: 1 };
const visualItems = new Map(); // "source:id" -> a promise of the item.

function loadVisualItem(source, visual) {
  const key = `${source}:${visual.item_id}`;
  if (!visualItems.has(key)) {
    const query = `id=${visual.item_id}&name=${encodeURIComponent(visual.name)}`;
    const request = api("GET", `/api/visual/${source}/item?${query}`).then((item) => {
      // A tooltip that couldn't be fetched is tried again the next time the tab opens.
      if (!item.found) visualItems.delete(key);
      return item;
    }, (err) => { visualItems.delete(key); throw err; });
    visualItems.set(key, request);
  }
  return visualItems.get(key);
}

const newKey = () => (crypto.randomUUID?.() ?? `${Date.now()}-${Math.random()}`).slice(0, 36);

// Item cards to overlay in the video: any item with its tooltip and a gold gain or loss,
// or a gold amount on its own. Top items wait on the right, to drag in or click.
function renderVisuals(pane, episode, tabButton) {
  const save = () => {
    tabButton.textContent = `Visuals (${episode.visuals.length})`;
    saveLater(`visuals-${episode.id}`, () => api("PATCH", `/api/episodes/${episode.id}`, { visuals: episode.visuals }));
  };
  const list = h("div", { class: "visual-list" });
  const dropSlot = h("div", { class: "visual-drop-slot", "aria-hidden": "true" }, "Drop here for a new card");
  const paintList = () => {
    list.replaceChildren(...(episode.visuals.length
      ? episode.visuals.map((visual) => visualCard(visual, episode, save, paintList))
      : [h("div", { class: "empty-state" }, h("h2", {}, "No cards yet"),
        h("p", {}, "Search for any item above, or drag one in from the top items. Its tooltip appears with a gold amount beside it, ready to export for the video. A gold amount can also go on its own."))]),
    dropSlot);
  };
  // `found` is {item_id, name, copper}, with item_id null for the gold amount alone.
  const addCard = (found) => {
    episode.visuals = [...episode.visuals, { key: newKey(), item_id: found.item_id, name: found.name, copper: found.copper ?? 0, place: "right", sell: true, ilvl: true }];
    save();
    paintList();
    list.querySelector(".visual-card:last-of-type .visual-amount")?.focus();
  };
  // An item dropped on a card takes the place of its item, and fills in the amount if it has none.
  const swapItem = (key, found) => {
    const visual = episode.visuals.find((v) => v.key === key);
    if (!visual) return;
    Object.assign(visual, { item_id: found.item_id, name: found.name }, visual.copper ? {} : { copper: found.copper ?? 0 });
    save();
    paintList();
  };
  const goldButton = h("button", { class: "button", title: "A card with the gold amount alone, no item",
    onclick: () => addCard({ item_id: null, name: "", copper: 0 }) }, icon("plus"), "Gold amount only");
  const work = h("div", { class: "visual-main" }, itemSearch(episode, (found) => addCard({ ...found, copper: 0 }), goldButton), list);
  itemDrops(work, (found, card) => (card ? swapItem(card.dataset.key, found) : addCard(found)));
  pane.replaceChildren(h("div", { class: "visual-layout" }, work, itemTray(episode, addCard)));
  paintList();
}

const DRAG_TYPE = "application/x-ledger-item";

// Takes items dragged from the tray: onto a card to swap its item, anywhere else to add one.
function itemDrops(zone, onDrop) {
  let marked = null;
  const mark = (el) => {
    if (marked === el) return;
    marked?.classList.remove("drop-over");
    marked = el;
    el?.classList.add("drop-over");
  };
  const carries = (e) => [...(e.dataTransfer?.types ?? [])].includes(DRAG_TYPE);
  const targetOf = (e) => e.target.closest?.(".visual-card") || zone.querySelector(".visual-drop-slot");
  zone.addEventListener("dragover", (e) => {
    if (!carries(e)) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "copy";
    mark(targetOf(e));
  });
  zone.addEventListener("dragleave", (e) => { if (!zone.contains(e.relatedTarget)) mark(null); });
  zone.addEventListener("drop", (e) => {
    if (!carries(e)) return;
    e.preventDefault();
    const card = e.target.closest?.(".visual-card");
    mark(null);
    let found;
    try { found = JSON.parse(e.dataTransfer.getData(DRAG_TYPE)); } catch { return; }
    if (found && Number.isInteger(found.item_id)) onDrop(found, card);
  });
}

const TRAY_GROUPS = [["sales", "Most sold", "revenue", "Units sold. A card made from one shows what they sold for, after the auction house cut"],
  ["profit", "Most profit", "net", "Net: money in less money out"],
  ["loss", "Biggest loss", "net", "Net: money in less money out"]];

// The items with the most sales, profit and loss in the episode's window, as icons to drag
// onto the cards. A click or Enter adds one as a new card, with its amount filled in.
function itemTray(episode, onPick) {
  const body = h("div", { class: "tray-body" }, h("p", { class: "tray-note" }, "Loading top items…"));
  const tray = h("aside", { class: "visual-tray", "aria-label": "Top items" }, h("h2", {}, "Top items"), body);
  // A sales row shows units sold. Its card still gets the gold they brought in.
  const tile = (row, copper, units) => {
    const found = { item_id: row.item_id, name: row.name, copper };
    const count = `${units?.toLocaleString("en-US")} sold`;
    return h("button", {
      class: "tray-item", draggable: true, title: `Drag onto a card, or click to add ${row.name} as a new card`,
      "aria-label": `Add ${row.name}, ${units == null ? "" : `${count} for `}${moneyWords(copper, { signed: true })}`,
      ondragstart: (e) => {
        e.dataTransfer.setData(DRAG_TYPE, JSON.stringify(found));
        e.dataTransfer.setData("text/plain", row.name);
        e.dataTransfer.effectAllowed = "copy";
        tray.closest(".visual-layout")?.classList.add("dragging");
      },
      ondragend: () => tray.closest(".visual-layout")?.classList.remove("dragging"),
      onclick: () => onPick(found),
    },
    row.icon ? h("img", { class: "tray-icon", src: row.icon, alt: "", draggable: false }) : h("span", { class: "tray-icon" }),
    h("span", { class: "tray-name" }, row.name),
    units == null
      ? h("span", { class: `tray-amount ${copper < 0 ? "loss" : "gain"}` }, moneyNode(copper, { signed: true }))
      : h("span", { class: "tray-amount", title: `${count} for ${moneyWords(copper)}` }, count));
  };
  api("GET", `/api/visual/${episode.source}/top?window=${encodeURIComponent(episode.window)}`).then((result) => {
    if (result.empty) {
      body.replaceChildren(h("p", { class: "tray-note" }, "Nothing imported for this source yet."));
      return;
    }
    body.replaceChildren(h("p", { class: "tray-note" }, `In ${result.window.label}. Drag onto a card to swap its item, or below the cards for a new one.`),
      ...TRAY_GROUPS.map(([key, heading, field, about]) => h("section", { class: "tray-group" },
        h("h3", { title: about }, heading),
        result[key].length ? h("div", { class: "tray-items" }, result[key].map((row) => tile(row, row[field], key === "sales" ? row.sold : null)))
          : h("p", { class: "tray-note" }, "None in this window"))));
  }, (err) => body.replaceChildren(h("p", { class: "tray-note" }, err.message)));
  return tray;
}

// Finds items in this source's ledger first, then on Wowhead, as you type.
function itemSearch(episode, onPick, extra) {
  const input = h("input", { type: "text", class: "visual-search-input", placeholder: "Search for any item, e.g. Linen Cloth",
    "aria-label": "Search for an item", autocomplete: "off", role: "combobox", "aria-expanded": "false", "aria-controls": "visual-results" });
  const results = h("ul", { class: "visual-results", id: "visual-results", role: "listbox", hidden: true });
  let timer, asked = 0, active = -1, found = [];
  const open = () => { results.hidden = false; input.setAttribute("aria-expanded", "true"); };
  const close = () => { results.hidden = true; input.setAttribute("aria-expanded", "false"); active = -1; };
  const pick = (item) => { close(); input.value = ""; found = []; onPick(item); };
  const mark = (next) => {
    active = next;
    [...results.children].forEach((li, i) => li.setAttribute("aria-selected", String(i === active)));
    results.children[active]?.scrollIntoView({ block: "nearest" });
  };
  async function search() {
    const words = input.value.trim();
    const ticket = ++asked;
    const reply = await attempt(() => api("GET", `/api/visual/${episode.source}/search?q=${encodeURIComponent(words)}`));
    if (!reply || ticket !== asked) return;
    found = reply.items;
    const row = (item) => h("li", { role: "option", "aria-selected": "false", onmousedown: (e) => { e.preventDefault(); pick(item); } },
      h("span", { class: "visual-result-name", style: item.quality == null ? "" : `color: ${QUALITY_COLORS[item.quality]}` }, item.name),
      h("span", { class: "visual-result-tag" }, item.in_ledger ? "In your ledger" : "Wowhead"));
    results.replaceChildren(...(found.length ? found.map(row)
      : [h("li", { class: "visual-result-none" }, words.length < 2 ? "Type at least two letters to search Wowhead too"
        : reply.online ? "No item found by that name" : "Not in this ledger, and Wowhead search is off (--offline)")]));
    open();
    active = -1;
  }
  input.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(search, 250); });
  input.addEventListener("focus", () => { if (found.length) open(); else search(); });
  input.addEventListener("blur", close);
  input.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown" && found.length) { e.preventDefault(); open(); mark(Math.min(found.length - 1, active + 1)); }
    if (e.key === "ArrowUp" && found.length) { e.preventDefault(); mark(Math.max(0, active - 1)); }
    if (e.key === "Enter" && found[Math.max(0, active)]) { e.preventDefault(); pick(found[Math.max(0, active)]); }
    if (e.key === "Escape") close();
  });
  return h("div", { class: "visual-search" }, h("span", { class: "filter-label" }, "Add item"),
    h("div", { class: "visual-search-box" }, input, results), extra,
    h("span", { class: "figure-note" }, `Tooltips from Wowhead's ${episode.source === "tbc" ? "TBC" : "Forever"} data`));
}

function visualCard(visual, episode, save, repaintList) {
  const holder = h("div", { class: "visual-holder" });
  const note = h("p", { class: "visual-note", hidden: true });
  const goldOnly = visual.item_id == null;
  const label = goldOnly ? "the gold amount" : visual.name;
  let item = null, ready = goldOnly;
  const update = (changes) => {
    Object.assign(visual, changes);
    save();
    paint();
  };

  let drawn = 0;
  async function paint() {
    if (!ready) return;
    const ticket = ++drawn;
    const density = 2 * (window.devicePixelRatio || 1);
    const canvas = await drawVisual(item, visual, density);
    if (ticket !== drawn) return;
    canvas.style.width = `${(canvas.width / density) * 1.25}px`; // A little larger than in the game.
    canvas.setAttribute("role", "img");
    if (goldOnly) {
      canvas.setAttribute("aria-label", `Gold amount: ${valueWords(visual.copper)}`);
    } else {
      const lines = shownLines(item, visual).slice(1).map((line) => line.left.map((s) => s.text).join(""));
      canvas.setAttribute("aria-label", `${item.name}. ${lines.join(". ")}. ${valueWords(visual.copper)}`);
    }
    holder.replaceChildren(canvas);
  }

  // The amount is typed as gold, silver and copper, with gain or loss chosen beside it.
  const abs = Math.abs(visual.copper);
  const pieces = { gold: Math.floor(abs / 10000), silver: Math.floor(abs / 100) % 100, copper: abs % 100 };
  let sign = visual.copper < 0 ? -1 : 1;
  const amount = () => Object.entries(inputs).reduce((sum, [coin, el]) =>
    sum + Math.min(coin === "gold" ? 99999999 : 99, Math.max(0, Math.floor(Number(el.value) || 0))) * COPPER_PER[coin], 0);
  const commit = () => update({ copper: sign * amount() });
  const inputs = Object.fromEntries(Object.keys(pieces).map((coin) => [coin, h("input", {
    type: "number", class: `visual-amount ${coin}`, min: 0, max: coin === "gold" ? 99999999 : 99, step: 1,
    value: pieces[coin] || "", placeholder: "0", "aria-label": `${coin[0].toUpperCase()}${coin.slice(1)} for ${label}`, oninput: commit })]));
  const signButtons = [["Gain", 1], ["Loss", -1]].map(([text, value]) => h("button", {
    "aria-pressed": String(value === sign),
    onclick: () => {
      sign = value;
      signButtons.forEach((b, i) => b.setAttribute("aria-pressed", String((i === 1) === (sign < 0))));
      commit();
    } }, text));
  const placeButtons = [["right", "Beside"], ["below", "Below"]].map(([place, text], index) => h("button", {
    "aria-pressed": String((visual.place || "right") === place),
    onclick: () => {
      placeButtons.forEach((b, i) => b.setAttribute("aria-pressed", String(i === index)));
      update({ place });
    } }, text));
  const toggle = (flag, text) => h("label", { class: "character-chip" },
    h("input", { type: "checkbox", checked: visual[flag] !== false, onchange: (e) => update({ [flag]: e.target.checked }) }), text);

  const fileName = () => `${`${episode.title}-${goldOnly ? `gold-${valueWords(visual.copper)}` : item?.name || visual.name}`
    .replace(/[^\w-]+/g, "-").toLowerCase()}.png`;
  const exportButton = h("button", { class: "button", disabled: !goldOnly, title: "A transparent PNG at three times the game's tooltip size, to lay over footage",
    onclick: () => attempt(async () => saveBlob((await visualBlob(item, visual)).blob, fileName())) }, "Export PNG");
  const copyButton = h("button", { class: "button quiet", disabled: !goldOnly, title: "Copies the transparent PNG, to paste into an editor",
    onclick: () => attempt(async () => {
      const { blob } = await visualBlob(item, visual);
      await navigator.clipboard.write([new ClipboardItem({ "image/png": blob })]);
      copyButton.textContent = "Copied";
      setTimeout(() => { copyButton.textContent = "Copy image"; }, 1500);
    }) }, "Copy image");
  const removeButton = h("button", { class: "icon-button", title: "Remove this card", "aria-label": `Remove ${label}`, onclick: () => {
    episode.visuals = episode.visuals.filter((other) => other.key !== visual.key);
    save();
    repaintList();
  } }, icon("trash"));

  const coinField = (coin) => h("span", { class: "axis-custom" }, inputs[coin], h("img", { class: "coin", src: COINS[coin], alt: coin }));
  const card = h("article", { class: `figure-card visual-card${goldOnly ? " gold-only" : ""}`, "data-key": visual.key },
    h("div", { class: "visual-stage" }, holder), note,
    h("div", { class: "figure-foot" },
      h("span", { class: "foot-label" }, goldOnly ? "Gold only" : "Amount"),
      h("div", { class: "segmented", role: "group", "aria-label": "Gain or loss" }, signButtons),
      coinField("gold"), coinField("silver"), coinField("copper"),
      goldOnly ? null : [
        h("div", { class: "segmented", role: "group", "aria-label": "Where the amount goes" }, placeButtons),
        toggle("ilvl", "Item level"), toggle("sell", "Sell price")],
      h("span", { class: "spacer" }), copyButton, exportButton, removeButton));

  if (goldOnly) {
    paint();
    return card;
  }
  holder.append(h("div", { class: "visual-note" }, `Loading ${visual.name}…`));
  loadVisualItem(episode.source, visual).then((loaded) => {
    item = loaded;
    ready = true;
    exportButton.disabled = copyButton.disabled = false;
    if (!loaded.found) {
      note.textContent = "Wowhead's tooltip couldn't be fetched (offline, or no such item), so only the name shows. It's tried again next time this tab opens.";
      note.hidden = false;
    }
    paint();
  }, (err) => {
    holder.replaceChildren(h("p", { class: "visual-note" }, err.message));
  });
  return card;
}

// ---------- Sources ----------

function renderSources() {
  state.episode = null;
  const fileRow = (source, file) => h("div", { class: "file-row" },
    h("span", { class: "file-path" }, file.path),
    h("span", { class: "file-state" }, file.status
      ? file.status.importing ? "Importing…" : file.status.ok ? `Imported ${new Date(file.status.at * 1000).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })}` : "Import failed"
      : "Waiting to import"),
    h("button", { class: "button quiet", onclick: async () => {
      const result = await attempt(() => api("POST", `/api/sources/${source.id}/files/remove`, { path: file.path }));
      if (result) { state.sources = result.sources; renderSidebar(); renderSources(); }
    } }, "Stop using"),
    file.status && !file.status.ok ? h("span", { class: "file-error" }, file.status.error) : null);

  const card = (source) => {
    const span = source.records ? `${compact(source.records)} records  ·  ${source.accounts} account${source.accounts === 1 ? "" : "s"}  ·  ${formatTime(source.first)} to ${formatTime(source.last)}` : "No records yet";
    const pathInput = h("input", { type: "text", placeholder: "Path to an account's SavedVariables\\ForeverLedger.lua", "aria-label": `File to add to ${source.label}` });
    return h("section", { class: "source-card" },
      h("div", { class: "source-head" }, h("h2", {}, source.label), h("span", { class: "source-stats" }, span),
        h("button", { class: "button", onclick: async () => {
          const result = await attempt(() => api("POST", `/api/sources/${source.id}/import`, {}));
          if (result) { state.sources = result.sources; renderSidebar(); renderSources(); }
        } }, source.id === "mock" ? "Regenerate" : "Import now")),
      source.id === "mock"
        ? h("p", { class: "source-hint" }, "Made-up data for designing charts. Charts made from it carry no label, so keep them out of published videos.")
        : [source.files.map((file) => fileRow(source, file)),
          source.files.length ? null : h("p", { class: "source-hint" }, source.id === "forever"
            ? "No Forever saved data found yet. It's picked up automatically once the addon has saved in the _forever_ client."
            : "No Anniversary saved data found. Add the file below."),
          h("form", { class: "add-file", onsubmit: async (e) => {
            e.preventDefault();
            const result = await attempt(() => api("POST", `/api/sources/${source.id}/files`, { path: pathInput.value }));
            if (result) { state.sources = result.sources; renderSidebar(); renderSources(); }
          } }, pathInput, h("button", { class: "button", type: "submit" }, "Add file"))]);
  };
  main.replaceChildren(h("div", { class: "page" },
    h("h1", {}, "Data sources"),
    h("p", { class: "lede" }, "Each source has its own database and is never merged with the others. An account already in one source is refused by the others. WoW's files are only ever read, and are re-imported shortly after the game saves them."),
    state.sources.map(card)));
}

function renderHome() {
  state.episode = null;
  const first = state.tree.flatMap((s) => s.episodes)[0];
  main.replaceChildren(h("div", { class: "page" },
    h("div", { class: "empty-state" },
      h("h2", {}, first ? "Pick an episode" : "Start with a series"),
      h("p", {}, first ? "Choose an episode from the sidebar to see its script, shots and data." : "Use the + beside Shorts or Longform to add a series or title."),
      first ? h("button", { class: "button", onclick: () => go(`#/episode/${first.id}/script`) }, `Open ${first.title}`) : null)));
}

// ---------- Start ----------

async function render() {
  await flushSaves();
  tooltip.hidden = true;
  const current = route();
  renderSidebar();
  if (current.view === "episode") await renderEpisode(current.id, current.tab);
  else if (current.view === "sources") { await attempt(refreshSources); renderSidebar(); renderSources(); }
  else renderHome();
}

window.addEventListener("hashchange", render);
window.addEventListener("focus", async () => {
  // Keeps the sidebar's record counts current after playing.
  await attempt(refreshSources);
  if (!sidebar.contains(document.activeElement) || document.activeElement.tagName !== "INPUT") renderSidebar();
});

await attempt(() => Promise.all([refreshTree(), refreshSources()]));
await render();
