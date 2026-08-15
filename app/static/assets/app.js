const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

const sourceMeta = {
  gmail: { label: "Gmail", icon: "i-mail", search: "Rechercher dans les emails…", create: "Nouveau message" },
  chat: { label: "Google Chat", icon: "i-chat", search: "Rechercher un espace…", create: "Nouveau message" },
  drive: { label: "Google Drive", icon: "i-drive", search: "Rechercher un fichier…", create: "Créer dans Drive" },
  calendar: { label: "Google Calendar", icon: "i-calendar", search: "Rechercher un événement…", create: "Nouvel événement" },
  odoo: { label: "Odoo", icon: "i-odoo", search: "Rechercher dans Odoo…", create: "Nouvel enregistrement" },
};

const state = {
  contexts: [], connectors: {}, query: "", selectedId: null, selectedIds: new Set(), view: "contexts",
  sourceApp: { source: "gmail", items: [], detail: null, selectedId: null, selectedKind: null, driveView: "all", requestId: 0 },
  resourcePicker: { source: "gmail", results: [], selected: null, detail: null, choices: [], choice: null, requestId: 0 },
  editor: { mode: "create", detail: null, overrides: {} },
  pendingResource: null,
};

function icon(id) { return `<svg aria-hidden="true"><use href="#${id}"></use></svg>`; }
function escapeHtml(value = "") { const node = document.createElement("div"); node.textContent = String(value); return node.innerHTML; }
function relativeDate(value) {
  if (!value) return "";
  const delta = new Date(value).getTime() - Date.now();
  const days = Math.round(delta / 86400000);
  if (Math.abs(days) >= 1) return new Intl.RelativeTimeFormat("fr", { numeric: "auto" }).format(days, "day");
  return new Intl.RelativeTimeFormat("fr", { numeric: "auto" }).format(Math.round(delta / 3600000), "hour");
}
function formatDateTime(value) {
  if (!value) return "Date non définie";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat("fr-FR", { dateStyle: "medium", timeStyle: "short" }).format(date);
}
function truncate(value = "", size = 180) { return value.length > size ? `${value.slice(0, size)}…` : value; }

async function api(path, options = {}) {
  const response = await fetch(path, { ...options, headers: { "Content-Type": "application/json", ...(options.headers || {}) } });
  if (!response.ok) {
    let detail = "Une erreur est survenue";
    try { const body = await response.json(); detail = body.detail || detail; } catch (_) { /* Empty response. */ }
    throw new Error(typeof detail === "string" ? detail : "Les données saisies sont invalides");
  }
  return response.status === 204 ? null : response.json();
}

function toast(message, error = false) {
  const element = $("#toast");
  $("#toast-message").textContent = message;
  $("span", element).textContent = error ? "!" : "✓";
  element.classList.toggle("error", error);
  element.classList.add("show");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => element.classList.remove("show"), 3800);
}

function sourceIcons(context) {
  return context.sources.map((source) => `<span class="mini-source ${source}" title="${sourceMeta[source]?.label || source}">${icon(sourceMeta[source]?.icon || "i-link")}</span>`).join("");
}

function renderSourceSummary() {
  const counts = Object.fromEntries(Object.keys(sourceMeta).map((source) => [source, state.contexts.filter((context) => context.sources.includes(source)).length]));
  $("#source-summary").innerHTML = Object.entries(sourceMeta).map(([source, meta]) => `<span class="summary-source ${source}" title="${meta.label} · ${counts[source]} contexte(s)">${icon(meta.icon)}</span>`).join("");
}

function contextRow(context) {
  return `<article class="context-row" data-id="${context.id}" tabindex="0">
    <label class="context-select"><input type="checkbox" data-select-context="${context.id}" ${state.selectedIds.has(context.id) ? "checked" : ""} aria-label="Sélectionner ${escapeHtml(context.title)}"></label>
    <div class="context-main"><h2>${escapeHtml(context.title)}</h2><p>${escapeHtml(context.summary || "Espace de ressources")}</p></div>
    <div class="context-resources"><div class="resource-sources">${sourceIcons(context)}</div><small>${context.resource_count} ressource${context.resource_count !== 1 ? "s" : ""}</small></div>
    <div class="context-date">Modifié ${relativeDate(context.updated_at)}</div>
    <div class="context-row-actions"><button class="row-delete" data-delete-context-row="${context.id}" aria-label="Supprimer">${icon("i-trash")}</button><span class="row-arrow">${icon("i-external")}</span></div>
  </article>`;
}

function updateSelectionUi() {
  const count = state.selectedIds.size;
  $("#bulk-actions").classList.toggle("hidden", count === 0);
  $("#selected-count").textContent = `${count} sélectionné${count !== 1 ? "s" : ""}`;
  const ids = state.contexts.map((context) => context.id);
  const visibleSelected = ids.filter((id) => state.selectedIds.has(id)).length;
  $("#select-all-contexts").checked = ids.length > 0 && visibleSelected === ids.length;
  $("#select-all-contexts").indeterminate = visibleSelected > 0 && visibleSelected < ids.length;
}

