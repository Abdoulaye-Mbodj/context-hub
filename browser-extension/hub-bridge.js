(() => {
  if (window.__contextHubWebBridgeInjected) return;

  async function isConfiguredHub() {
    if (["localhost", "127.0.0.1"].includes(location.hostname)) return true;
    const { hubUrl } = await chrome.storage.local.get({ hubUrl: "http://localhost:8080" });
    try { return new URL(hubUrl).origin === location.origin; } catch (_) { return false; }
  }

  function announce() {
    window.postMessage({
      type: "context-hub-extension-ready",
      version: chrome.runtime.getManifest().version
    }, location.origin);
  }

  async function requestNavigation(app, url) {
    try {
      const result = await chrome.runtime.sendMessage({
        type: "NAVIGATE_APP_IN_PLACE",
        app,
        url
      });
      if (!result?.ok) throw new Error(result?.error || "Navigation impossible");
    } catch (error) {
      window.postMessage({
        type: "context-hub-navigation-result",
        ok: false,
        error: error.message
      }, location.origin);
    }
  }

  async function start() {
    if (!(await isConfiguredHub())) return;
    window.__contextHubWebBridgeInjected = true;
    announce();

    document.addEventListener("click", (event) => {
      const target = event.target instanceof Element
        ? event.target.closest("[data-extension-launch][data-url]")
        : null;
      const url = target?.dataset.url || target?.dataset.workspaceUrl;
      if (!url) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      requestNavigation(target.dataset.app || target.dataset.workspaceApp, url);
    }, true);

    window.addEventListener("message", async (event) => {
      if (event.source !== window || event.origin !== location.origin) return;
      if (event.data?.type === "context-hub-extension-ping") return announce();
      if (event.data?.type !== "context-hub-open-app") return;
      requestNavigation(event.data.app, event.data.url);
    });
  }

  start();
})();
