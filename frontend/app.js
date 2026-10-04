"use strict";
/* Revive front end. No framework, no build step.
   Talks to the API in master §7.1: /api/health, /api/jobs, /api/jobs/{id}, /api/jobs/{id}/album,
   PATCH /api/jobs/{id}/items/{item}. */

const $ = (id) => document.getElementById(id);
const IMAGE_EXT = /\.(jpe?g|png|heic|heif|webp|bmp|gif|tiff?)$/i;
const POLL_MS = 1000;

const STAGE_LABELS = {
  queued: "Waiting for its turn",
  faces: "Fixing faces",
  upscaling: "Making sharper",
  captioning: "Writing a caption",
  done: "Done",
  failed: "Couldn't finish this one",
};

const state = {
  picked: [],          // [{key, file, url}]
  nextKey: 1,
  health: null,
  jobId: null,
  job: null,
  pollTimer: null,
  failedPolls: 0,
  viewerList: [],
  viewerIndex: 0,
  viewerOpener: null,
  saveTimer: null,
};

function el(tag, attrs, ...kids) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === false || v == null) continue;
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) node.append(kid instanceof Node ? kid : document.createTextNode(kid));
  return node;
}

function plural(n, one, many) { return `${n} ${n === 1 ? one : many}`; }

/* ---------------------------------------------------------------- notices */

function showNotice(msg) {
  const box = $("notice");
  box.textContent = msg || "";
  box.hidden = !msg;
}

/* ---------------------------------------------------------------- health */

async function loadHealth() {
  const banner = $("health-banner");
  const notes = [];
  try {
    const res = await fetch("/api/health");
    if (!res.ok) throw new Error(res.status);
    state.health = await res.json();
  } catch {
    state.health = null;
    notes.push("We can't reach Revive right now. Is it still running? Try closing this page and starting Revive again.");
  }
  const h = state.health;
  if (h) {
    if (!h.upscaler) notes.push("Photos can't be made sharper right now because the sharpening tool isn't ready. Please run the setup again.");
    setToggleAvailable("faces", h.faces, notes, "Face fixing is off because the face helper isn't ready.");
    setToggleAvailable("captions", h.gemma, notes, "Captions are off because the caption helper isn't running.");
  }
  banner.replaceChildren(...notes.map((n) => el("p", {}, n)));
  banner.hidden = notes.length === 0;
  updateStartState();
}

function setToggleAvailable(id, ok, notes, message) {
  const input = $(id);
  const row = $("opt-" + id);
  input.disabled = !ok;
  row.classList.toggle("is-off", !ok);
  if (!ok) {
    input.checked = false;
    notes.push(message);
  }
}

/* ---------------------------------------------------------------- picking files */

function isPhoto(file) {
  return (file.type && file.type.startsWith("image/")) || IMAGE_EXT.test(file.name);
}

function addFiles(files) {
  let skipped = 0;
  for (const file of files) {
    if (!isPhoto(file)) { skipped++; continue; }
    state.picked.push({ key: state.nextKey++, file, url: URL.createObjectURL(file) });
  }
  showNotice(skipped ? `${plural(skipped, "file wasn't a photo and was", "files weren't photos and were")} skipped.` : "");
  renderPreview();
}

function removePicked(key) {
  const i = state.picked.findIndex((p) => p.key === key);
  if (i >= 0) { URL.revokeObjectURL(state.picked[i].url); state.picked.splice(i, 1); }
  renderPreview();
}

function clearPicked() {
  state.picked.forEach((p) => URL.revokeObjectURL(p.url));
  state.picked = [];
  renderPreview();
}

function renderPreview() {
  const n = state.picked.length;
  $("preview").hidden = n === 0;
  $("options").hidden = n === 0;
  $("start-row").hidden = n === 0;
  $("dropzone").classList.toggle("is-compact", n > 0);
  $("preview-count").textContent = plural(n, "photo", "photos") + " ready";
  $("preview-strip").replaceChildren(...state.picked.map((p) =>
    el("li", {},
      el("img", { src: p.url, alt: p.file.name, title: p.file.name, onerror: (e) => { e.target.removeAttribute("src"); } }),
      el("button", { type: "button", class: "rm", "aria-label": `Remove ${p.file.name}`, onclick: () => removePicked(p.key) }, "✕"))));
  updateStartState();
}

function updateStartState() {
  const ok = state.picked.length > 0 && (!state.health || state.health.upscaler);
  $("btn-start").disabled = !ok;
}