function renderContexts() {
  $("#contexts-list").innerHTML = state.contexts.map(contextRow).join("");
  $("#contexts-list").classList.toggle("hidden", state.contexts.length === 0);
  $("#empty-state").classList.toggle("hidden", state.contexts.length !== 0);
  $("#result-label").textContent = `${state.contexts.length} contexte${state.contexts.length !== 1 ? "s" : ""}`;
  $("#context-count").textContent = state.contexts.length;
  renderSourceSummary();
  $$(".context-row").forEach((row) => {
    row.addEventListener("click", (event) => { if (!event.target.closest("button,input,label,a")) openContext(row.dataset.id); });
    row.addEventListener("keydown", (event) => { if (["Enter", " "].includes(event.key)) openContext(row.dataset.id); });
  });
  $$('[data-select-context]').forEach((input) => input.addEventListener("change", () => { if (input.checked) state.selectedIds.add(input.dataset.selectContext); else state.selectedIds.delete(input.dataset.selectContext); updateSelectionUi(); }));
  $$('[data-delete-context-row]').forEach((button) => button.addEventListener("click", (event) => { event.stopPropagation(); deleteContexts([button.dataset.deleteContextRow]); }));
  updateSelectionUi();
}

async function loadContexts() {
  const params = new URLSearchParams();
  if (state.query) params.set("q", state.query);
  try { state.contexts = await api(`/api/v1/contexts?${params}`); renderContexts(); }
  catch (error) { toast(error.message, true); }
}

function openResourceInApp(resource) {
  const kind = resource.resource_type || "item";
  showSourceApp(resource.source, resource.external_id, kind);
}

function resourceItem(resource, contextId) {
  const meta = sourceMeta[resource.source] || { label: resource.source, icon: "i-link" };
  return `<article class="resource-item"><span class="mini-source ${resource.source}">${icon(meta.icon)}</span><div class="resource-main"><button class="resource-open" data-resource-open="${resource.id}">${escapeHtml(resource.title)}</button><p>${escapeHtml(resource.excerpt || `${meta.label} · ${resource.resource_type}`)}</p></div><div class="resource-actions"><button data-resource-open="${resource.id}" aria-label="Ouvrir dans le Hub">${icon("i-external")}</button><button data-delete-resource="${resource.id}" data-context="${contextId}" aria-label="Détacher">${icon("i-trash")}</button></div></article>`;
}

function renderDrawer(context) {
  const resources = context.resources.length ? context.resources.map((resource) => resourceItem(resource, context.id)).join("") : `<div class="drawer-empty">Aucune ressource rattachée. Choisissez un élément dans Gmail, Chat, Drive, Calendar ou Odoo.</div>`;
  $("#drawer-content").innerHTML = `<div class="drawer-hero"><div class="drawer-toolbar"><span class="drawer-kicker">CONTEXTE</span><button class="icon-button drawer-close" aria-label="Fermer">${icon("i-close")}</button></div><div class="drawer-title-row"><h2>${escapeHtml(context.title)}</h2><button class="icon-button edit-context" aria-label="Modifier">${icon("i-edit")}</button></div><p>${escapeHtml(context.summary || "Espace centralisant des ressources provenant de plusieurs sources.")}</p></div><div class="drawer-body"><div class="drawer-section-head"><div><h3>Ressources</h3><small>${context.resource_count} raccourci${context.resource_count !== 1 ? "s" : ""} · aucune copie</small></div><button class="secondary-button" id="add-resource">${icon("i-plus")}Choisir une ressource</button></div><div class="resource-list">${resources}</div></div>`;
  $(".drawer-close").addEventListener("click", closeDrawer);
  $(".edit-context").addEventListener("click", () => openContextModal(context));
  $("#add-resource").addEventListener("click", openResourceModal);
  $$('[data-delete-resource]').forEach((button) => button.addEventListener("click", removeResource));
  $$('[data-resource-open]').forEach((button) => button.addEventListener("click", () => {
    const resource = context.resources.find((item) => item.id === button.dataset.resourceOpen);
    if (resource) { closeDrawer(); openResourceInApp(resource); }
  }));
}

async function openContext(id) {
  state.selectedId = id;
  try {
    const context = await api(`/api/v1/contexts/${id}`);
    renderDrawer(context);
    $("#drawer-backdrop").classList.remove("hidden");
    $("#context-drawer").classList.add("open");
    $("#context-drawer").setAttribute("aria-hidden", "false");
  } catch (error) { toast(error.message, true); }
}

function closeDrawer() { $("#drawer-backdrop").classList.add("hidden"); $("#context-drawer").classList.remove("open"); $("#context-drawer").setAttribute("aria-hidden", "true"); state.selectedId = null; }
function openModal(id) { $(`#${id}`).classList.remove("hidden"); setTimeout(() => $("input:not([type=hidden]),textarea", $(`#${id}`))?.focus(), 30); }
function closeModal(element) { element.closest(".modal-backdrop")?.classList.add("hidden"); }

function openContextModal(context = null, pendingResource = null) {
  state.pendingResource = pendingResource;
  const form = $("#context-form"); form.reset(); form.elements.context_id.value = context?.id || "";
  $("#modal-mode").textContent = context ? "MODIFIER LE CONTEXTE" : pendingResource ? "NOUVEAU CONTEXTE + RATTACHEMENT" : "NOUVEAU CONTEXTE";
  $("#context-modal-title").textContent = context ? context.title : "Créer un contexte";
  $("#delete-context").classList.toggle("hidden", !context);
  if (context) for (const field of ["title", "summary"]) form.elements[field].value = context[field] || "";
  openModal("context-modal");
}

