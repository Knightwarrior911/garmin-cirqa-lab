"use strict";
// No service-worker cache: health responses and authenticated HTML stay private.
window.addEventListener("pageshow", (event) => {
  if (event.persisted) location.reload();
});
const safeArea = document.createElement("style");
safeArea.textContent = "body{padding-top:env(safe-area-inset-top);padding-right:env(safe-area-inset-right);padding-bottom:env(safe-area-inset-bottom);padding-left:env(safe-area-inset-left)}.account-control{font:inherit;font-size:12px;padding:7px 10px;border:1px solid #dfe5df;border-radius:8px;background:white;color:#204e40;cursor:pointer;white-space:nowrap}.account-control:focus-visible{outline:3px solid #527ca4;outline-offset:3px}header{flex-wrap:wrap}";
document.head.append(safeArea);
(async () => {
  try {
    const response = await fetch("/api/health", { cache: "no-store" });
    if (!response.ok) return;
    const health = await response.json();
    if (health.hosting !== "cloud") return;
    const footer = document.querySelector("footer");
    if (footer) footer.textContent = "Private cloud history · Sync your CIRQA through Garmin Connect on iPhone to upload new readings. Cloud refresh runs daily and every 30 minutes while open. Safari → Share → Add to Home Screen.";
    const button = document.createElement("button");
    button.type = "button";
    button.className = "account-control";
    button.textContent = "Sign out";
    button.onclick = async () => {
      button.disabled = true;
      try {
        const result = await fetch("/auth/logout", { method: "POST", headers: { "X-CIRQA-Request": "1" } });
        if (result.ok || result.status === 401) {
          location.replace("/login");
          return;
        }
        throw new Error("Sign-out failed");
      } catch {
        button.disabled = false;
        button.textContent = "Retry sign out";
      }
    };
    document.querySelector("header")?.append(button);
  } catch {
    // Existing data-fetch UI reports connectivity failures; no private cache fallback.
  }
})();
