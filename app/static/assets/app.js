const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

const state = {
  contexts: [],
  stats: null,
  query: "",
  status: "",
  source: "",
  showAll: false,
  selectedId: null,
  pendingOdoo: null,
};

const sources = {
  gmail: { label: "Gmail", icon: "i-mail" },
  chat: { label: "Google Chat", icon: "i-chat" },
  drive: { label: "Google Drive", icon: "i-drive" },
  calendar: { label: "Calendar", icon: "i-calendar" },
  odoo: { label: "Odoo", icon: "i-odoo" },
};

const typeLabels = {
  project: "Projet",
  client: "Client",
  opportunity: "Opportunité",
  activity: "Activité",
  topic: "Sujet",
};

const activityLabels = {
  context_created: "Contexte créé",
  context_updated: "Contexte mis à jour",
  resource_added: "Ressource liée",
  resource_removed: "Ressource détachée",
};

function icon(id) {
  return `<svg aria-hidden="true"><use href="#${id}"></use></svg>`;
}

function escapeHtml(value = "") {
  const node = document.createElement("div");
  node.textContent = String(value);
  return node.innerHTML;
}

function initials(name = "") {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]).join("").toUpperCase() || "CH";
}

function relativeDate(value) {
  if (!value) return "Date inconnue";
  const date = new Date(value);
  const delta = date.getTime() - Date.now();
  const days = Math.round(delta / 86400000);
  if (Math.abs(days) > 1) return new Intl.RelativeTimeFormat("fr", { numeric: "auto" }).format(days, "day");
  const hours = Math.round(delta / 3600000);
  return new Intl.RelativeTimeFormat("fr", { numeric: "auto" }).format(hours, "hour");
}

function shortDate(value) {
  if (!value) return "Sans échéance";
  return new Intl.DateTimeFormat("fr-FR", { day: "numeric", month: "short" }).format(new Date(value));
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  if (!response.ok) {
    let message = "Une erreur est survenue";
    try {
      const body = await response.json();
      message = body.detail || message;
    } catch (_) { /* Response without JSON body. */ }
    throw new Error(typeof message === "string" ? message : "Les données saisies sont invalides");
  }
  return response.status === 204 ? null : response.json();
}

function showToast(message, error = false) {
  const toast = $("#toast");
  $("#toast-message").textContent = message;
  toast.classList.toggle("error", error);
  $(".toast-icon", toast).textContent = error ? "!" : "✓";
  toast.classList.add("show");
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => toast.classList.remove("show"), 2800);
}

function sourceIcons(context) {
  return context.sources.map((source) => {
    const item = sources[source] || { label: source, icon: "i-link" };
    return `<span class="source-icon ${source}" title="${item.label}">${icon(item.icon)}</span>`;
  }).join("");
}

