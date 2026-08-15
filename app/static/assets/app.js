const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

const state = {
  contexts: [],
  connectors: {},
  query: "",
  status: "",
  selectedId: null,
  selectedIds: new Set(),
  view: "contexts",
  browser: { status: null, contexts: [], selectedId: null, resource: null, app: "" },
};
let browserResourcePoll = null;

const sourceMeta = {
  gmail: { label: "Gmail", icon: "i-mail" },
  chat: { label: "Google Chat", icon: "i-chat" },
  drive: { label: "Google Drive", icon: "i-drive" },
  calendar: { label: "Calendar", icon: "i-calendar" },
  odoo: { label: "Odoo", icon: "i-odoo" },
};
const typeLabels = { project: "Projet", client: "Client", opportunity: "Opportunité", activity: "Activité", topic: "Sujet" };
const statusLabels = { active: "Actif", watching: "À suivre", archived: "Archivé" };

function icon(id) { return `<svg aria-hidden="true"><use href="#${id}"></use></svg>`; }
function escapeHtml(value = "") { const node = document.createElement("div"); node.textContent = String(value); return node.innerHTML; }
function initials(name = "") { return name.split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]).join("").toUpperCase() || "CH"; }
function formatDate(value) { return value ? new Intl.DateTimeFormat("fr-FR", { day: "numeric", month: "short", year: "numeric" }).format(new Date(value)) : "Sans échéance"; }
function relativeDate(value) {
  if (!value) return "jamais";
  const delta = new Date(value).getTime() - Date.now();
  const days = Math.round(delta / 86400000);
  if (Math.abs(days) >= 1) return new Intl.RelativeTimeFormat("fr", { numeric: "auto" }).format(days, "day");
  return new Intl.RelativeTimeFormat("fr", { numeric: "auto" }).format(Math.round(delta / 3600000), "hour");
}

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
  toast.timer = setTimeout(() => element.classList.remove("show"), 3200);
}

function sourceIcons(context) {
  return context.sources.map((source) => `<span class="mini-source ${source}" title="${sourceMeta[source]?.label || source}">${icon(sourceMeta[source]?.icon || "i-link")}</span>`).join("");
}

function renderSourceSummary() {
  const counts = Object.fromEntries(Object.keys(sourceMeta).map((source) => [source, state.contexts.filter((context) => context.sources.includes(source)).length]));
  $("#source-summary").innerHTML = Object.entries(sourceMeta).map(([source, meta]) => `<span class="summary-source ${source}" title="${meta.label} · ${counts[source]} contexte(s)">${icon(meta.icon)}</span>`).join("");
}

function contextRow(context) {
  return `<article class="context-row" data-id="${context.id}" tabindex="0" style="--context-color:${escapeHtml(context.color)}">
    <label class="context-select" title="Sélectionner ${escapeHtml(context.title)}"><input type="checkbox" data-select-context="${context.id}" ${state.selectedIds.has(context.id) ? "checked" : ""} aria-label="Sélectionner ${escapeHtml(context.title)}"></label>
    <div class="context-main"><span class="context-type"><i></i>${typeLabels[context.context_type] || context.context_type}</span><h2>${escapeHtml(context.title)}</h2><p>${escapeHtml(context.summary || "Aucun résumé")}</p></div>
    <div class="context-owner"><span class="avatar" style="background:${escapeHtml(context.color)}">${initials(context.owner_name)}</span><div><strong>${escapeHtml(context.owner_name || "Non assigné")}</strong><small>${statusLabels[context.status] || context.status}</small></div></div>
    <div class="context-resources"><div class="resource-sources">${sourceIcons(context)}</div><small>${context.resource_count} ressource${context.resource_count !== 1 ? "s" : ""}</small></div>
    <div class="context-date">${formatDate(context.due_at)}</div>
    <div class="context-row-actions"><button class="row-delete" data-delete-context-row="${context.id}" title="Supprimer" aria-label="Supprimer ${escapeHtml(context.title)}">${icon("i-trash")}</button><span class="row-arrow">${icon("i-external")}</span></div>
  </article>`;
}