/* Drag and drop, including folders. Entries must be grabbed synchronously during the drop event. */
function readAllEntries(reader) {
  return new Promise((resolve, reject) => {
    const all = [];
    const next = () => reader.readEntries((batch) => {
      if (!batch.length) resolve(all);
      else { all.push(...batch); next(); }
    }, reject);
    next();
  });
}

async function walkEntry(entry, out) {
  if (entry.isFile) {
    await new Promise((resolve) => entry.file((f) => { out.push(f); resolve(); }, resolve));
  } else if (entry.isDirectory) {
    const kids = await readAllEntries(entry.createReader()).catch(() => []);
    for (const kid of kids) await walkEntry(kid, out);
  }
}

async function filesFromDrop(dt) {
  const items = [...(dt.items || [])];
  if (items.length && items[0].webkitGetAsEntry) {
    const entries = items.filter((i) => i.kind === "file").map((i) => i.webkitGetAsEntry()).filter(Boolean);
    const out = [];
    for (const entry of entries) await walkEntry(entry, out);
    return out;
  }
  return [...dt.files];
}

function setupPicking() {
  const dz = $("dropzone");
  $("btn-photos").addEventListener("click", (e) => { e.stopPropagation(); $("input-photos").click(); });
  $("btn-folder").addEventListener("click", (e) => { e.stopPropagation(); $("input-folder").click(); });
  dz.addEventListener("click", () => $("input-photos").click());
  dz.addEventListener("keydown", (e) => {
    if (e.target === dz && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); $("input-photos").click(); }
  });
  for (const id of ["input-photos", "input-folder"]) {
    $(id).addEventListener("change", (e) => { addFiles([...e.target.files]); e.target.value = ""; });
  }
  let depth = 0;
  dz.addEventListener("dragenter", (e) => { e.preventDefault(); depth++; dz.classList.add("is-over"); });
  dz.addEventListener("dragover", (e) => { e.preventDefault(); });
  dz.addEventListener("dragleave", () => { if (--depth <= 0) { depth = 0; dz.classList.remove("is-over"); } });
  dz.addEventListener("drop", async (e) => {
    e.preventDefault(); depth = 0; dz.classList.remove("is-over");
    addFiles(await filesFromDrop(e.dataTransfer));
  });
  // A photo dropped beside the zone shouldn't make the browser navigate away.
  for (const type of ["dragover", "drop"]) window.addEventListener(type, (e) => { if (!dz.contains(e.target)) e.preventDefault(); });
  $("btn-clear").addEventListener("click", clearPicked);
}

/* ---------------------------------------------------------------- starting a job */

async function startJob() {
  if (!state.picked.length) return;
  const btn = $("btn-start");
  btn.disabled = true;
  btn.textContent = "Starting…";
  showNotice("");
  const form = new FormData();
  for (const p of state.picked) form.append("files", p.file, p.file.name);
  form.append("scale", document.querySelector("input[name=scale]:checked").value);
  form.append("faces", $("faces").checked && !$("faces").disabled ? "true" : "false");
  form.append("captions", $("captions").checked && !$("captions").disabled ? "true" : "false");
  try {
    const res = await fetch("/api/jobs", { method: "POST", body: form });
    if (!res.ok) throw new Error(await errorText(res));
    const { job_id } = await res.json();
    clearPicked();
    attachToJob(job_id);
  } catch (err) {
    showNotice(err.message && !/^Failed to fetch|NetworkError/i.test(err.message)
      ? err.message
      : "We couldn't start. Is Revive still running? Please try again.");
  } finally {
    btn.textContent = "Start";
    updateStartState();
  }
}

async function errorText(res) {
  try {
    const body = await res.json();
    if (typeof body.detail === "string") return body.detail;
  } catch { /* fall through */ }
  return "Something went wrong. Please try again.";
}

/* ---------------------------------------------------------------- polling & progress */

function attachToJob(jobId) {
  stopPolling();
  state.jobId = jobId;
  state.job = null;
  state.failedPolls = 0;
  history.replaceState(null, "", `#job=${jobId}`);
  $("step-pick").hidden = true;
  $("step-results").hidden = true;
  $("step-progress").hidden = false;
  $("progress-list").replaceChildren();
  poll();
}

function stopPolling() {
  clearTimeout(state.pollTimer);
  state.pollTimer = null;
}

