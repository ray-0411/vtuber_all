(() => {
  const nativeFetch = window.fetch.bind(window);
  const baseUrl = (window.DASHBOARD_API?.baseUrl || "").replace(/\/$/, "");

  window.dashboardFetch = (input, init) => {
    if (!baseUrl) return nativeFetch(input, init);
    const url = new URL(typeof input === "string" ? input : input.url, location.href);
    return nativeFetch(`${baseUrl}${url.pathname}${url.search}`, init);
  };
})();