function updateSelectionUi() {
  const count = state.selectedIds.size;
  $("#bulk-actions").classList.toggle("hidden", count === 0);
  $("#selected-count").textContent = `${count} sélectionné${count !== 1 ? "s" : ""}`;
  const visibleIds = state.contexts.map((context) => context.id);
  const visibleSelected = visibleIds.filter((id) => state.selectedIds.has(id)).length;
  const selectAll = $("#select-all-contexts");
  selectAll.checked = visibleIds.length > 0 && visibleSelected === visibleIds.length;
  selectAll.indeterminate = visibleSelected > 0 && visibleSelected < visibleIds.length;
  $$(".context-row").forEach((row) => row.classList.toggle("selected", state.selectedIds.has(row.dataset.id)));
}

function renderContexts() {
  const list = $("#contexts-list");
  list.innerHTML = state.contexts.map(contextRow).join("");
  list.classList.toggle("hidden", state.contexts.length === 0);
  $("#empty-state").classList.toggle("hidden", state.contexts.length !== 0);
  $("#result-label").textContent = `${state.contexts.length} contexte${state.contexts.length !== 1 ? "s" : ""}`;
  $("#context-count").textContent = state.contexts.length;
  renderSourceSummary();
  $$(".context-row").forEach((row) => {
    row.addEventListener("click", (event) => { if (!event.target.closest("button,input,label,a")) openContext(row.dataset.id); });
    row.addEventListener("keydown", (event) => { if (["Enter", " "].includes(event.key)) openContext(row.dataset.id); });
  });
  $$('[data-select-context]').forEach((checkbox) => checkbox.addEventListener("change", (event) => { const id = event.currentTarget.dataset.selectContext; if (event.currentTarget.checked) state.selectedIds.add(id); else state.selectedIds.delete(id); updateSelectionUi(); }));
  $$('[data-delete-context-row]').forEach((button) => button.addEventListener("click", (event) => { event.stopPropagation(); deleteContexts([event.currentTarget.dataset.deleteContextRow]); }));
  updateSelectionUi();
}

async function loadContexts() {
  const params = new URLSearchParams();
  if (state.query) params.set("q", state.query);
  if (state.status) params.set("status", state.status);
  try { state.contexts = await api(`/api/v1/contexts?${params}`); renderContexts(); }
  catch (error) { toast(error.message, true); }
}

function resourceItem(resource, contextId) {
  const meta = sourceMeta[resource.source] || { label: resource.source, icon: "i-link" };
  return `<article class="resource-item"><span class="mini-source ${resource.source}">${icon(meta.icon)}</span><div class="resource-main"><a href="${escapeHtml(resource.url)}" data-integrated-url="${escapeHtml(resource.url)}" data-integrated-app="${resource.source}">${escapeHtml(resource.title)}</a><p>${escapeHtml(resource.excerpt || `${meta.label} · ${resource.resource_type}`)}</p></div><div class="resource-actions"><a href="${escapeHtml(resource.url)}" data-integrated-url="${escapeHtml(resource.url)}" data-integrated-app="${resource.source}" aria-label="Ouvrir dans Context Hub">${icon("i-external")}</a><button data-delete-resource="${resource.id}" data-context="${contextId}" aria-label="Détacher">${icon("i-trash")}</button></div></article>`;
}

function renderDrawer(context) {
  const resources = context.resources.length ? context.resources.map((resource) => resourceItem(resource, context.id)).join("") : `<div class="drawer-empty">Aucune ressource rattachée. Ouvrez une application ou ajoutez un lien.</div>`;
  $("#drawer-content").innerHTML = `<div class="drawer-hero"><div class="drawer-toolbar"><span class="context-type"><i></i>${typeLabels[context.context_type] || context.context_type}</span><button class="icon-button drawer-close" aria-label="Fermer">${icon("i-close")}</button></div><div class="drawer-title-row"><h2>${escapeHtml(context.title)}</h2><button class="icon-button edit-context" title="Modifier" aria-label="Modifier le contexte">${icon("i-edit")}</button></div><p>${escapeHtml(context.summary || "Aucun résumé")}</p><div class="drawer-tags">${context.tags.map((tag) => `<span>${escapeHtml(tag)}</span>`).join("")}<span>${escapeHtml(context.owner_name || "Non assigné")}</span><span>${statusLabels[context.status] || context.status}</span></div></div><div class="drawer-body"><div class="drawer-section-head"><div><h3>Ressources rattachées</h3><small>${context.resource_count} raccourci${context.resource_count !== 1 ? "s" : ""} · aucune copie</small></div><button class="secondary-button" id="add-resource">${icon("i-plus")}Ajouter un lien</button></div><div class="resource-list">${resources}</div></div>`;
  $(".drawer-close").addEventListener("click", closeDrawer);
  $(".edit-context").addEventListener("click", () => openContextModal(context));
  $("#add-resource").addEventListener("click", () => openModal("resource-modal"));
  $$('[data-delete-resource]').forEach((button) => button.addEventListener("click", removeResource));
  $$('[data-integrated-url]', $("#drawer-content")).forEach((link) => link.addEventListener("click", (event) => { event.preventDefault(); openEmbeddedUrl(link.dataset.integratedUrl, link.dataset.integratedApp); }));
}