async function poll() {
  const jobId = state.jobId;
  if (!jobId) return;
  try {
    const res = await fetch(`/api/jobs/${jobId}`);
    if (jobId !== state.jobId) return;
    if (res.status === 404) return leaveJob("We couldn't find that batch of photos. It may have been cleared. You can start a new one.");
    if (!res.ok) throw new Error(res.status);
    state.job = await res.json();
    state.failedPolls = 0;
    showNotice("");
    renderJob(state.job);
    if (state.job.status === "done" || state.job.status === "failed") return;
  } catch {
    if (++state.failedPolls >= 3) showNotice("Lost touch with Revive. We'll keep trying.");
  }
  state.pollTimer = setTimeout(poll, POLL_MS);
}

function leaveJob(message) {
  stopPolling();
  state.jobId = null;
  state.job = null;
  history.replaceState(null, "", location.pathname + location.search);
  $("step-progress").hidden = true;
  $("step-results").hidden = true;
  $("step-pick").hidden = false;
  showNotice(message || "");
  window.scrollTo(0, 0);
}

function stageText(item) {
  return STAGE_LABELS[item.status] || item.status;
}

function renderJob(job) {
  const finished = job.status === "done" || job.status === "failed";
  if (finished) {
    renderResults(job);
    return;
  }
  $("step-progress").hidden = false;
  $("step-results").hidden = true;
  renderProgress(job);
}

function etaText(job) {
  const timed = job.items.filter((it) => it.status === "done" && typeof it.seconds === "number");
  const left = job.total - job.done;
  if (!timed.length || left <= 0) return "";
  const avg = timed.reduce((sum, it) => sum + it.seconds, 0) / timed.length;
  const mins = Math.round((avg * left) / 60);
  if (mins < 1) return "· Less than a minute left";
  return `· About ${plural(mins, "minute", "minutes")} left`;
}

function renderProgress(job) {
  const pct = job.total ? Math.round((job.done / job.total) * 100) : 0;
  const bar = $("bar");
  bar.setAttribute("aria-valuenow", pct);
  bar.classList.toggle("working", job.status === "running" || job.status === "queued");
  $("bar-fill").style.width = `${Math.max(pct, 3)}%`;
  $("progress-count").textContent = `${job.done} of ${plural(job.total, "photo", "photos")} finished`;
  $("progress-eta").textContent = etaText(job);

  const list = $("progress-list");
  const known = new Map([...list.children].map((li) => [li.dataset.id, li]));
  for (const item of job.items) {
    let li = known.get(item.id);
    if (!li) {
      li = el("li", { class: "pitem", "data-id": item.id });
      list.append(li);
    }
    fillProgressRow(li, item);
  }
}

function fillProgressRow(li, item) {
  const active = ["faces", "upscaling", "captioning"].includes(item.status);
  li.className = "pitem" + (active ? " is-active" : "") + (item.status === "done" ? " is-done" : "") + (item.status === "failed" ? " is-failed" : "");
  const sig = [item.status, item.error, item.original_url].join("|");
  if (li.dataset.sig === sig) return;
  li.dataset.sig = sig;

  const thumb = item.original_url
    ? el("img", { src: item.original_url, alt: "", loading: "lazy", onerror: (e) => e.target.replaceWith(el("div", { class: "thumb-ph" })) })
    : el("div", { class: "thumb-ph" });
  const label = el("div", { class: "stage" + (active ? " dots" : "") }, stageText(item));
  const name = el("div", { class: "pname" }, el("div", { class: "fname", title: item.filename }, item.filename), label);
  if (item.status === "failed" && item.error) name.append(el("div", { class: "err" }, item.error));

  let mark;
  if (active) mark = el("div", { class: "spinner", role: "img", "aria-label": "Working" });
  else if (item.status === "done") mark = el("div", { class: "tick", "aria-hidden": "true", style: "color:var(--ok)" }, "✓");
  else if (item.status === "failed") mark = el("div", { class: "tick", "aria-hidden": "true", style: "color:var(--bad)" }, "!");
  else mark = el("div", { class: "tick", "aria-hidden": "true" }, "");
  li.replaceChildren(thumb, name, mark);
}

/* ---------------------------------------------------------------- results */

function hasResult(item) { return !!item.result_url; }