async function saveContext(event) {
  event.preventDefault(); const form = event.currentTarget; const values = Object.fromEntries(new FormData(form));
  const id = values.context_id; delete values.context_id; const button = $("button[type=submit]", form); button.disabled = true;
  try {
    const context = await api(id ? `/api/v1/contexts/${id}` : "/api/v1/contexts", { method: id ? "PATCH" : "POST", body: JSON.stringify(values) });
    if (!id && state.pendingResource) {
      await api(`/api/v1/contexts/${context.id}/resources`, { method: "POST", body: JSON.stringify(state.pendingResource) });
      toast("Contexte créé et ressource rattachée"); state.pendingResource = null;
    } else toast(id ? "Contexte mis à jour" : "Contexte créé");
    closeModal(button); await loadContexts();
    if (state.view === "contexts") openContext(context.id);
  } catch (error) { toast(error.message, true); } finally { button.disabled = false; }
}

async function deleteContext() {
  const id = $("#context-form").elements.context_id.value;
  if (!id || !confirm("Supprimer ce contexte ? Les données sources resteront intactes.")) return;
  try { await api(`/api/v1/contexts/${id}`, { method: "DELETE" }); state.selectedIds.delete(id); closeModal($("#delete-context")); closeDrawer(); toast("Contexte supprimé"); await loadContexts(); }
  catch (error) { toast(error.message, true); }
}

async function deleteContexts(ids) {
  const uniqueIds = [...new Set(ids)].filter(Boolean); if (!uniqueIds.length || !confirm(`Supprimer ${uniqueIds.length === 1 ? "ce contexte" : `ces ${uniqueIds.length} contextes`} ?`)) return;
  try { const result = await api("/api/v1/contexts/bulk-delete", { method: "POST", body: JSON.stringify({ ids: uniqueIds }) }); uniqueIds.forEach((id) => state.selectedIds.delete(id)); toast(`${result.deleted} contexte(s) supprimé(s)`); await loadContexts(); }
  catch (error) { toast(error.message, true); }
}

async function removeResource(event) {
  const button = event.currentTarget; if (!confirm("Détacher cette ressource ? La donnée source ne sera pas supprimée.")) return;
  try { await api(`/api/v1/contexts/${button.dataset.context}/resources/${button.dataset.deleteResource}`, { method: "DELETE" }); toast("Ressource détachée"); await Promise.all([openContext(button.dataset.context), loadContexts()]); }
  catch (error) { toast(error.message, true); }
}

function resourceResultItem(resource, index) {
  const meta = sourceMeta[resource.source]; const selected = state.resourcePicker.selected === index;
  return `<button type="button" class="resource-search-result ${selected ? "selected" : ""}" data-resource-index="${index}"><span class="mini-source ${resource.source}">${icon(meta.icon)}</span><span><strong>${escapeHtml(resource.title)}</strong><small>${escapeHtml(resource.excerpt || meta.label)}</small></span><i>${selected ? "Ouvert" : "Vérifier"}</i></button>`;
}

function previewChoice(resource, label, index) {
  const selected = state.resourcePicker.choice === index;
  return `<button type="button" class="preview-choice ${selected ? "selected" : ""}" data-preview-choice="${index}"><span>${selected ? "●" : "○"}</span><div><strong>${escapeHtml(label)}</strong><small>${escapeHtml(truncate(resource.excerpt || resource.title, 120))}</small></div></button>`;
}

function detailBody(detail) {
  const meta = [detail.sender, detail.to ? `À ${detail.to}` : "", detail.location, detail.timestamp ? formatDateTime(detail.timestamp) : ""].filter(Boolean);
  return `<div class="detail-meta">${meta.map((item) => `<span>${escapeHtml(item)}</span>`).join("")}</div>${detail.body ? `<div class="detail-body">${escapeHtml(detail.body)}</div>` : detail.snippet ? `<div class="detail-body">${escapeHtml(detail.snippet)}</div>` : ""}`;
}

function renderResourcePreview() {
  const detail = state.resourcePicker.detail;
  if (!detail) { $("#resource-preview").innerHTML = `<div class="resource-preview-empty">Sélectionnez un résultat pour vérifier son contenu avant de le rattacher.</div>`; return; }
  const choices = state.resourcePicker.choices;
  const children = detail.kind === "thread" ? `<div class="mail-preview-stack">${(detail.children || []).map((message) => `<article><header><strong>${escapeHtml(message.sender || "Expéditeur")}</strong><time>${escapeHtml(message.date || formatDateTime(message.timestamp))}</time></header><p>${escapeHtml(truncate(message.body || message.snippet, 500))}</p></article>`).join("")}</div>` : "";
  $("#resource-preview").innerHTML = `<span class="eyebrow">APERÇU AVANT RATTACHEMENT</span><h3>${escapeHtml(detail.title)}</h3>${detailBody(detail)}${children}<div class="attachment-scope"><strong>Rattacher</strong>${choices.map((choice, index) => previewChoice(choice.resource, choice.label, index)).join("")}</div>`;
  $$('[data-preview-choice]').forEach((button) => button.addEventListener("click", () => { state.resourcePicker.choice = Number(button.dataset.previewChoice); renderResourcePreview(); $("#attach-selected-resource").disabled = false; }));
}

async function loadResourcePreview(index) {
  state.resourcePicker.selected = index; state.resourcePicker.detail = null; state.resourcePicker.choices = []; state.resourcePicker.choice = null;
  renderResourceResults(); $("#resource-preview").innerHTML = `<div class="resource-preview-empty">Chargement du détail…</div>`;
  const resource = state.resourcePicker.results[index];
  try {
    const detail = await api(`/api/v1/apps/${resource.source}/item?item_id=${encodeURIComponent(resource.external_id)}&kind=${encodeURIComponent(resource.resource_type)}`);
    state.resourcePicker.detail = detail;
    if (detail.kind === "thread") {
      state.resourcePicker.choices = [{ label: `Conversation entière · ${detail.children?.length || 0} messages`, resource: detail.resource }, ...(detail.children || []).map((message) => ({ label: `Message de ${message.sender || "l’expéditeur"} · ${formatDateTime(message.timestamp)}`, resource: message.resource }))];
    } else state.resourcePicker.choices = [{ label: detail.kind === "message" ? "Ce message uniquement" : "Cet élément", resource: detail.resource || resource }];
    state.resourcePicker.choice = 0; $("#attach-selected-resource").disabled = false; renderResourcePreview();
  } catch (error) { $("#resource-preview").innerHTML = `<div class="resource-preview-error">${escapeHtml(error.message)}</div>`; toast(error.message, true); }
}

