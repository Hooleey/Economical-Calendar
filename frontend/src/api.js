const DEFAULT_API_BASE = "http://127.0.0.1:8000";

const viteEnv = typeof import.meta !== "undefined" ? import.meta.env : {};
const viteBase = typeof viteEnv.VITE_API_BASE === "string" ? viteEnv.VITE_API_BASE.trim() : "";

const viteDev = viteEnv.DEV === true;
const viteProd = viteEnv.PROD === true;
/** In dev use Vite proxy to backend when base is unset. */
const useDevSameOriginProxy = viteDev && !viteBase;

/** Machine-readable marker for Events/News loaders (paired with strings `events.<code>`). */
export const API_CONFIG_ERROR_PREFIX = "__API_CFG__";

function normalizeApiError(payload, status) {
  if (!payload || typeof payload !== "string") return `HTTP ${status}`;
  const trimmed = payload.trim();
  if (trimmed.startsWith("{") && trimmed.endsWith("}")) {
    try {
      const j = JSON.parse(trimmed);
      if (j?.detail !== undefined && j.detail !== null) return String(j.detail);
    } catch {
      /* keep text */
    }
  }
  return trimmed || `HTTP ${status}`;
}

/** GitHub Pages is static HTTPS; localhost API base baked at build cannot work here. */
export function apiConfigurationBlockedReason() {
  if (typeof window === "undefined") return null;
  if (!viteProd || !String(window.location.hostname).endsWith("github.io")) return null;

  const base = viteBase.toLowerCase();
  if (!base) return "githubPagesNoApiBase";
  if (base.includes("127.0.0.1") || base.includes("localhost")) return "githubPagesLocalhostApi";
  return null;
}

export function parseApiConfigError(err) {
  const m = err && typeof err.message === "string" ? err.message : "";
  if (m.startsWith(API_CONFIG_ERROR_PREFIX)) return m.slice(API_CONFIG_ERROR_PREFIX.length);
  return null;
}

function assertApiConfiguredForBrowser() {
  const r = apiConfigurationBlockedReason();
  if (r) throw new Error(API_CONFIG_ERROR_PREFIX + r);
}

function resolveApiBase() {
  if (viteBase) return viteBase.replace(/\/+$/, "");
  if (useDevSameOriginProxy) return "";
  /* Production build viewed not on gh.io (e.g. vite preview): keep localhost fallback. */
  return DEFAULT_API_BASE;
}

export function apiUrl(path) {
  const base = resolveApiBase();
  const p = String(path || "");
  if (!p.startsWith("/")) return `${base}/${p}`;
  return `${base}${p}`;
}

/** @returns {Promise<null | Record<string, unknown>>} */
export async function fetchBackendHealth() {
  const block = apiConfigurationBlockedReason();
  if (block) return { __apiConfigError: block };
  try {
    const res = await fetch(apiUrl("/health"));
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

export async function fetchEvents(filters = {}, options = {}) {
  assertApiConfiguredForBrowser();
  const params = new URLSearchParams();

  if (filters.country) params.set("country", filters.country);
  if (filters.regulator) params.set("regulator", filters.regulator);
  if (filters.importance) params.set("importance", filters.importance);
  if (options.onDate) params.set("on_date", options.onDate);
  if (options.autoRefresh !== undefined) {
    params.set("auto_refresh", String(Boolean(options.autoRefresh)));
  }

  const url = `${apiUrl("/events")}${params.toString() ? `?${params.toString()}` : ""}`;
  const res = await fetch(url);
  if (!res.ok) throw new Error("Failed to fetch events");
  return res.json();
}

export async function refreshEvents() {
  assertApiConfiguredForBrowser();
  const res = await fetch(apiUrl("/events/refresh"), { method: "POST" });
  if (!res.ok) {
    const err = await res.text();
    throw new Error(err || "Failed to refresh events");
  }
  return res.json();
}

export async function fetchEventDescription(eventId, lang) {
  assertApiConfiguredForBrowser();
  const params = new URLSearchParams();
  if (lang) params.set("lang", lang);
  const url = `${apiUrl(`/events/${eventId}/description`)}${params.toString() ? `?${params.toString()}` : ""}`;
  const res = await fetch(url);
  if (!res.ok) throw new Error("Failed to fetch event description");
  return res.json();
}

export async function fetchNews(filters = {}, options = {}) {
  assertApiConfiguredForBrowser();
  const params = new URLSearchParams();
  if (filters.source) params.set("source", filters.source);
  if (options.autoRefresh !== undefined) {
    params.set("auto_refresh", String(Boolean(options.autoRefresh)));
  }
  if (options.limit != null) params.set("limit", String(options.limit));
  const url = `${apiUrl("/news")}${params.toString() ? `?${params.toString()}` : ""}`;
  const res = await fetch(url);
  if (!res.ok) {
    const t = await res.text();
    throw new Error(normalizeApiError(t, res.status));
  }
  return res.json();
}

export async function refreshNews() {
  assertApiConfiguredForBrowser();
  const res = await fetch(apiUrl("/news/refresh"), { method: "POST" });
  if (!res.ok) {
    const t = await res.text();
    throw new Error(normalizeApiError(t, res.status));
  }
  return res.json();
}

export async function fetchNewsContent(articleId) {
  assertApiConfiguredForBrowser();
  const res = await fetch(apiUrl(`/news/${articleId}/content`));
  if (!res.ok) {
    const t = await res.text();
    throw new Error(normalizeApiError(t, res.status));
  }
  return res.json();
}