function contextCard(context) {
  const tags = context.tags.slice(0, 3).map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`).join("");
  const priority = context.priority === "high" ? `<span class="priority-pill">Prioritaire</span>` : "";
  return `
    <article class="context-card" data-id="${context.id}" tabindex="0" style="--card-color:${escapeHtml(context.color)}">
      <div class="card-top">
        <span class="type-pill"><i></i>${typeLabels[context.context_type] || escapeHtml(context.context_type)}</span>
        ${priority}
      </div>
      <h3>${escapeHtml(context.title)}</h3>
      <p class="summary">${escapeHtml(context.summary || "Aucun résumé pour ce contexte.")}</p>
      <div class="tag-row">${tags}</div>
      <div class="resource-row">
        <div class="source-icons">${sourceIcons(context)}</div>
        <span class="resource-count">${context.resource_count} ressource${context.resource_count !== 1 ? "s" : ""}</span>
      </div>
      <div class="card-foot">
        <div class="avatar" style="background:${escapeHtml(context.color)}">${initials(context.owner_name)}</div>
        <div><strong>${escapeHtml(context.owner_name || "Non assigné")}</strong><small>Mis à jour ${relativeDate(context.updated_at)}</small></div>
        <span class="due">${icon("i-calendar")}${shortDate(context.due_at)}</span>
      </div>
    </article>`;
}

function renderContexts() {
  const grid = $("#contexts-grid");
  const empty = $("#empty-state");
  const visible = state.showAll ? state.contexts : state.contexts.slice(0, 6);
  grid.innerHTML = visible.map(contextCard).join("");
  grid.classList.toggle("hidden", visible.length === 0);
  empty.classList.toggle("hidden", visible.length !== 0);
  $$(".context-card", grid).forEach((card) => {
    card.addEventListener("click", () => openContext(card.dataset.id));
    card.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") openContext(card.dataset.id);
    });
  });
}

function updateFilterLabel() {
  const chip = $("#active-filter");
  const parts = [];
  if (state.source) parts.push(`Source : ${sources[state.source]?.label || state.source}`);
  if (state.query) parts.push(`Recherche : « ${state.query} »`);
  if (parts.length) {
    $("span", chip).textContent = parts.join(" · ");
    chip.classList.remove("hidden");
  } else {
    chip.classList.add("hidden");
  }
}

async function loadContexts() {
  const params = new URLSearchParams();
  if (state.query) params.set("q", state.query);
  if (state.status) params.set("status", state.status);
  if (state.source) params.set("source", state.source);
  try {
    state.contexts = await api(`/api/v1/contexts?${params}`);
    renderContexts();
    updateFilterLabel();
  } catch (error) {
    $("#contexts-grid").innerHTML = "";
    showToast(error.message, true);
  }
}

async function loadStats() {
  try {
    state.stats = await api("/api/v1/dashboard");
    $("#stat-active").textContent = state.stats.active_contexts;
    $("#stat-resources").textContent = state.stats.linked_resources;
    $("#stat-due").textContent = state.stats.due_soon;
    $("#nav-count").textContent = state.stats.total_contexts;
    $$(".source-count").forEach((element) => {
      element.textContent = state.stats.by_source[element.dataset.count] || 0;
    });
  } catch (error) {
    showToast(error.message, true);
  }
}

function resourceItem(resource, contextId) {
  const source = sources[resource.source] || { label: resource.source, icon: "i-link" };
  return `
    <article class="resource-item">
      <span class="source-icon ${resource.source}">${icon(source.icon)}</span>
      <div class="resource-main">
        <a href="${escapeHtml(resource.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(resource.title)}</a>
        <p>${escapeHtml(resource.excerpt || `${source.label} · ${resource.resource_type}`)}</p>
        <small>${source.label} · ${relativeDate(resource.occurred_at)}${resource.author_name ? ` · ${escapeHtml(resource.author_name)}` : ""}</small>
      </div>
      <div class="resource-actions">
        <a href="${escapeHtml(resource.url)}" target="_blank" rel="noopener noreferrer" aria-label="Ouvrir la ressource">${icon("i-external")}</a>
        <button data-delete-resource="${resource.id}" data-context="${contextId}" aria-label="Détacher la ressource">${icon("i-trash")}</button>
      </div>
    </article>`;
}

function activityItem(activity) {
  return `
    <div class="activity-item">
      <strong>${activityLabels[activity.action] || escapeHtml(activity.action)} · ${escapeHtml(activity.detail)}</strong>
      <small>${escapeHtml(activity.actor)} · ${relativeDate(activity.created_at)}</small>
    </div>`;
}

function renderDrawer(context) {
  const tags = context.tags.map((tag) => `<span>${escapeHtml(tag)}</span>`).join("");
  const resourcesHtml = context.resources.length
    ? context.resources.map((resource) => resourceItem(resource, context.id)).join("")
    : `<div class="drawer-empty">Aucune ressource liée. Ajoutez le premier raccourci vers Gmail, Chat, Drive, Calendar ou Odoo.</div>`;
  const activitiesHtml = context.activities.length
    ? context.activities.slice(0, 8).map(activityItem).join("")
    : `<div class="drawer-empty">L’activité apparaîtra ici.</div>`;
  $("#drawer-content").innerHTML = `
    <div class="drawer-hero">
      <div class="drawer-toolbar">
        <span class="type-pill"><i></i>${typeLabels[context.context_type] || escapeHtml(context.context_type)}</span>
        <button class="icon-btn drawer-close" aria-label="Fermer">${icon("i-close")}</button>
      </div>
      <h2>${escapeHtml(context.title)}</h2>
      <p>${escapeHtml(context.summary || "Aucun résumé pour ce contexte.")}</p>
      <div class="drawer-meta">${tags}<span>${escapeHtml(context.owner_name || "Non assigné")}</span><span>Échéance · ${shortDate(context.due_at)}</span></div>
    </div>
    <div class="drawer-body">
      <div class="drawer-section-head"><div><h3>Ressources liées</h3><small>${context.resource_count} raccourci${context.resource_count !== 1 ? "s" : ""}, aucune copie</small></div><button class="add-link-btn" id="drawer-add-resource">${icon("i-plus")}Lier une ressource</button></div>
      <div class="resource-list">${resourcesHtml}</div>
      <div class="activity-section">
        <div class="drawer-section-head"><div><h3>Activité du contexte</h3><small>Dernières modifications</small></div></div>
        <div class="activity-list">${activitiesHtml}</div>
      </div>
    </div>`;
  $(".drawer-close").addEventListener("click", closeDrawer);
  $("#drawer-add-resource").addEventListener("click", () => openModal("resource-modal"));
  $$('[data-delete-resource]').forEach((button) => button.addEventListener("click", deleteResource));
}

async function openContext(id) {
  state.selectedId = id;
  try {
    const context = await api(`/api/v1/contexts/${id}`);
    renderDrawer(context);
    $("#drawer-backdrop").classList.remove("hidden");
    const drawer = $("#context-drawer");
    drawer.classList.add("open");
    drawer.setAttribute("aria-hidden", "false");
    const url = new URL(window.location.href);
    url.searchParams.set("context", id);
    history.replaceState({}, "", url);
  } catch (error) {
    showToast(error.message, true);
  }
}

function closeDrawer() {
  $("#context-drawer").classList.remove("open");
  $("#context-drawer").setAttribute("aria-hidden", "true");
  $("#drawer-backdrop").classList.add("hidden");
  state.selectedId = null;
  const url = new URL(window.location.href);
  url.searchParams.delete("context");
  history.replaceState({}, "", url);
}

async function deleteResource(event) {
  const button = event.currentTarget;
  if (!window.confirm("Détacher cette ressource du contexte ? La donnée source ne sera pas supprimée.")) return;
  try {
    await api(`/api/v1/contexts/${button.dataset.context}/resources/${button.dataset.deleteResource}`, { method: "DELETE" });
    showToast("Ressource détachée — la donnée source est intacte");
    await Promise.all([openContext(button.dataset.context), loadContexts(), loadStats()]);
  } catch (error) {
    showToast(error.message, true);
  }
}

function openModal(id) {
  $(`#${id}`).classList.remove("hidden");
  setTimeout(() => $("input:not([type=radio]), textarea", $(`#${id}`))?.focus(), 30);
}