function renderResourceResults() {
  $("#resource-search-results").innerHTML = state.resourcePicker.results.map(resourceResultItem).join("");
  $$('[data-resource-index]').forEach((button) => button.addEventListener("click", () => loadResourcePreview(Number(button.dataset.resourceIndex))));
}

async function searchResources() {
  const requestId = ++state.resourcePicker.requestId; const query = $("#resource-search").value.trim();
  $("#resource-search-state").textContent = `Recherche dans ${sourceMeta[state.resourcePicker.source].label}…`; $("#resource-search-results").innerHTML = `<div class="source-loading">Chargement…</div>`;
  state.resourcePicker.selected = null; state.resourcePicker.detail = null; state.resourcePicker.choice = null; $("#attach-selected-resource").disabled = true; renderResourcePreview();
  try {
    const results = await api(`/api/v1/resources/search?source=${state.resourcePicker.source}&q=${encodeURIComponent(query)}`);
    if (requestId !== state.resourcePicker.requestId) return;
    state.resourcePicker.results = results; $("#resource-search-state").textContent = results.length ? `${results.length} résultat(s) · cliquez pour vérifier` : "Aucune ressource trouvée."; renderResourceResults();
  } catch (error) { if (requestId !== state.resourcePicker.requestId) return; state.resourcePicker.results = []; $("#resource-search-results").innerHTML = ""; $("#resource-search-state").textContent = error.message; toast(error.message, true); }
}

function setResourceSource(source, run = true) {
  state.resourcePicker.source = source; state.resourcePicker.results = []; state.resourcePicker.detail = null; state.resourcePicker.choice = null;
  $$('[data-resource-source]').forEach((button) => button.classList.toggle("active", button.dataset.resourceSource === source));
  $("#resource-search").placeholder = `Rechercher dans ${sourceMeta[source].label}…`; renderResourcePreview(); if (run) searchResources();
}
function openResourceModal() { $("#resource-search").value = ""; setResourceSource("gmail", false); openModal("resource-modal"); searchResources(); }
async function saveResource(event) {
  event.preventDefault(); const choice = state.resourcePicker.choices[state.resourcePicker.choice]; if (!state.selectedId || !choice) return;
  const button = $("#attach-selected-resource"); button.disabled = true;
  try { await api(`/api/v1/contexts/${state.selectedId}/resources`, { method: "POST", body: JSON.stringify(choice.resource) }); closeModal(button); toast("Ressource rattachée"); await Promise.all([openContext(state.selectedId), loadContexts()]); }
  catch (error) { toast(error.message, true); } finally { button.disabled = false; }
}

function showView(view) {
  state.view = view;
  $("#contexts-view").classList.toggle("hidden", view !== "contexts"); $("#applications-view").classList.toggle("hidden", view !== "applications"); $("#settings-view").classList.toggle("hidden", view !== "settings");
  $("#search").disabled = view !== "contexts"; $("#create-context").classList.toggle("hidden", view === "applications"); document.body.classList.toggle("source-app-mode", view === "applications");
  $$(".nav-button[data-view]").forEach((button) => button.classList.toggle("active", button.dataset.view === view)); $$(".source-app-button").forEach((button) => button.classList.toggle("active", view === "applications" && button.dataset.app === state.sourceApp.source));
  $(".sidebar").classList.remove("open"); if (view === "settings") loadConnectors();
}

function sourceListItem(item) {
  const selected = item.id === state.sourceApp.selectedId && item.kind === state.sourceApp.selectedKind;
  return `<button class="source-list-item ${selected ? "selected" : ""}" data-source-id="${escapeHtml(item.id)}" data-source-kind="${escapeHtml(item.kind)}"><span class="source-kind-icon">${icon(sourceMeta[state.sourceApp.source].icon)}</span><span><strong>${escapeHtml(item.title)}</strong><small>${escapeHtml(item.subtitle || item.snippet || "")}</small><em>${escapeHtml(truncate(item.snippet || "", 100))}</em></span><time>${escapeHtml(relativeDate(item.timestamp))}</time></button>`;
}

function renderSourceItems() {
  $("#source-item-list").innerHTML = state.sourceApp.items.map(sourceListItem).join(""); $("#source-list-status").textContent = `${state.sourceApp.items.length} élément(s)`;
  $$('[data-source-id]').forEach((button) => button.addEventListener("click", () => loadSourceDetail(button.dataset.sourceId, button.dataset.sourceKind)));
}

