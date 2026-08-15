const GOOGLE_APP_HOSTS = new Set([
  "mail.google.com",
  "chat.google.com",
  "drive.google.com",
  "docs.google.com",
  "sheets.google.com",
  "slides.google.com",
  "calendar.google.com"
]);

function matchPattern(value) {
  const url = new URL(value);
  return `${url.protocol}//${url.hostname}/*`;
}

async function replaceRegisteredScript(id, url, files) {
  try { await chrome.scripting.unregisterContentScripts({ ids: [id] }); } catch (_) { /* Not registered yet. */ }
  if (!url) return;
  await chrome.scripting.registerContentScripts([{
    id,
    matches: [matchPattern(url)],
    ...files,
    runAt: "document_idle",
    persistAcrossSessions: true
  }]);
}

async function registerOdooScript(odooUrl) {
  return replaceRegisteredScript("context-hub-odoo", odooUrl, {
    css: ["content.css"],
    js: ["content.js"]
  });
}

async function unregisterLegacyHubScript() {
  try { await chrome.scripting.unregisterContentScripts({ ids: ["context-hub-web"] }); }
  catch (_) { /* Already absent. */ }
}

async function initialize() {
  await chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true });
  const settings = await chrome.storage.local.get({ hubUrl: "http://localhost:8080", odooUrl: "" });
  await Promise.all([
    unregisterLegacyHubScript(),
    registerOdooScript(settings.odooUrl)
  ]);
}

async function isAllowedApplicationUrl(value) {
  let target;
  try { target = new URL(value); } catch (_) { return false; }
  if (target.protocol !== "https:" && target.protocol !== "http:") return false;
  if (target.protocol === "https:" && GOOGLE_APP_HOSTS.has(target.hostname)) return true;
  const settings = await chrome.storage.local.get({ hubUrl: "http://localhost:8080", odooUrl: "" });
  return [settings.hubUrl, settings.odooUrl]
    .filter(Boolean)
    .some((configured) => {
      try { return new URL(configured).origin === target.origin; } catch (_) { return false; }
    });
}

async function navigateTab(tab, url, panelPromise = Promise.resolve()) {
  if (!tab?.id || !(await isAllowedApplicationUrl(url))) throw new Error("Destination non autorisée");
  await panelPromise;
  await chrome.tabs.update(tab.id, { url });
  return { ok: true };
}

chrome.runtime.onInstalled.addListener(() => initialize().catch(console.error));
chrome.runtime.onStartup.addListener(() => initialize().catch(console.error));

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === "OPEN_PANEL" && sender.tab?.id) {
    chrome.sidePanel.open({ windowId: sender.tab.windowId })
      .then(() => sendResponse({ ok: true }))
      .catch((error) => sendResponse({ ok: false, error: error.message }));
    return true;
  }

  if (message.type === "GET_ACTIVE_RESOURCE") {
    chrome.tabs.query({ active: true, currentWindow: true }).then(async ([tab]) => {
      if (!tab?.id) return sendResponse({ resource: null });
      try { sendResponse(await chrome.tabs.sendMessage(tab.id, { type: "GET_RESOURCE" })); }
      catch (_) { sendResponse({ resource: null, tab: { title: tab.title, url: tab.url } }); }
    });
    return true;
  }

  if (message.type === "NAVIGATE_APP") {
    chrome.tabs.query({ active: true, currentWindow: true })
      .then(([tab]) => navigateTab(tab, message.url))
      .then(sendResponse)
      .catch((error) => sendResponse({ ok: false, error: error.message }));
    return true;
  }

  if (message.type === "REGISTER_ODOO") {
    registerOdooScript(message.url)
      .then(() => sendResponse({ ok: true }))
      .catch((error) => sendResponse({ ok: false, error: error.message }));
    return true;
  }

  return false;
});
