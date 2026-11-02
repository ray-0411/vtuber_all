// Local previews use the local API. Public pages use the Cloudflare Tunnel hostname.
const localHosts = new Set(["localhost", "127.0.0.1"]);
window.DASHBOARD_API = {
  baseUrl: localHosts.has(location.hostname) ? "" : "https://api.ray0411.win",
};