async function loadSourceItems(query = "") {
  const requestId = ++state.sourceApp.requestId; $("#source-list-status").textContent = "Chargement…"; $("#source-item-list").innerHTML = `<div class="source-loading">Connexion à ${sourceMeta[state.sourceApp.source].label}…</div>`;
  const view = state.sourceApp.source === "drive" ? `&view=${state.sourceApp.driveView}` : "";
  try {
    const data = await api(`/api/v1/apps/${state.sourceApp.source}/items?q=${encodeURIComponent(query)}${view}`); if (requestId !== state.sourceApp.requestId) return;
    state.sourceApp.items = data.items; renderSourceItems();
  } catch (error) { if (requestId !== state.sourceApp.requestId) return; $("#source-list-status").textContent = error.message; $("#source-item-list").innerHTML = `<div class="source-error"><strong>Connexion impossible</strong><p>${escapeHtml(error.message)}</p><button class="secondary-button" data-view-settings>Ouvrir les paramètres</button></div>`; $("[data-view-settings]")?.addEventListener("click", () => showView("settings")); }
}

function contextAttachCard(resource) {
  if (!resource) return "";
  const options = state.contexts.map((context) => `<option value="${context.id}">${escapeHtml(context.title)}</option>`).join("");
  return `<section class="detail-context-card"><div><span class="eyebrow">CONTEXTUALISATION</span><h3>Rattacher cet élément</h3><p>Ajoute une référence, sans copier la donnée source.</p></div><div class="detail-context-actions"><select id="detail-context-select"><option value="">Choisir un contexte…</option>${options}</select><button class="primary-button" id="detail-attach">${icon("i-link")}Rattacher</button><button class="secondary-button" id="detail-new-context">${icon("i-plus")}Nouveau contexte</button></div></section>`;
}

function detailActions(detail) {
  const source = state.sourceApp.source;
  if (source === "gmail") return `<button class="secondary-button" data-source-action="read">Marquer lu</button><button class="secondary-button" data-source-action="unread">Non lu</button><button class="secondary-button" data-source-action="star">Suivre</button><button class="secondary-button" data-source-action="archive">Archiver</button><button class="danger-button" data-source-delete>Corbeille</button>`;
  if (source === "chat" && detail.kind === "message") return `<button class="secondary-button" data-source-edit>${icon("i-edit")}Modifier</button><button class="danger-button" data-source-delete>${icon("i-trash")}Supprimer</button>`;
  if (source === "drive" || source === "calendar" || source === "odoo") return `<button class="secondary-button" data-source-edit>${icon("i-edit")}Modifier</button><button class="danger-button" data-source-delete>${icon("i-trash")}${source === "drive" ? "Corbeille" : "Supprimer"}</button>`;
  return "";
}

function renderMessageCard(message) {
  return `<article class="native-message-card"><header><div><strong>${escapeHtml(message.sender || message.subtitle || "Message")}</strong><small>${escapeHtml(message.to ? `À ${message.to}` : "")}</small></div><time>${escapeHtml(formatDateTime(message.timestamp))}</time></header><h4>${escapeHtml(message.title)}</h4><div class="native-message-body">${escapeHtml(message.body || message.snippet || "")}</div><div class="native-message-actions"><button class="secondary-button" data-child-open="${escapeHtml(message.id)}" data-child-kind="message">Ouvrir</button>${message.resource ? `<button class="primary-button" data-child-attach="${escapeHtml(message.id)}">${icon("i-link")}Rattacher ce message</button>` : ""}</div></article>`;
}

function renderSourceDetail() {
  const detail = state.sourceApp.detail; if (!detail) return;
  const source = state.sourceApp.source; const children = detail.children || [];
  const childHtml = children.length ? `<section class="native-children"><div class="native-section-title"><h3>${source === "chat" ? "Messages" : "Conversation"}</h3>${source === "chat" ? `<button class="primary-button" id="chat-reply">${icon("i-plus")}Nouveau message</button>` : ""}</div>${children.map(renderMessageCard).join("")}</section>` : "";
  const fields = detail.fields ? `<dl class="native-fields">${Object.entries(detail.fields).filter(([, value]) => value !== false && value !== "" && value != null).map(([key, value]) => `<div><dt>${escapeHtml(key.replaceAll("_", " "))}</dt><dd>${escapeHtml(String(value))}</dd></div>`).join("")}</dl>` : "";
  $("#source-detail-panel").innerHTML = `<article class="source-detail"><header class="source-detail-header"><div><span class="eyebrow">${escapeHtml(detail.kind || "ÉLÉMENT")}</span><h2>${escapeHtml(detail.title)}</h2><p>${escapeHtml(detail.subtitle || "")}</p></div><div class="source-detail-actions">${detailActions(detail)}</div></header>${detailBody(detail)}${fields}${contextAttachCard(detail.resource)}${childHtml}</article>`;
  bindDetailEvents();
}

function bindDetailEvents() {
  const detail = state.sourceApp.detail;
  $("#detail-attach")?.addEventListener("click", () => attachDetailResource(detail.resource));
  $("#detail-new-context")?.addEventListener("click", () => openContextModal(null, detail.resource));
  $$('[data-source-action]').forEach((button) => button.addEventListener("click", () => updateSourceAction(button.dataset.sourceAction)));
  $("[data-source-edit]")?.addEventListener("click", () => openSourceEditor("edit", detail)); $("[data-source-delete]")?.addEventListener("click", deleteSourceItem);
  $("#chat-reply")?.addEventListener("click", () => openSourceEditor("create", null, { parent: detail.id }));
  $$('[data-child-open]').forEach((button) => button.addEventListener("click", () => loadSourceDetail(button.dataset.childOpen, button.dataset.childKind)));
  $$('[data-child-attach]').forEach((button) => button.addEventListener("click", () => { const message = (detail.children || []).find((item) => item.id === button.dataset.childAttach); if (message?.resource) attachDetailResource(message.resource); }));
}