function renderResults(job) {
  stopPolling();
  $("step-progress").hidden = true;
  $("step-results").hidden = false;

  const good = job.items.filter(hasResult);
  const bad = job.items.filter((it) => it.status === "failed");
  const title = $("results-title");
  title.textContent = good.length ? "Your photos are ready" : "We couldn't finish any of the photos";
  $("results-sub").textContent = bad.length && good.length
    ? `${good.length} finished, ${bad.length} couldn't be finished.`
    : good.length ? plural(good.length, "photo", "photos") + ". Tap one to compare before and after." : "";

  const album = $("btn-album");
  album.href = `/api/jobs/${job.job_id}/album`;
  album.setAttribute("aria-disabled", good.length ? "false" : "true");

  $("results-grid").replaceChildren(...good.map((item, i) => resultCard(item, i)));

  const failedList = $("failed-list");
  const failedOnly = bad.filter((it) => !hasResult(it));
  $("failed-title").hidden = failedOnly.length === 0;
  failedList.hidden = failedOnly.length === 0;
  failedList.replaceChildren(...failedOnly.map((item) => {
    const li = el("li", { class: "pitem is-failed" });
    fillProgressRow(li, item);
    return li;
  }));
}

function resultCard(item, index) {
  const label = item.caption ? `Compare before and after: ${item.caption}` : `Compare before and after: ${item.filename}`;
  return el("li", { class: "card", "data-id": item.id },
    el("button", { type: "button", class: "open", "aria-label": label, onclick: (e) => openViewer(index, e.currentTarget) },
      el("img", { src: item.result_url, alt: item.caption || item.filename, loading: "lazy" })),
    el("div", { class: "cbody" },
      item.caption ? el("p", { class: "ccap" }, item.caption) : null,
      item.decade ? el("p", { class: "cdec" }, item.decade) : null,
      el("p", { class: "cname", title: item.filename }, item.filename)));
}

/* ---------------------------------------------------------------- before/after slider */

function makeSlider(beforeUrl, afterUrl, altText) {
  const before = el("img", { class: "ba-before", src: beforeUrl, alt: "", draggable: "false" });
  const after = el("img", { src: afterUrl, alt: altText || "", draggable: "false" });
  const root = el("div", {
    class: "ba", tabindex: "0", role: "slider",
    "aria-label": "Before and after. Left shows the original, right shows the sharper photo.",
    "aria-valuemin": "0", "aria-valuemax": "100", "aria-valuenow": "50", "aria-valuetext": "Half original, half sharper",
  },
  after, before,
  el("div", { class: "ba-line" }),
  el("div", { class: "ba-knob", "aria-hidden": "true" }, "↔"),
  el("span", { class: "ba-tag ba-tag-l" }, "Before"),
  el("span", { class: "ba-tag ba-tag-r" }, "After"));

  let pos = 50;
  const set = (value) => {
    pos = Math.min(100, Math.max(0, value));
    root.style.setProperty("--pos", pos + "%");
    root.setAttribute("aria-valuenow", Math.round(pos));
    root.setAttribute("aria-valuetext", pos <= 2 ? "All sharper" : pos >= 98 ? "All original" : `${Math.round(pos)} percent original`);
  };
  const fromEvent = (e) => {
    const r = root.getBoundingClientRect();
    set(((e.clientX - r.left) / r.width) * 100);
  };
  root.addEventListener("pointerdown", (e) => {
    if (e.button !== undefined && e.button > 0) return;
    root.setPointerCapture(e.pointerId);
    root.dataset.drag = "1";
    fromEvent(e);
    root.focus({ preventScroll: true });
  });
  root.addEventListener("pointermove", (e) => { if (root.dataset.drag) fromEvent(e); });
  const end = (e) => { delete root.dataset.drag; if (root.hasPointerCapture(e.pointerId)) root.releasePointerCapture(e.pointerId); };
  root.addEventListener("pointerup", end);
  root.addEventListener("pointercancel", end);
  root.addEventListener("keydown", (e) => {
    const step = e.shiftKey ? 10 : 2;
    const moves = { ArrowLeft: -step, ArrowDown: -step, ArrowRight: step, ArrowUp: step };
    if (e.key in moves) set(pos + moves[e.key]);
    else if (e.key === "Home") set(0);
    else if (e.key === "End") set(100);
    else if (e.key === "PageDown") set(pos - 10);
    else if (e.key === "PageUp") set(pos + 10);
    else return;
    e.preventDefault();
    e.stopPropagation();
  });
  set(50);
  root.setPosition = set;
  return root;
}

/* ---------------------------------------------------------------- viewer */

function openViewer(index, opener) {
  if (!state.job) return;
  state.viewerList = state.job.items.filter(hasResult);
  state.viewerOpener = opener || null;
  $("viewer").hidden = false;
  document.body.style.overflow = "hidden";
  showViewerItem(index);
  $("v-close").focus();
}