async function openContext(id) {
  state.selectedId = id;
  try {
    const context = await api(`/api/v1/contexts/${id}`);
    renderDrawer(context);
    $("#drawer-backdrop").classList.remove("hidden");
    $("#context-drawer").classList.add("open");
    $("#context-drawer").setAttribute("aria-hidden", "false");
    const url = new URL(location.href); url.searchParams.set("context", id); history.replaceState({}, "", url);
  } catch (error) { toast(error.message, true); }
}

function closeDrawer() {
  $("#drawer-backdrop").classList.add("hidden");
  $("#context-drawer").classList.remove("open");
  $("#context-drawer").setAttribute("aria-hidden", "true");
  state.selectedId = null;
  const url = new URL(location.href); url.searchParams.delete("context"); history.replaceState({}, "", url);
}

function openModal(id) { $(`#${id}`).classList.remove("hidden"); setTimeout(() => $("input:not([type=hidden]),textarea", $(`#${id}`))?.focus(), 30); }
function closeModal(element) { element.closest(".modal-backdrop")?.classList.add("hidden"); }

function openContextModal(context = null) {
  const form = $("#context-form"); form.reset();
  form.elements.context_id.value = context?.id || "";
  $("#modal-mode").textContent = context ? "MODIFIER LE CONTEXTE" : "NOUVEAU CONTEXTE";
  $("#context-modal-title").textContent = context ? context.title : "Créer un contexte";
  $("#delete-context").classList.toggle("hidden", !context);
  if (context) {
    for (const field of ["title", "summary", "context_type", "status", "priority", "owner_name"]) form.elements[field].value = context[field] || "";
    form.elements.tags.value = (context.tags || []).join(", ");
    form.elements.due_at.value = context.due_at ? context.due_at.slice(0, 10) : "";
  }
  openModal("context-modal");
}

async function saveContext(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const values = Object.fromEntries(new FormData(form));
  const id = values.context_id; delete values.context_id;
  values.tags = values.tags.split(",").map((tag) => tag.trim()).filter(Boolean);
  if (values.due_at) values.due_at = `${values.due_at}T17:00:00Z`; else delete values.due_at;
  const button = $("button[type=submit]", form); button.disabled = true;
  try {
    const context = await api(id ? `/api/v1/contexts/${id}` : "/api/v1/contexts", { method: id ? "PATCH" : "POST", body: JSON.stringify(values) });
    closeModal(button); toast(id ? "Contexte mis à jour" : "Contexte créé"); await loadContexts(); openContext(context.id);
  } catch (error) { toast(error.message, true); } finally { button.disabled = false; }
}

async function deleteContext() {
  const id = $("#context-form").elements.context_id.value;
  if (!id || !confirm("Supprimer ce contexte et tous ses rattachements ? Les données dans Gmail, Drive, Calendar, Chat et Odoo resteront intactes.")) return;
  try { await api(`/api/v1/contexts/${id}`, { method: "DELETE" }); state.selectedIds.delete(id); closeModal($("#delete-context")); closeDrawer(); toast("Contexte supprimé"); await Promise.all([loadContexts(), loadBrowserContexts($("#browser-context-search").value.trim())]); }
  catch (error) { toast(error.message, true); }
}