async function loadSourceDetail(id, kind) {
  state.sourceApp.selectedId = id; state.sourceApp.selectedKind = kind; renderSourceItems(); $("#source-detail-panel").innerHTML = `<div class="source-detail-empty"><div class="source-loading">Chargement du détail…</div></div>`;
  try { state.sourceApp.detail = await api(`/api/v1/apps/${state.sourceApp.source}/item?item_id=${encodeURIComponent(id)}&kind=${encodeURIComponent(kind)}`); renderSourceDetail(); }
  catch (error) { $("#source-detail-panel").innerHTML = `<div class="source-detail-empty"><h2>Détail indisponible</h2><p>${escapeHtml(error.message)}</p></div>`; toast(error.message, true); }
}

async function attachDetailResource(resource) {
  const contextId = $("#detail-context-select")?.value;
  if (!contextId) return toast("Choisissez d’abord un contexte", true);
  try { await api(`/api/v1/contexts/${contextId}/resources`, { method: "POST", body: JSON.stringify(resource) }); toast("Ressource rattachée au contexte"); await loadContexts(); }
  catch (error) { toast(error.message, true); }
}

async function updateSourceAction(action) {
  const detail = state.sourceApp.detail;
  try { state.sourceApp.detail = await api(`/api/v1/apps/${state.sourceApp.source}/item?item_id=${encodeURIComponent(detail.id)}&kind=${encodeURIComponent(detail.kind)}`, { method: "PATCH", body: JSON.stringify({ action }) }); renderSourceDetail(); toast("Action effectuée"); await loadSourceItems($("#source-app-search").value.trim()); }
  catch (error) { toast(error.message, true); }
}

function editorField(label, name, value = "", type = "text", required = false) {
  if (type === "textarea") return `<label>${label}<textarea name="${name}" rows="5" ${required ? "required" : ""}>${escapeHtml(value)}</textarea></label>`;
  return `<label>${label}<input name="${name}" type="${type}" value="${escapeHtml(value)}" ${required ? "required" : ""}/></label>`;
}

function sourceEditorFields(source, mode, detail, overrides) {
  if (source === "gmail") return `${editorField("Destinataire", "to", "", "email", true)}${editorField("Cc", "cc", "", "email")}${editorField("Objet", "subject", "", "text", true)}${editorField("Message", "body", "", "textarea", true)}`;
  if (source === "chat") {
    if (mode === "edit") return editorField("Message", "text", detail.body || detail.snippet, "textarea", true);
    const options = state.sourceApp.items.filter((item) => item.kind === "space").map((space) => `<option value="${escapeHtml(space.id)}" ${space.id === overrides.parent ? "selected" : ""}>${escapeHtml(space.title)}</option>`).join("");
    return `<label>Espace<select name="parent" required>${options}</select></label>${editorField("Message", "text", "", "textarea", true)}`;
  }
  if (source === "drive") {
    const kind = mode === "create" ? `<label>Type<select name="kind"><option value="folder">Dossier</option><option value="doc">Google Docs</option><option value="sheet">Google Sheets</option><option value="slide">Google Slides</option></select></label>` : "";
    return `${editorField("Nom", "name", detail?.title || "", "text", true)}${kind}${editorField("Description", "description", detail?.body || detail?.snippet || "", "textarea")}`;
  }
  if (source === "calendar") {
    const start = detail?.start?.dateTime?.slice(0, 16) || ""; const end = detail?.end?.dateTime?.slice(0, 16) || "";
    return `${editorField("Titre", "title", detail?.title || "", "text", true)}<div class="two-columns">${editorField("Début", "start", start, "datetime-local", true)}${editorField("Fin", "end", end, "datetime-local", true)}</div>${editorField("Lieu", "location", detail?.location || "")}${editorField("Description", "description", detail?.body || "", "textarea")}`;
  }
  if (mode === "create") return `<label>Type<select name="model"><option value="crm.lead">Opportunité CRM</option><option value="res.partner">Contact</option><option value="project.project">Projet</option><option value="project.task">Tâche</option></select></label>${editorField("Nom", "name", "", "text", true)}${editorField("Description", "description", "", "textarea")}`;
  return `${editorField("Nom", "name", detail?.title || "", "text", true)}${editorField("Description", "description", detail?.fields?.description || detail?.fields?.comment || "", "textarea")}`;
}

function openSourceEditor(mode = "create", detail = null, overrides = {}) {
  state.editor = { mode, detail, overrides }; const source = state.sourceApp.source; const meta = sourceMeta[source];
  $("#source-editor-mode").textContent = mode === "create" ? "NOUVEL ÉLÉMENT" : "MODIFIER L’ÉLÉMENT"; $("#source-editor-title").textContent = mode === "create" ? meta.create : `Modifier · ${detail.title}`;
  $("#source-editor-help").textContent = `L’action sera appliquée directement dans ${meta.label}.`; $("#source-editor-fields").innerHTML = sourceEditorFields(source, mode, detail, overrides); openModal("source-editor-modal");
}