function closeModal(backdrop) {
  backdrop.classList.add("hidden");
  $("form", backdrop)?.reset();
  if (backdrop.id === "resource-modal") {
    $$(".source-picker label", backdrop).forEach((label, index) => label.classList.toggle("selected", index === 0));
  }
}

async function createContext(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const data = Object.fromEntries(new FormData(form));
  data.tags = data.tags.split(",").map((tag) => tag.trim()).filter(Boolean);
  if (!data.due_at) delete data.due_at;
  else data.due_at = `${data.due_at}T17:00:00Z`;
  const submit = $("button[type=submit]", form);
  submit.disabled = true;
  try {
    const context = await api("/api/v1/contexts", { method: "POST", body: JSON.stringify(data) });
    if (state.pendingOdoo) {
      const pending = state.pendingOdoo;
      await api(`/api/v1/contexts/${context.id}/resources`, {
        method: "POST",
        body: JSON.stringify({
          source: "odoo",
          external_id: `${pending.model}:${pending.id}`,
          title: pending.title || `${pending.model} #${pending.id}`,
          url: pending.url || window.location.origin,
          resource_type: pending.model,
          excerpt: "Ressource rattachée depuis le bouton Context Hub dans Odoo.",
          extra: { model: pending.model, record_id: pending.id },
        }),
      });
      state.pendingOdoo = null;
      history.replaceState({}, "", window.location.pathname);
    }
    closeModal($("#context-modal"));
    showToast("Contexte créé");
    await Promise.all([loadContexts(), loadStats()]);
    openContext(context.id);
  } catch (error) {
    showToast(error.message, true);
  } finally {
    submit.disabled = false;
  }
}

async function createResource(event) {
  event.preventDefault();
  if (!state.selectedId) return;
  const form = event.currentTarget;
  const data = Object.fromEntries(new FormData(form));
  data.resource_type = data.source === "gmail" ? "thread" : data.source === "calendar" ? "event" : data.source === "odoo" ? "record" : "item";
  const submit = $("button[type=submit]", form);
  submit.disabled = true;
  try {
    await api(`/api/v1/contexts/${state.selectedId}/resources`, { method: "POST", body: JSON.stringify(data) });
    closeModal($("#resource-modal"));
    showToast("Ressource liée au contexte");
    await Promise.all([openContext(state.selectedId), loadContexts(), loadStats()]);
  } catch (error) {
    showToast(error.message, true);
  } finally {
    submit.disabled = false;
  }
}