async function deleteContexts(ids) {
  const uniqueIds = [...new Set(ids)].filter(Boolean);
  if (!uniqueIds.length) return;
  const message = uniqueIds.length === 1
    ? "Supprimer ce contexte ? Les ressources dans les applications sources resteront intactes."
    : `Supprimer les ${uniqueIds.length} contextes sélectionnés ? Les ressources sources resteront intactes.`;
  if (!confirm(message)) return;
  try {
    const result = await api("/api/v1/contexts/bulk-delete", { method: "POST", body: JSON.stringify({ ids: uniqueIds }) });
    uniqueIds.forEach((id) => state.selectedIds.delete(id));
    if (state.selectedId && uniqueIds.includes(state.selectedId)) closeDrawer();
    toast(`${result.deleted} contexte${result.deleted !== 1 ? "s" : ""} supprimé${result.deleted !== 1 ? "s" : ""}`);
    await Promise.all([loadContexts(), loadBrowserContexts($("#browser-context-search").value.trim())]);
  } catch (error) { toast(error.message, true); }
}

async function saveResource(event) {
  event.preventDefault(); if (!state.selectedId) return;
  const form = event.currentTarget; const values = Object.fromEntries(new FormData(form)); values.resource_type = "item";
  const button = $("button[type=submit]", form); button.disabled = true;
  try { await api(`/api/v1/contexts/${state.selectedId}/resources`, { method: "POST", body: JSON.stringify(values) }); closeModal(button); form.reset(); toast("Ressource rattachée"); await Promise.all([openContext(state.selectedId), loadContexts()]); }
  catch (error) { toast(error.message, true); } finally { button.disabled = false; }
}

async function removeResource(event) {
  const button = event.currentTarget;
  if (!confirm("Détacher cette ressource ? La donnée source ne sera pas supprimée.")) return;
  try { await api(`/api/v1/contexts/${button.dataset.context}/resources/${button.dataset.deleteResource}`, { method: "DELETE" }); toast("Ressource détachée"); await Promise.all([openContext(button.dataset.context), loadContexts()]); }
  catch (error) { toast(error.message, true); }
}

function showView(view) {
  state.view = view;
  $("#contexts-view").classList.toggle("hidden", view !== "contexts");
  $("#applications-view").classList.toggle("hidden", view !== "applications");
  $("#settings-view").classList.toggle("hidden", view !== "settings");
  $("#search").disabled = view !== "contexts";
  $("#create-context").classList.toggle("hidden", view === "applications");
  $$(".nav-button[data-view]").forEach((button) => button.classList.toggle("active", button.dataset.view === view));
  $$(".integrated-app-button").forEach((button) => button.classList.toggle("active", view === "applications" && button.dataset.app === state.browser.app));
  $(".sidebar").classList.remove("open");
  if (view === "settings") loadConnectors();
  if (browserResourcePoll) { clearInterval(browserResourcePoll); browserResourcePoll = null; }
  if (view === "applications") {
    Promise.all([loadBrowserStatus(), loadBrowserContexts()]);
    browserResourcePoll = setInterval(() => refreshBrowserResource(true), 3000);
  }
}

function connectorStatusLabel(connector) {
  if (connector.status === "connected") return "Connecté";
  if (connector.status === "configured") return "Prêt à connecter";
  if (connector.status === "error") return "Erreur";
  return "Non configuré";
}

function statsHtml(provider, stats) {
  const labels = provider === "google"
    ? { gmail_threads: "Fils Gmail", drive_files_sample: "Fichiers Drive détectés", upcoming_events: "Événements à venir", chat_spaces: "Espaces Chat" }
    : { contacts: "Contacts", opportunities: "Opportunités", projects: "Projets", server_version: "Version serveur" };
  return Object.entries(stats).filter(([key]) => labels[key]).map(([key, value]) => `<div class="connector-stat"><strong>${escapeHtml(value)}</strong><span>${labels[key]}</span></div>`).join("");
}