async function saveSourceEditor(event) {
  event.preventDefault(); const form = event.currentTarget; const data = Object.fromEntries(new FormData(form)); const { source } = state.sourceApp; const { mode, detail } = state.editor;
  if (source === "calendar") for (const field of ["start", "end"]) if (data[field]) data[field] = new Date(data[field]).toISOString();
  if (source === "odoo" && data.description !== undefined && (data.model === "res.partner" || detail?.kind === "res.partner")) {
    data.comment = data.description; delete data.description;
  }
  const button = $("button[type=submit]", form); button.disabled = true;
  try {
    const path = mode === "create" ? `/api/v1/apps/${source}/items` : `/api/v1/apps/${source}/item?item_id=${encodeURIComponent(detail.id)}&kind=${encodeURIComponent(detail.kind)}`;
    const result = await api(path, { method: mode === "create" ? "POST" : "PATCH", body: JSON.stringify(data) }); closeModal(button); toast(mode === "create" ? "Élément créé" : "Élément mis à jour"); await loadSourceItems($("#source-app-search").value.trim()); if (result?.id) loadSourceDetail(result.id, result.kind);
  } catch (error) { toast(error.message, true); } finally { button.disabled = false; }
}

async function deleteSourceItem() {
  const detail = state.sourceApp.detail; if (!confirm(`Supprimer « ${detail.title} » dans ${sourceMeta[state.sourceApp.source].label} ?`)) return;
  try { await api(`/api/v1/apps/${state.sourceApp.source}/item?item_id=${encodeURIComponent(detail.id)}&kind=${encodeURIComponent(detail.kind)}`, { method: "DELETE" }); state.sourceApp.detail = null; state.sourceApp.selectedId = null; $("#source-detail-panel").innerHTML = `<div class="source-detail-empty"><h2>Élément supprimé</h2></div>`; toast("Suppression effectuée"); await loadSourceItems($("#source-app-search").value.trim()); }
  catch (error) { toast(error.message, true); }
}

async function showSourceApp(source, itemId = null, kind = null) {
  state.sourceApp.source = source; state.sourceApp.detail = null; state.sourceApp.selectedId = null; state.sourceApp.selectedKind = null;
  const meta = sourceMeta[source]; $("#source-app-title").textContent = meta.label; $("#source-app-search").placeholder = meta.search; $("#source-app-search").value = ""; $("#source-app-logo").className = `source-app-logo ${source}`; $("#source-app-logo").innerHTML = icon(meta.icon); $("#source-app-create").innerHTML = `${icon("i-plus")}${meta.create}`;
  $("#drive-view-tabs").classList.toggle("hidden", source !== "drive"); $("#source-detail-panel").innerHTML = `<div class="source-detail-empty"><span>${icon(meta.icon)}</span><h2>Sélectionnez un élément</h2><p>Son contenu et ses actions apparaîtront ici.</p></div>`; showView("applications"); await loadSourceItems();
  if (itemId) loadSourceDetail(itemId, kind || "item");
  const url = new URL(location.href); url.search = ""; url.searchParams.set("app", source); if (itemId) { url.searchParams.set("item", itemId); url.searchParams.set("kind", kind || "item"); } history.replaceState({}, "", url);
}

function connectorStatusLabel(connector) { if (connector.status === "connected") return connector.configuration.scope_upgrade_required ? "Droits à actualiser" : "Connecté"; if (connector.status === "configured") return "Prêt à connecter"; if (connector.status === "error") return "Erreur"; return "Non configuré"; }
function statsHtml(provider, stats) { const labels = provider === "google" ? { gmail_threads: "Fils Gmail", drive_files_sample: "Fichiers Drive", upcoming_events: "Événements", chat_spaces: "Espaces Chat" } : { contacts: "Contacts", opportunities: "Opportunités", projects: "Projets", server_version: "Version serveur" }; return Object.entries(stats).filter(([key]) => labels[key]).map(([key, value]) => `<div class="connector-stat"><strong>${escapeHtml(value)}</strong><span>${labels[key]}</span></div>`).join(""); }
function renderConnector(connector) {
  const provider = connector.provider; const status = $(`#${provider}-status`); status.textContent = connectorStatusLabel(connector); status.className = `connection-pill ${connector.status}`;
  const account = $(`#${provider}-account`); account.textContent = connector.external_account ? `Connecté avec ${connector.external_account}` : ""; account.classList.toggle("hidden", !connector.external_account);
  const stats = $(`#${provider}-stats`); stats.innerHTML = statsHtml(provider, connector.stats || {}); stats.classList.toggle("hidden", !stats.innerHTML);
  const needsScope = provider === "google" && connector.configuration.scope_upgrade_required; const error = $(`#${provider}-error`); error.textContent = needsScope ? "Les vues natives nécessitent de nouveaux droits OAuth. Cliquez sur « Autoriser les accès API » ci-dessous." : connector.last_error || ""; error.classList.toggle("hidden", !error.textContent);
  const connected = connector.status === "connected"; $(`#${provider}-actions`).classList.toggle("hidden", !connected);
  if (provider === "google") { $("#google-connect").classList.toggle("hidden", !connector.configured || (connected && !needsScope)); $("#google-connect").textContent = needsScope ? "Autoriser les accès API" : "Ouvrir la connexion Google"; $("#google-redirect-uri").textContent = connector.configuration.redirect_uri || `${location.origin}/api/v1/connectors/google/callback`; if (connector.configuration.client_id) $("#google-form").elements.client_id.value = connector.configuration.client_id; }
  else { for (const field of ["url", "database", "username"]) if (connector.configuration[field]) $("#odoo-form").elements[field].value = connector.configuration[field]; $("#odoo-form").classList.toggle("hidden", connected); }
}
async function loadConnectors() { try { const connectors = await api("/api/v1/connectors"); state.connectors = Object.fromEntries(connectors.map((item) => [item.provider, item])); connectors.forEach(renderConnector); } catch (error) { toast(error.message, true); } }
async function configureGoogle(event) { event.preventDefault(); const form = event.currentTarget; const button = $("button[type=submit]", form); button.disabled = true; try { const connector = await api("/api/v1/connectors/google/configure", { method: "POST", body: JSON.stringify(Object.fromEntries(new FormData(form))) }); renderConnector(connector); form.elements.client_secret.value = ""; toast("Configuration OAuth enregistrée"); } catch (error) { toast(error.message, true); } finally { button.disabled = false; } }
function connectGoogle() { const popup = window.open("/api/v1/connectors/google/authorize", "context-hub-google-oauth", "popup,width=560,height=720"); if (!popup) toast("Autorisez les fenêtres contextuelles", true); }
async function configureOdoo(event) { event.preventDefault(); const form = event.currentTarget; const button = $("button[type=submit]", form); button.disabled = true; try { const connector = await api("/api/v1/connectors/odoo/configure", { method: "POST", body: JSON.stringify(Object.fromEntries(new FormData(form))) }); renderConnector(connector); form.elements.api_key.value = ""; toast("Connexion Odoo validée"); } catch (error) { toast(error.message, true); } finally { button.disabled = false; } }
async function syncConnector(event) { const provider = event.currentTarget.dataset.sync; event.currentTarget.disabled = true; try { const connector = await api(`/api/v1/connectors/${provider}/sync`, { method: "POST" }); renderConnector(connector); toast("Connecteur actualisé"); } catch (error) { toast(error.message, true); } finally { event.currentTarget.disabled = false; } }
async function disconnectConnector(event) { const provider = event.currentTarget.dataset.disconnect; if (!confirm(`Déconnecter ${provider} ?`)) return; try { await api(`/api/v1/connectors/${provider}`, { method: "DELETE" }); toast("Connecteur déconnecté"); await loadConnectors(); } catch (error) { toast(error.message, true); } }

