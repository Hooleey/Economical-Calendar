const DEFAULT_API_BASE = "http://127.0.0.1:8000";

/** In dev, prefer same-origin + Vite proxy (see vite.config.js) unless VITE_API_BASE is set. */
const viteEnv = typeof import.meta !== "undefined" ? import.meta.env : {};
const viteBase = typeof viteEnv.VITE_API_BASE === "string" ? viteEnv.VITE_API_BASE.trim() : "";
const useDevSameOriginProxy = viteEnv.DEV === true && !viteBase;
const API_BASE = (viteBase || (useDevSameOriginProxy ? "" : DEFAULT_API_BASE)).replace(/\/+$/, "");

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

function apiUrl(path) {
  const p = String(path || "");
  if (!p.startsWith("/")) return `${API_BASE}/${p}`;
  return `${API_BASE}${p}`;
}

/** @returns {Promise<null | Record<string, unknown>>} */
export async function fetchBackendHealth() {
  try {
    const res = await fetch(apiUrl("/health"));
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

export async function fetchEvents(filters = {}, options = {}) {
  const params = new URLSearchParams();

  if (filters.country) params.set("country", filters.country);
  if (filters.regulator) params.set("regulator", filters.regulator);
  if (filters.importance) params.set("importance", filters.importance);
  if (options.autoRefresh !== undefined) {
    params.set("auto_refresh", String(Boolean(options.autoRefresh)));
  }

  const url = `${apiUrl("/events")}${params.toString() ? `?${params.toString()}` : ""}`;
  const res = await fetch(url);
  if (!res.ok) throw new Error("Failed to fetch events");
  return res.json();
}

export async function refreshEvents() {
  const res = await fetch(apiUrl("/events/refresh"), { method: "POST" });
  if (!res.ok) {
    const err = await res.text();
    throw new Error(err || "Failed to refresh events");
  }
  return res.json();
}

export async function fetchEventDescription(eventId, lang) {
  const params = new URLSearchParams();
  if (lang) params.set("lang", lang);
  const url = `${apiUrl(`/events/${eventId}/description`)}${params.toString() ? `?${params.toString()}` : ""}`;
  const res = await fetch(url);
  if (!res.ok) throw new Error("Failed to fetch event description");
  return res.json();
}

export async function fetchNews(filters = {}, options = {}) {
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
  const res = await fetch(apiUrl("/news/refresh"), { method: "POST" });
  if (!res.ok) {
    const t = await res.text();
    throw new Error(normalizeApiError(t, res.status));
  }
  return res.json();
}

export async function fetchNewsContent(articleId) {
  const res = await fetch(apiUrl(`/news/${articleId}/content`));
  if (!res.ok) {
    const t = await res.text();
    throw new Error(normalizeApiError(t, res.status));
  }
  return res.json();
}