function renderConnector(connector) {
  const provider = connector.provider;
  const status = $(`#${provider}-status`);
  status.textContent = connectorStatusLabel(connector);
  status.className = `connection-pill ${connector.status}`;
  const account = $(`#${provider}-account`);
  account.textContent = connector.external_account ? `Connecté avec ${connector.external_account}` : "";
  account.classList.toggle("hidden", !connector.external_account);
  const stats = $(`#${provider}-stats`);
  stats.innerHTML = statsHtml(provider, connector.stats || {});
  stats.classList.toggle("hidden", !stats.innerHTML);
  const error = $(`#${provider}-error`);
  error.textContent = connector.last_error || "";
  error.classList.toggle("hidden", !connector.last_error);
  const connected = connector.status === "connected";
  $(`#${provider}-actions`).classList.toggle("hidden", !connected);
  if (provider === "google") {
    $("#google-connect").classList.toggle("hidden", !connector.configured || connected);
    $("#google-redirect-uri").textContent = connector.configuration.redirect_uri || `${location.origin}/api/v1/connectors/google/callback`;
    if (connector.configuration.client_id) $("#google-form").elements.client_id.value = connector.configuration.client_id;
  } else {
    for (const field of ["url", "database", "username"]) if (connector.configuration[field]) $("#odoo-form").elements[field].value = connector.configuration[field];
    if (connected) $("#odoo-form").classList.add("hidden"); else $("#odoo-form").classList.remove("hidden");
    const odooButton = $('.integrated-app-button[data-app="odoo"]');
    if (connector.configuration.url) odooButton.dataset.url = connector.configuration.url;
  }
}

async function loadConnectors() {
  try { const connectors = await api("/api/v1/connectors"); state.connectors = Object.fromEntries(connectors.map((item) => [item.provider, item])); connectors.forEach(renderConnector); }
  catch (error) { toast(error.message, true); }
}

async function configureGoogle(event) {
  event.preventDefault(); const form = event.currentTarget; const button = $("button[type=submit]", form); button.disabled = true;
  try { const connector = await api("/api/v1/connectors/google/configure", { method: "POST", body: JSON.stringify(Object.fromEntries(new FormData(form))) }); state.connectors.google = connector; renderConnector(connector); form.elements.client_secret.value = ""; toast("Configuration OAuth enregistrée. Vous pouvez connecter Google."); }
  catch (error) { toast(error.message, true); } finally { button.disabled = false; }
}

function connectGoogle() {
  const popup = window.open("/api/v1/connectors/google/authorize", "context-hub-google-oauth", "popup,width=560,height=720");
  if (!popup) toast("Autorisez les fenêtres contextuelles pour lancer OAuth Google", true);
}

async function configureOdoo(event) {
  event.preventDefault(); const form = event.currentTarget; const button = $("button[type=submit]", form); button.disabled = true;
  try { const connector = await api("/api/v1/connectors/odoo/configure", { method: "POST", body: JSON.stringify(Object.fromEntries(new FormData(form))) }); state.connectors.odoo = connector; renderConnector(connector); form.elements.api_key.value = ""; toast("Connexion Odoo validée"); }
  catch (error) { toast(error.message, true); } finally { button.disabled = false; }
}

async function syncConnector(event) {
  const provider = event.currentTarget.dataset.sync; event.currentTarget.disabled = true;
  try { const connector = await api(`/api/v1/connectors/${provider}/sync`, { method: "POST" }); state.connectors[provider] = connector; renderConnector(connector); toast(`${provider === "google" ? "Google Workspace" : "Odoo"} actualisé`); }
  catch (error) { toast(error.message, true); } finally { event.currentTarget.disabled = false; }
}

async function disconnectConnector(event) {
  const provider = event.currentTarget.dataset.disconnect;
  if (!confirm(`Déconnecter ${provider === "google" ? "Google Workspace" : "Odoo"} et supprimer les identifiants enregistrés ?`)) return;
  try { await api(`/api/v1/connectors/${provider}`, { method: "DELETE" }); toast("Connecteur déconnecté"); await loadConnectors(); if (provider === "odoo") $("#odoo-form").classList.remove("hidden"); }
  catch (error) { toast(error.message, true); }
}

function setBrowserResource(resource) {
  state.browser.resource = resource || null;
  $("#browser-resource-title").textContent = resource?.title || "Aucune page détectée";
  $("#browser-resource-url").textContent = resource?.url || "Ouvrez un email, un fichier, un événement ou une fiche.";
  $("#browser-attach").disabled = !resource || !state.browser.selectedId;
}