function bindEvents() {
  $("#create-context").addEventListener("click", () => openContextModal()); $("#empty-create").addEventListener("click", () => openContextModal()); $("#context-form").addEventListener("submit", saveContext); $("#delete-context").addEventListener("click", deleteContext); $("#resource-form").addEventListener("submit", saveResource); $("#source-editor-form").addEventListener("submit", saveSourceEditor);
  $("#drawer-backdrop").addEventListener("click", closeDrawer); $$(".modal-close").forEach((button) => button.addEventListener("click", () => closeModal(button))); $$(".modal-backdrop").forEach((backdrop) => backdrop.addEventListener("mousedown", (event) => { if (event.target === backdrop) backdrop.classList.add("hidden"); }));
  $$(".nav-button[data-view]").forEach((button) => button.addEventListener("click", () => showView(button.dataset.view))); $$(".source-app-button").forEach((button) => button.addEventListener("click", () => showSourceApp(button.dataset.app)));
  $("#select-all-contexts").addEventListener("change", (event) => { state.contexts.forEach((context) => { if (event.currentTarget.checked) state.selectedIds.add(context.id); else state.selectedIds.delete(context.id); }); renderContexts(); }); $("#delete-selected-contexts").addEventListener("click", () => deleteContexts([...state.selectedIds]));
  $$('[data-resource-source]').forEach((button) => button.addEventListener("click", () => setResourceSource(button.dataset.resourceSource))); $("#resource-search-button").addEventListener("click", searchResources); $("#resource-search").addEventListener("keydown", (event) => { if (event.key === "Enter") { event.preventDefault(); searchResources(); } });
  let globalTimer; $("#search").addEventListener("input", (event) => { clearTimeout(globalTimer); globalTimer = setTimeout(() => { state.query = event.target.value.trim(); loadContexts(); }, 220); });
  let sourceTimer; $("#source-app-search").addEventListener("input", (event) => { clearTimeout(sourceTimer); sourceTimer = setTimeout(() => loadSourceItems(event.target.value.trim()), 300); }); $("#source-app-refresh").addEventListener("click", () => loadSourceItems($("#source-app-search").value.trim())); $("#source-app-create").addEventListener("click", () => openSourceEditor());
  $$('[data-drive-view]').forEach((button) => button.addEventListener("click", () => { state.sourceApp.driveView = button.dataset.driveView; $$('[data-drive-view]').forEach((item) => item.classList.toggle("active", item === button)); loadSourceItems($("#source-app-search").value.trim()); }));
  $("#google-form").addEventListener("submit", configureGoogle); $("#google-connect").addEventListener("click", connectGoogle); $("#odoo-form").addEventListener("submit", configureOdoo); $$(".sync-button").forEach((button) => button.addEventListener("click", syncConnector)); $$(".disconnect-button").forEach((button) => button.addEventListener("click", disconnectConnector)); $("#mobile-menu").addEventListener("click", () => $(".sidebar").classList.toggle("open"));
  window.addEventListener("message", (event) => { if (event.origin === location.origin && event.data?.type === "context-hub-oauth") { loadConnectors(); toast(event.data.success ? "Google Workspace connecté" : "Connexion Google interrompue", !event.data.success); } });
  document.addEventListener("keydown", (event) => { if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") { event.preventDefault(); showView("contexts"); $("#search").focus(); } if (event.key === "Escape") { $$(".modal-backdrop:not(.hidden)").forEach((item) => item.classList.add("hidden")); if ($("#context-drawer").classList.contains("open")) closeDrawer(); } });
}

async function init() {
  bindEvents(); await Promise.all([loadContexts(), loadConnectors()]); const params = new URLSearchParams(location.search);
  if (params.get("context")) openContext(params.get("context")); else if (params.get("app")) showSourceApp(params.get("app"), params.get("item"), params.get("kind")); else if (params.get("view") === "settings") showView("settings");
}
init();
