(() => {
  if (window.__contextHubInjected) return;
  window.__contextHubInjected = true;

  function sourceFromLocation() {
    const host = location.hostname;
    if (host === "mail.google.com") return "gmail";
    if (host === "chat.google.com") return "chat";
    if (["drive.google.com", "docs.google.com", "sheets.google.com", "slides.google.com"].includes(host)) return "drive";
    if (host === "calendar.google.com") return "calendar";
    return "odoo";
  }

  function externalId(source) {
    const decodedHash = decodeURIComponent(location.hash || "");
    if (source === "gmail") return decodedHash.split("/").filter(Boolean).pop() || `gmail:${location.pathname}`;
    if (source === "chat") return location.pathname.split("/").filter(Boolean).slice(-2).join(":") || "chat:home";
    if (source === "drive") {
      const match = location.pathname.match(/\/(?:d|folders)\/([^/]+)/);
      return match?.[1] || new URLSearchParams(location.search).get("id") || `drive:${location.pathname}`;
    }
    if (source === "calendar") return decodedHash || `${location.pathname}${location.search}`;
    const hashParams = new URLSearchParams((location.hash || "").replace(/^#/, ""));
    const model = hashParams.get("model") || new URLSearchParams(location.search).get("model") || "odoo.record";
    const id = hashParams.get("id") || new URLSearchParams(location.search).get("id") || location.pathname;
    return `${model}:${id}`;
  }

  function resourceType(source) {
    if (source === "gmail") return "thread";
    if (source === "chat") return "space-or-message";
    if (source === "calendar") return "event";
    if (source === "odoo") return "record";
    return location.hostname === "drive.google.com" ? "drive-item" : "document";
  }

  function currentResource() {
    const source = sourceFromLocation();
    return {
      source,
      external_id: externalId(source),
      title: document.title.replace(/\s*[-–—]\s*(Gmail|Google Drive|Google Calendar|Google Chat|Odoo).*$/i, "").trim() || `${source} · élément courant`,
      url: location.href,
      resource_type: resourceType(source),
      excerpt: `Rattaché depuis ${document.title || location.hostname}`,
      extra: { captured_at: new Date().toISOString(), host: location.hostname }
    };
  }

  const button = document.createElement("button");
  button.id = "context-hub-attach-button";
  button.type = "button";
  button.setAttribute("aria-label", "Rattacher au contexte");
  button.innerHTML = `<span>⌘</span><b>Rattacher au contexte</b>`;
  button.addEventListener("click", () => chrome.runtime.sendMessage({ type: "OPEN_PANEL" }));
  document.documentElement.appendChild(button);

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message.type === "GET_RESOURCE") sendResponse({ resource: currentResource() });
  });
})();