async function loadBrowserStatus() {
  try {
    const status = await api("/api/v1/browser/status");
    state.browser.status = status;
    const frame = $("#embedded-browser");
    if (status.public_url && frame.dataset.url !== status.public_url) {
      frame.dataset.url = status.public_url;
      frame.src = status.public_url;
    }
    $("#browser-status").textContent = status.ready ? "Chromium Docker connecté · profil persistant" : "Chromium Docker démarre…";
    setBrowserResource(status.current);
    return status;
  } catch (error) {
    $("#browser-status").textContent = "Navigateur intégré indisponible";
    throw error;
  }
}

async function waitForBrowser() {
  for (let attempt = 0; attempt < 20; attempt += 1) {
    const status = await loadBrowserStatus();
    if (status.ready) return status;
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  throw new Error("Chromium met trop de temps à démarrer. Vérifiez le conteneur chromium.");
}

async function refreshBrowserResource(silent = false) {
  try {
    const result = await api("/api/v1/browser/current");
    setBrowserResource(result.resource);
  } catch (error) { if (!silent) toast(error.message, true); }
}

function renderBrowserContexts() {
  $("#browser-context-list").innerHTML = state.browser.contexts.map((context) => `<label class="browser-context-choice ${context.id === state.browser.selectedId ? "selected" : ""}" data-id="${context.id}"><input type="radio" name="browser-context" ${context.id === state.browser.selectedId ? "checked" : ""}><span><strong>${escapeHtml(context.title)}</strong><small>${escapeHtml(context.summary || typeLabels[context.context_type] || context.context_type)}</small></span><em>${context.resource_count}</em></label>`).join("");
  $("#browser-context-empty").classList.toggle("hidden", state.browser.contexts.length !== 0);
  $$(".browser-context-choice").forEach((choice) => choice.addEventListener("click", () => { state.browser.selectedId = choice.dataset.id; renderBrowserContexts(); $("#browser-attach").disabled = !state.browser.resource; }));
}

async function loadBrowserContexts(query = "") {
  try {
    state.browser.contexts = await api(`/api/v1/contexts${query ? `?q=${encodeURIComponent(query)}` : ""}`);
    renderBrowserContexts();
  } catch (error) { toast(error.message, true); }
}

async function attachBrowserResource() {
  if (!state.browser.resource || !state.browser.selectedId) return;
  const button = $("#browser-attach"); button.disabled = true;
  try {
    await api(`/api/v1/contexts/${state.browser.selectedId}/resources`, { method: "POST", body: JSON.stringify(state.browser.resource) });
    toast("Ressource rattachée au contexte");
    await Promise.all([loadContexts(), loadBrowserContexts($("#browser-context-search").value.trim())]);
  } catch (error) { toast(error.message, true); } finally { button.disabled = false; }
}

async function createBrowserContext(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const button = $("button[type=submit]", form);
  const values = Object.fromEntries(new FormData(form));
  button.disabled = true;
  try {
    const context = await api("/api/v1/contexts", { method: "POST", body: JSON.stringify(values) });
    state.browser.selectedId = context.id;
    let attachError = null;
    if (state.browser.resource) { try { await api(`/api/v1/contexts/${context.id}/resources`, { method: "POST", body: JSON.stringify(state.browser.resource) }); } catch (error) { attachError = error; } }
    form.reset(); form.classList.add("hidden");
    await Promise.all([loadContexts(), loadBrowserContexts()]);
    toast(attachError ? `Contexte créé, mais rattachement impossible : ${attachError.message}` : state.browser.resource ? "Contexte créé et ressource rattachée" : "Contexte créé", Boolean(attachError));
  } catch (error) { toast(`Création impossible : ${error.message}`, true); } finally { button.disabled = false; }
}

async function openEmbeddedUrl(url, app) {
  state.browser.app = app;
  $("#browser-app-title").textContent = sourceMeta[app]?.label || "Application";
  showView("applications");
  try {
    await waitForBrowser();
    const result = await api("/api/v1/browser/navigate", { method: "POST", body: JSON.stringify({ url }) });
    if (result.current) setBrowserResource(result.current);
    setTimeout(refreshBrowserResource, 1200);
    setTimeout(refreshBrowserResource, 3500);
  } catch (error) { toast(error.message, true); }
}

function openApplication(event) {
  const button = event.currentTarget; const url = button.dataset.url;
  if (!url) { showView("settings"); toast("Configurez d’abord l’URL Odoo"); return; }
  openEmbeddedUrl(url, button.dataset.app);
}

function bindEvents() {
  $("#create-context").addEventListener("click", () => openContextModal());
  $("#empty-create").addEventListener("click", () => openContextModal());
  $("#context-form").addEventListener("submit", saveContext);
  $("#delete-context").addEventListener("click", deleteContext);
  $("#resource-form").addEventListener("submit", saveResource);
  $("#drawer-backdrop").addEventListener("click", closeDrawer);
  $$(".modal-close").forEach((button) => button.addEventListener("click", () => closeModal(button)));
  $$(".modal-backdrop").forEach((backdrop) => backdrop.addEventListener("mousedown", (event) => { if (event.target === backdrop) backdrop.classList.add("hidden"); }));
  $$(".nav-button[data-view]").forEach((button) => button.addEventListener("click", () => showView(button.dataset.view)));
  $$(".integrated-app-button").forEach((button) => button.addEventListener("click", openApplication));
  $("#select-all-contexts").addEventListener("change", (event) => { state.contexts.forEach((context) => { if (event.currentTarget.checked) state.selectedIds.add(context.id); else state.selectedIds.delete(context.id); }); renderContexts(); });
  $("#delete-selected-contexts").addEventListener("click", () => deleteContexts([...state.selectedIds]));
  $("#browser-refresh").addEventListener("click", refreshBrowserResource);
  $("#browser-context-refresh").addEventListener("click", () => Promise.all([refreshBrowserResource(), loadBrowserContexts($("#browser-context-search").value.trim())]));
  $("#browser-attach").addEventListener("click", attachBrowserResource);
  $("#browser-create-toggle").addEventListener("click", () => $("#browser-create-form").classList.toggle("hidden"));
  $("#browser-create-form").addEventListener("submit", createBrowserContext);
  $("#embedded-browser").addEventListener("load", () => setTimeout(() => $("#browser-loader").classList.add("hidden"), 500));
  let browserSearchTimer;
  $("#browser-context-search").addEventListener("input", (event) => { clearTimeout(browserSearchTimer); browserSearchTimer = setTimeout(() => loadBrowserContexts(event.target.value.trim()), 220); });
  $("#mobile-menu").addEventListener("click", () => $(".sidebar").classList.toggle("open"));
  $$(".segmented button").forEach((button) => button.addEventListener("click", () => { $$(".segmented button").forEach((item) => item.classList.remove("active")); button.classList.add("active"); state.status = button.dataset.filter; loadContexts(); }));
  let searchTimer;
  $("#search").addEventListener("input", (event) => { clearTimeout(searchTimer); searchTimer = setTimeout(() => { state.query = event.target.value.trim(); loadContexts(); }, 220); });
  $("#google-form").addEventListener("submit", configureGoogle);
  $("#google-connect").addEventListener("click", connectGoogle);
  $("#odoo-form").addEventListener("submit", configureOdoo);
  $$(".sync-button").forEach((button) => button.addEventListener("click", syncConnector));
  $$(".disconnect-button").forEach((button) => button.addEventListener("click", disconnectConnector));
  window.addEventListener("message", (event) => {
    if (event.origin !== location.origin) return;
    if (event.data?.type === "context-hub-oauth") { loadConnectors(); toast(event.data.success ? "Google Workspace connecté" : "Connexion Google interrompue", !event.data.success); }
  });
  document.addEventListener("keydown", (event) => { if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") { event.preventDefault(); showView("contexts"); $("#search").focus(); } if (event.key === "Escape") { $$(".modal-backdrop:not(.hidden)").forEach((item) => item.classList.add("hidden")); if ($("#context-drawer").classList.contains("open")) closeDrawer(); } });
}

async function init() {
  bindEvents();
  await Promise.all([loadContexts(), loadConnectors()]);
  loadBrowserStatus().catch(() => {});
  const params = new URLSearchParams(location.search);
  if (params.get("context")) openContext(params.get("context"));
  if (params.get("view") === "settings") showView("settings");
}

init();