function showViewerItem(index) {
  const list = state.viewerList;
  state.viewerIndex = Math.min(Math.max(index, 0), list.length - 1);
  const item = list[state.viewerIndex];
  $("v-stage").replaceChildren(makeSlider(item.original_url, item.result_url, item.caption || item.filename));
  const bits = [`Photo ${state.viewerIndex + 1} of ${list.length}`];
  if (item.decade) bits.push(item.decade);
  if (item.out_width) bits.push(`${item.width}×${item.height} → ${item.out_width}×${item.out_height}`);
  if (item.faces_found) bits.push(plural(item.faces_found, "face fixed", "faces fixed"));
  $("v-meta").textContent = bits.join(" · ");
  const cap = $("v-caption");
  cap.value = item.caption || "";
  cap.dataset.id = item.id;
  const canCaption = !!(state.job.options && state.job.options.captions) || !!item.caption;
  cap.parentElement.hidden = !canCaption;
  $("v-save").textContent = "";
  $("v-prev").disabled = state.viewerIndex === 0;
  $("v-next").disabled = state.viewerIndex === list.length - 1;
  $("viewer").scrollTop = 0;
}

async function saveCaption() {
  const cap = $("v-caption");
  const item = state.viewerList.find((it) => it.id === cap.dataset.id);
  if (!item || (item.caption || "") === cap.value.trim()) return;
  const text = cap.value.trim();
  $("v-save").textContent = "Saving…";
  try {
    const res = await fetch(`/api/jobs/${state.jobId}/items/${item.id}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ caption: text }),
    });
    if (!res.ok) throw new Error();
    item.caption = text;
    $("v-save").textContent = "Saved ✓";
    const card = document.querySelector(`#results-grid .card[data-id="${item.id}"]`);
    if (card) {
      const idx = state.job.items.filter(hasResult).indexOf(item);
      card.replaceWith(resultCard(item, idx));
    }
  } catch {
    $("v-save").textContent = "We couldn't save that change. Please try again.";
  }
}

function closeViewer() {
  clearTimeout(state.saveTimer);
  saveCaption();
  $("viewer").hidden = true;
  document.body.style.overflow = "";
  if (state.viewerOpener && document.contains(state.viewerOpener)) state.viewerOpener.focus();
}

function moveViewer(delta) {
  clearTimeout(state.saveTimer);
  saveCaption();
  showViewerItem(state.viewerIndex + delta);
}

function setupViewer() {
  $("v-close").addEventListener("click", closeViewer);
  $("v-prev").addEventListener("click", () => moveViewer(-1));
  $("v-next").addEventListener("click", () => moveViewer(1));
  const cap = $("v-caption");
  cap.addEventListener("input", () => { clearTimeout(state.saveTimer); state.saveTimer = setTimeout(saveCaption, 900); });
  cap.addEventListener("blur", () => { clearTimeout(state.saveTimer); saveCaption(); });
  document.addEventListener("keydown", (e) => {
    if ($("viewer").hidden) return;
    if (e.key === "Escape") { closeViewer(); return; }
    const typing = e.target === cap;
    if (!typing && e.key === "ArrowLeft") moveViewer(-1);
    else if (!typing && e.key === "ArrowRight") moveViewer(1);
    else if (e.key === "Tab") trapFocus(e);
  });
}

function trapFocus(e) {
  const focusable = [...$("viewer").querySelectorAll("button:not(:disabled), textarea, [tabindex='0']")].filter((n) => n.offsetParent !== null || n === document.activeElement);
  if (!focusable.length) return;
  const first = focusable[0], last = focusable[focusable.length - 1];
  if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
  else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
}

/* ---------------------------------------------------------------- boot */

function jobIdFromHash() {
  const m = /^#job=([A-Za-z0-9_-]+)$/.exec(location.hash);
  return m ? m[1] : null;
}

function boot() {
  setupPicking();
  setupViewer();
  $("btn-start").addEventListener("click", startJob);
  $("btn-new").addEventListener("click", () => leaveJob(""));
  $("btn-album").addEventListener("click", (e) => { if ($("btn-album").getAttribute("aria-disabled") === "true") e.preventDefault(); });
  window.addEventListener("hashchange", () => {
    const id = jobIdFromHash();
    if (id && id !== state.jobId) attachToJob(id);
  });
  renderPreview();
  loadHealth();
  const id = jobIdFromHash();
  if (id) attachToJob(id);
}

boot();