function bindEvents() {
  $("#new-context").addEventListener("click", () => openModal("context-modal"));
  $("#empty-create").addEventListener("click", () => openModal("context-modal"));
  $("#context-form").addEventListener("submit", createContext);
  $("#resource-form").addEventListener("submit", createResource);
  $("#drawer-backdrop").addEventListener("click", closeDrawer);
  $$(".modal-close, .modal-cancel").forEach((button) => button.addEventListener("click", () => closeModal(button.closest(".modal-backdrop"))));
  $$(".modal-backdrop").forEach((backdrop) => backdrop.addEventListener("mousedown", (event) => {
    if (event.target === backdrop) closeModal(backdrop);
  }));
  $$(".source-picker input").forEach((input) => input.addEventListener("change", () => {
    $$(".source-picker label").forEach((label) => label.classList.toggle("selected", $("input", label).checked));
  }));

  let searchTimer;
  $("#global-search").addEventListener("input", (event) => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      state.query = event.target.value.trim();
      state.showAll = true;
      loadContexts();
    }, 260);
  });
  document.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      $("#global-search").focus();
    }
    if (event.key === "Escape") {
      $$(".modal-backdrop:not(.hidden)").forEach(closeModal);
      if ($("#context-drawer").classList.contains("open")) closeDrawer();
    }
  });

  $$(".filter-btn").forEach((button) => button.addEventListener("click", () => {
    $$(".filter-btn").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    state.status = button.dataset.status;
    loadContexts();
  }));
  $$(".source-nav").forEach((button) => button.addEventListener("click", () => {
    $$(".nav-item").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    state.source = button.dataset.source;
    state.showAll = true;
    $("#list-title").textContent = `Contextes liés à ${sources[state.source].label}`;
    $("#list-subtitle").textContent = "Les données restent hébergées dans leur système source";
    loadContexts();
    $(".sidebar").classList.remove("mobile-open");
  }));
  $("#active-filter button").addEventListener("click", () => {
    state.source = "";
    state.query = "";
    $("#global-search").value = "";
    $$(".nav-item").forEach((item) => item.classList.remove("active"));
    $('.nav-item[data-nav="dashboard"]').classList.add("active");
    $("#list-title").textContent = "Contextes récents";
    $("#list-subtitle").textContent = "Vos sujets les plus récemment mis à jour";
    loadContexts();
  });
  $("#see-all").addEventListener("click", () => {
    state.showAll = !state.showAll;
    $("#see-all").innerHTML = `${state.showAll ? "Réduire" : "Tout afficher"} ${icon("i-chevron")}`;
    renderContexts();
  });
  $$(".main-nav .nav-item[data-nav]").forEach((button) => button.addEventListener("click", () => {
    $$(".nav-item").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    state.source = "";
    state.status = button.dataset.nav === "favorites" ? "watching" : "";
    state.showAll = button.dataset.nav !== "dashboard";
    $("#list-title").textContent = button.dataset.nav === "recent" ? "Activité récente" : button.dataset.nav === "favorites" ? "Contextes à suivre" : button.dataset.nav === "contexts" ? "Tous les contextes" : "Contextes récents";
    loadContexts();
    $(".sidebar").classList.remove("mobile-open");
  }));
  $("#mobile-menu").addEventListener("click", () => $(".sidebar").classList.toggle("mobile-open"));
}

async function init() {
  bindEvents();
  await Promise.all([loadContexts(), loadStats()]);
  const queryParams = new URLSearchParams(window.location.search);
  const initialContext = queryParams.get("context");
  if (initialContext) openContext(initialContext);
  if (queryParams.get("odoo_model") && queryParams.get("odoo_id")) {
    state.pendingOdoo = {
      model: queryParams.get("odoo_model"),
      id: queryParams.get("odoo_id"),
      title: queryParams.get("odoo_title"),
      url: queryParams.get("odoo_url"),
    };
    const form = $("#context-form");
    form.elements.title.value = queryParams.get("odoo_title") || `Contexte · ${queryParams.get("odoo_model")} #${queryParams.get("odoo_id")}`;
    form.elements.summary.value = "Contexte créé depuis Odoo. Complétez le résumé pour préciser le périmètre métier.";
    form.elements.context_type.value = queryParams.get("odoo_model") === "crm.lead" ? "opportunity" : queryParams.get("odoo_model") === "res.partner" ? "client" : "project";
    openModal("context-modal");
    showToast("Créez le contexte qui sera automatiquement lié à cet enregistrement Odoo");
  }
}

init();
