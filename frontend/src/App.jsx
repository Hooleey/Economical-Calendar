import { useEffect, useMemo, useState } from "react";
import { BrowserRouter, HashRouter, Link, NavLink, Navigate, Route, Routes } from "react-router-dom";
import {
  fetchBackendHealth,
  fetchEventDescription,
  fetchEvents,
  fetchNewsContent,
  fetchNews,
  refreshEvents,
  refreshNews,
} from "./api";
import { useI18n } from "./i18n/I18nContext";
import "./styles.css";

function importanceClass(level) {
  if (level === "high") return "badge badge-high";
  if (level === "medium") return "badge badge-medium";
  return "badge badge-low";
}

function normalizeText(x) {
  return (x || "")
    .toString()
    .trim()
    .replace(/\s+/g, " ")
    .replace(/[.,]/g, "")
    .toLowerCase();
}

function countryKey(country, currency) {
  const c = normalizeText(country);
  const curr = (currency || "").toString().trim().toUpperCase();

  const byName = {
    "сша": "US",
    "соединенные штаты": "US",
    "united states": "US",
    "usa": "US",
    "великобритания": "GB",
    "united kingdom": "GB",
    "uk": "GB",
    "германия": "DE",
    "germany": "DE",
    "франция": "FR",
    "france": "FR",
    "италия": "IT",
    "italy": "IT",
    "испания": "ES",
    "spain": "ES",
    "канада": "CA",
    "canada": "CA",
    "япония": "JP",
    "japan": "JP",
    "китай": "CN",
    "china": "CN",
    "россия": "RU",
    "russia": "RU",
    "австралия": "AU",
    "australia": "AU",
    "новая зеландия": "NZ",
    "new zealand": "NZ",
    "швейцария": "CH",
    "switzerland": "CH",
    "швеция": "SE",
    "sweden": "SE",
    "норвегия": "NO",
    "norway": "NO",
    "турция": "TR",
    "turkey": "TR",
    "индия": "IN",
    "india": "IN",
    "бразилия": "BR",
    "brazil": "BR",
    "мексика": "MX",
    "mexico": "MX",
    "южная африка": "ZA",
    "south africa": "ZA",
    "сингапур": "SG",
    "singapore": "SG",
    "гонконг": "HK",
    "hong kong": "HK",
    "польша": "PL",
    "poland": "PL",
    "чехия": "CZ",
    "czech republic": "CZ",
    "румыния": "RO",
    "romania": "RO",
    "дания": "DK",
    "denmark": "DK",
    "финляндия": "FI",
    "finland": "FI",
    "португалия": "PT",
    "portugal": "PT",
    "нидерланды": "NL",
    "netherlands": "NL",
    "бельгия": "BE",
    "belgium": "BE",
    "ирландия": "IE",
    "ireland": "IE",
    "греция": "GR",
    "greece": "GR",
    "аргентина": "AR",
    "argentina": "AR",
    "чили": "CL",
    "chile": "CL",
    "колумбия": "CO",
    "colombia": "CO",
    "венгрия": "HU",
    "hungary": "HU",
    "корея": "KR",
    "республика корея": "KR",
    "south korea": "KR",
    "австрия": "AT",
    "austria": "AT",
    "еврозона": "EU",
    "eurozone": "EU"
  };
  if (c && byName[c]) return byName[c];

  const byCurrency = {
    USD: "US",
    EUR: "EU",
    GBP: "GB",
    JPY: "JP",
    CNY: "CN",
    RUB: "RU",
    CAD: "CA",
    AUD: "AU",
    NZD: "NZ",
    CHF: "CH",
    SEK: "SE",
    NOK: "NO",
    TRY: "TR",
    INR: "IN",
    BRL: "BR",
    MXN: "MX",
    ZAR: "ZA",
    SGD: "SG",
    HKD: "HK",
    KRW: "KR",
    PLN: "PL",
    CZK: "CZ",
    HUF: "HU",
    RON: "RO",
    DKK: "DK"
  };
  if (!c && curr && byCurrency[curr]) return byCurrency[curr];
  return "";
}

function countryLabel({ t, country, currency }) {
  const key = countryKey(country, currency);
  if (key) return t(`country.${key}`);
  return (country || "").toString().trim();
}

function localIsoDate(d = new Date()) {
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

function localMidnightFromIso(isoDate) {
  // isoDate: YYYY-MM-DD
  const [y, m, d] = (isoDate || "").split("-").map((x) => Number(x));
  if (!y || !m || !d) return null;
  return new Date(y, m - 1, d, 0, 0, 0, 0);
}

function nextAvailableDateIso(events, afterIso) {
  const dates = [...new Set((events || []).map((e) => e?.date).filter(Boolean))].sort();
  return dates.find((x) => x > afterIso) || "";
}

function compactMetricValue(value) {
  const text = (value || "").toString().trim();
  if (!text) return "";
  const cleaned = text
    .replace(/^(фактическое значение|прогноз|предыдущее значение)\s*/i, "")
    .trim();
  const numberMatch = cleaned.match(/[+\-]?\d+(?:[.,]\d+)?(?:\s?%)?/);
  return (numberMatch ? numberMatch[0] : cleaned).trim();
}

function eventDescriptionText(t, event) {
  const explicit = (event?.description || "").toString().trim();
  if (explicit) return explicit;
  return t("modal.descriptionFallback");
}

function EventDescriptionModal({ event, onClose }) {
  const { t, lang } = useI18n();
  const [resolvedDescription, setResolvedDescription] = useState(eventDescriptionText(t, event));

  useEffect(() => {
    let active = true;
    const fallback = eventDescriptionText(t, event);
    setResolvedDescription(fallback);
    if (!event?.id) return () => {};

    fetchEventDescription(event.id, lang)
      .then((payload) => {
        if (!active) return;
        const text = (payload?.description || "").toString().trim();
        setResolvedDescription(text || fallback);
      })
      .catch(() => {
        if (!active) return;
        setResolvedDescription(fallback);
      });

    return () => {
      active = false;
    };
  }, [event, lang, t]);

  if (!event) return null;

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" onClick={onClose}>
      <div className="modal-card" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h3>{t("modal.title")}</h3>
          <button type="button" className="modal-close" onClick={onClose} aria-label={t("modal.close")}>
            ×
          </button>
        </div>
        <p className="modal-title">
          {countryLabel({ t, country: event.country, currency: event.currency })} — {event.title}
        </p>
        <p className="modal-body">{resolvedDescription}</p>
      </div>
    </div>
  );
}

function EventsPage() {
  const { t } = useI18n();
  const [events, setEvents] = useState([]);
  const [selectedEvent, setSelectedEvent] = useState(null);
  const [filters, setFilters] = useState({
    country: "",
    datePreset: "all",
    dateExact: "",
    importance: ""
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const countries = useMemo(
    () =>
      [...new Set(events.map((e) => countryKey(e.country, e.currency)).filter(Boolean))]
        .map((key) => ({ key, label: t(`country.${key}`) }))
        .sort((a, b) => a.label.localeCompare(b.label)),
    [events, t]
  );
  useEffect(() => {
    let isActive = true;
    const load = async (refreshFirst = false) => {
      setLoading(true);
      setError("");
      try {
        if (refreshFirst) {
          try {
            await refreshEvents();
          } catch {
            // ignore, show last known DB data
          }
        }
        let data = await fetchEvents({}, { autoRefresh: false });
        if (!data.length) {
          try {
            await refreshEvents();
            data = await fetchEvents({}, { autoRefresh: false });
          } catch {
            // keep empty
          }
        }
        if (isActive) setEvents(data);
      } catch (e) {
        if (isActive) setError(e.message);
      } finally {
        if (isActive) setLoading(false);
      }
    };
    load(false);
    const id = setInterval(() => load(true), 60000);
    return () => {
      isActive = false;
      clearInterval(id);
    };
  }, []);

  const filtered = useMemo(
    () =>
      events.filter((e) => {
        if (filters.country && countryKey(e.country, e.currency) !== filters.country) return false;
        const today = new Date();
        const todayIso = localIsoDate(today);
        const tomorrow = new Date(today);
        tomorrow.setDate(today.getDate() + 1);
        const tomorrowIso = localIsoDate(tomorrow);
        const tomorrowTargetIso =
          filters.datePreset === "tomorrow"
            ? events.some((x) => x.date === tomorrowIso)
              ? tomorrowIso
              : nextAvailableDateIso(events, todayIso)
            : tomorrowIso;
        if (filters.datePreset === "today" && e.date !== todayIso) return false;
        if (filters.datePreset === "tomorrow" && e.date !== tomorrowTargetIso) return false;
        if (filters.datePreset === "week") {
          const d = localMidnightFromIso(e.date);
          const t0 = new Date(today.getFullYear(), today.getMonth(), today.getDate(), 0, 0, 0, 0);
          if (!d) return false;
          const deltaDays = Math.floor((d.getTime() - t0.getTime()) / 86400000);
          if (deltaDays < 0 || deltaDays > 6) return false;
        }
        if (filters.datePreset === "exact" && filters.dateExact && e.date !== filters.dateExact) return false;
        if (filters.importance && e.importance !== filters.importance) return false;
        return true;
      }),
    [events, filters]
  );

  return (
    <div className="page">
      <header className="page-head">
        <h1>{t("events.title")}</h1>
      </header>

      <form className="filters-card">
        <div className="filters-grid">
          <label className="field">
            <span>{t("events.country")}</span>
            <select
              value={filters.country}
              onChange={(e) => setFilters((p) => ({ ...p, country: e.target.value }))}
            >
              <option value="">{t("events.all")}</option>
              {countries.map((x) => (
                <option key={x.key} value={x.key}>
                  {x.label}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>{t("events.filterDate")}</span>
            <div className="date-presets">
              <button
                type="button"
                className={`chip ${filters.datePreset === "all" ? "chip-active" : ""}`}
                onClick={() => setFilters((p) => ({ ...p, datePreset: "all" }))}
              >
                {t("events.date.all")}
              </button>
              <button
                type="button"
                className={`chip ${filters.datePreset === "today" ? "chip-active" : ""}`}
                onClick={() => setFilters((p) => ({ ...p, datePreset: "today" }))}
              >
                {t("events.date.today")}
              </button>
              <button
                type="button"
                className={`chip ${filters.datePreset === "tomorrow" ? "chip-active" : ""}`}
                onClick={() => setFilters((p) => ({ ...p, datePreset: "tomorrow" }))}
              >
                {t("events.date.tomorrow")}
              </button>
              <button
                type="button"
                className={`chip ${filters.datePreset === "week" ? "chip-active" : ""}`}
                onClick={() => setFilters((p) => ({ ...p, datePreset: "week" }))}
              >
                {t("events.date.week")}
              </button>
              <button
                type="button"
                className={`chip ${filters.datePreset === "exact" ? "chip-active" : ""}`}
                onClick={() => setFilters((p) => ({ ...p, datePreset: "exact" }))}
              >
                {t("events.date.exact")}
              </button>
            </div>
            {filters.datePreset === "exact" && (
              <input
                type="date"
                value={filters.dateExact}
                onChange={(e) => setFilters((p) => ({ ...p, dateExact: e.target.value }))}
              />
            )}
          </label>
          <label className="field">
            <span>{t("events.importance")}</span>
            <select
              value={filters.importance}
              onChange={(e) => setFilters((p) => ({ ...p, importance: e.target.value }))}
            >
              <option value="">{t("events.all")}</option>
              <option value="low">{t("events.imp.low")}</option>
              <option value="medium">{t("events.imp.medium")}</option>
              <option value="high">{t("events.imp.high")}</option>
            </select>
          </label>
        </div>
        <div className="filters-actions">
          <button
            type="button"
            className="btn btn-ghost"
            onClick={() =>
              setFilters({ country: "", datePreset: "all", dateExact: "", importance: "" })
            }
          >
            {t("events.reset")}
          </button>
        </div>
      </form>

      {loading && <p className="muted">{t("events.loading")}</p>}
      {error && <p className="error">{error}</p>}

      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>{t("events.col.date")}</th>
              <th>{t("events.col.time")}</th>
              <th>{t("events.col.remaining")}</th>
              <th>{t("events.col.currency")}</th>
              <th>{t("events.col.country")}</th>
              <th>{t("events.col.importance")}</th>
              <th>{t("events.col.title")}</th>
              <th>{t("events.col.actual")}</th>
              <th>{t("events.col.forecast")}</th>
              <th>{t("events.col.previous")}</th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 && !loading ? (
              <tr>
                <td colSpan={10} className="muted center">
                  {t("events.empty")}
                </td>
              </tr>
            ) : (
              filtered.map((e) => (
                <tr key={e.id} className="event-row" onClick={() => setSelectedEvent(e)}>
                  <td className="mono">{e.date}</td>
                  <td className="mono">{e.event_time || t("events.dash")}</td>
                  <td className="mono">{e.remaining_time || t("events.dash")}</td>
                  <td className="mono">{e.currency || t("events.dash")}</td>
                  <td>
                    <span className="country-cell">
                      <span>{countryLabel({ t, country: e.country, currency: e.currency })}</span>
                    </span>
                  </td>
                  <td>
                    <span className={importanceClass(e.importance)}>{t(`importance.${e.importance}`)}</span>
                  </td>
                  <td>{e.title}</td>
                  <td className="mono">{compactMetricValue(e.actual) || t("events.dash")}</td>
                  <td className="mono">{compactMetricValue(e.forecast) || t("events.dash")}</td>
                  <td className="mono">{compactMetricValue(e.previous) || t("events.dash")}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
      <EventDescriptionModal event={selectedEvent} onClose={() => setSelectedEvent(null)} />
    </div>
  );
}

function formatNewsTimestamp(iso) {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return String(iso);
  }
}

function NewsPage() {
  const { t } = useI18n();
  const [articles, setArticles] = useState([]);
  const [sourceOptions, setSourceOptions] = useState([]);
  const [source, setSource] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const [readingArticle, setReadingArticle] = useState(null);
  const [unlockIn, setUnlockIn] = useState(0);
  const [readerContent, setReaderContent] = useState("");
  const [readerSummary, setReaderSummary] = useState("");
  const [readerLoading, setReaderLoading] = useState(false);
  const [readerError, setReaderError] = useState("");

  async function populateSourceCatalog() {
    const h = await fetchBackendHealth();
    if (!h?.features?.news) {
      setSourceOptions([]);
      return;
    }
    try {
      const data = await fetchNews({}, { autoRefresh: false, limit: 220 });
      const map = new Map();
      for (const a of data || []) {
        if (a.source_key) map.set(a.source_key, a.source_label || a.source_key);
      }
      setSourceOptions([...map.entries()].sort((a, b) => a[1].localeCompare(b[1])));
    } catch {
      setSourceOptions([]);
    }
  }

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const h = await fetchBackendHealth();
        if (cancelled) return;
        if (!h?.features?.news) {
          setSourceOptions([]);
          return;
        }
        const data = await fetchNews({}, { autoRefresh: false, limit: 220 });
        if (cancelled) return;
        const map = new Map();
        for (const a of data || []) {
          if (a.source_key) map.set(a.source_key, a.source_label || a.source_key);
        }
        setSourceOptions([...map.entries()].sort((a, b) => a[1].localeCompare(b[1])));
      } catch {
        if (!cancelled) setSourceOptions([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let active = true;
    const load = async (opts = {}) => {
      setLoading(true);
      setError("");
      try {
        const h = await fetchBackendHealth();
        if (!active) return;
        if (!h) {
          setArticles([]);
          setError(t("news.healthFailed"));
          return;
        }
        if (h.features?.news !== true) {
          setArticles([]);
          setError(t("news.backendOutdated"));
          return;
        }
        const data = await fetchNews(
          { source: source || undefined },
          { autoRefresh: false, limit: 150 }
        );
        if (active) setArticles(Array.isArray(data) ? data : []);
      } catch (e) {
        if (active) setError(e.message || String(e));
      } finally {
        if (active) setLoading(false);
      }
    };
    load({ autoRefresh: false });
    const id = setInterval(() => load({ autoRefresh: false }), 120000);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, [source, t]);

  const onRefreshNow = async () => {
    setRefreshing(true);
    setError("");
    try {
      const h = await fetchBackendHealth();
      if (!h) {
        setError(t("news.healthFailed"));
        return;
      }
      if (h.features?.news !== true) {
        setError(t("news.backendOutdated"));
        return;
      }
      await refreshNews();
      await populateSourceCatalog();
      const list = await fetchNews(
        { source: source || undefined },
        { autoRefresh: false, limit: 150 }
      );
      setArticles(Array.isArray(list) ? list : []);
    } catch (e) {
      setError(e.message || String(e));
    } finally {
      setRefreshing(false);
    }
  };

  const showStaleHint =
    typeof error === "string" &&
    (error.includes("Not Found") || /not\s*found/i.test(error) || error === t("news.backendOutdated"));

  useEffect(() => {
    if (!readingArticle || unlockIn <= 0) return undefined;
    const id = setInterval(() => {
      setUnlockIn((prev) => (prev > 0 ? prev - 1 : 0));
    }, 1000);
    return () => clearInterval(id);
  }, [readingArticle, unlockIn]);

  const openReader = (article) => {
    setReadingArticle(article);
    setUnlockIn(6);
    setReaderContent("");
    setReaderSummary("");
    setReaderError("");
    setReaderLoading(true);
    fetchNewsContent(article.id)
      .then((payload) => {
        setReaderContent((payload?.content || "").toString().trim());
        setReaderSummary((payload?.summary || "").toString().trim());
      })
      .catch((e) => {
        setReaderError(e.message || String(e));
      })
      .finally(() => setReaderLoading(false));
  };

  const closeReader = () => {
    setReadingArticle(null);
    setUnlockIn(0);
  };

  return (
    <div className="page">
      <header className="page-head">
        <h1>{t("news.title")}</h1>
        <p className="lede">{t("news.lede")}</p>
      </header>

      <div className="filters-card news-toolbar">
        <div className="filters-grid news-toolbar-grid">
          <label className="field">
            <span>{t("news.source")}</span>
            <select value={source} onChange={(e) => setSource(e.target.value)}>
              <option value="">{t("news.allSources")}</option>
              {sourceOptions.map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <div className="field news-toolbar-actions">
            <span className="field-spacer" />
            <button
              type="button"
              className="btn"
              disabled={refreshing}
              onClick={onRefreshNow}
            >
              {refreshing ? t("news.refreshing") : t("news.refresh")}
            </button>
          </div>
        </div>
      </div>

      {loading && !articles.length && <p className="muted">{t("news.loading")}</p>}
      {error && (
        <div className="error news-error">
          <p className="news-error-text">{error}</p>
          {error === t("news.backendOutdated") ? (
            <p className="muted news-error-hint">{t("news.restartBackend")}</p>
          ) : null}
          {showStaleHint && error !== t("news.backendOutdated") ? (
            <p className="muted news-error-hint">{t("news.hintNotFound")}</p>
          ) : null}
        </div>
      )}

      <div className="news-grid">
        {!loading && !articles.length && !error ? (
          <p className="muted">{t("news.empty")}</p>
        ) : (
          articles.map((a) => (
            <article key={a.id} className="news-card">
              <div className="news-card-meta">
                <span className="pill news-source">{a.source_label || a.source_key}</span>
                <time className="mono muted news-time" dateTime={a.published_at || undefined}>
                  {formatNewsTimestamp(a.published_at) || t("news.noDate")}
                </time>
              </div>
              <h2 className="news-card-title">
                <button type="button" className="news-title-btn" onClick={() => openReader(a)}>
                  {a.title}
                </button>
              </h2>
              {a.summary ? <p className="news-card-summary muted">{a.summary}</p> : null}
              <div className="news-card-foot">
                <button type="button" className="news-read-btn" onClick={() => openReader(a)}>
                  {t("news.openReader")}
                </button>
              </div>
            </article>
          ))
        )}
      </div>
      {readingArticle ? (
        <div className="modal-backdrop news-reader-backdrop" role="dialog" aria-modal="true" onClick={closeReader}>
          <div className="modal-card news-reader-modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-head">
              <h3>{t("news.readerTitle")}</h3>
              <button type="button" className="modal-close" onClick={closeReader} aria-label={t("modal.close")}>
                ×
              </button>
            </div>
            <p className="modal-title">{readingArticle.title}</p>
            <p className="muted news-reader-source">{readingArticle.source_label || readingArticle.source_key}</p>
            {readerLoading ? <p className="modal-body">{t("news.readerLoading")}</p> : null}
            {readerError ? <p className="modal-body">{readerError}</p> : null}
            {!readerLoading && !readerError ? (
              <div className="modal-body news-reader-content">
                {readerSummary ? <p className="news-reader-summary">{readerSummary}</p> : null}
                {(readerContent || readingArticle.summary || t("news.readerFallback"))
                  .split(/\n{2,}/)
                  .filter(Boolean)
                  .map((p, i) => (
                    <p key={i}>{p}</p>
                  ))}
              </div>
            ) : null}
            <div className="news-reader-actions">
              <span className="muted">
                {unlockIn > 0 ? t("news.readerWait", { seconds: String(unlockIn) }) : t("news.readerReady")}
              </span>
              <a
                className={`news-read ${unlockIn > 0 ? "news-read-disabled" : ""}`}
                href={unlockIn > 0 ? undefined : readingArticle.link}
                target="_blank"
                rel="noopener noreferrer"
                aria-disabled={unlockIn > 0}
                onClick={(e) => {
                  if (unlockIn > 0) e.preventDefault();
                }}
              >
                {t("news.readOriginal")}
              </a>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function Layout() {
  const { t, lang, setLang, locales, localeLabels } = useI18n();
  const [themeSource, setThemeSource] = useState(() => {
    if (typeof localStorage === "undefined") return "system";
    return localStorage.getItem("themeSource") || "system";
  });
  const [theme, setTheme] = useState(() => {
    if (typeof localStorage !== "undefined") {
      const saved = localStorage.getItem("theme");
      if (saved === "light" || saved === "dark") return saved;
    }
    if (typeof window !== "undefined" && window.matchMedia?.("(prefers-color-scheme: dark)").matches) {
      return "dark";
    }
    return "light";
  });

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    if (typeof localStorage !== "undefined") {
      localStorage.setItem("theme", theme);
      localStorage.setItem("themeSource", themeSource);
    }
  }, [theme, themeSource]);

  useEffect(() => {
    if (themeSource !== "system" || typeof window === "undefined" || !window.matchMedia) return undefined;
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const apply = () => setTheme(media.matches ? "dark" : "light");
    apply();
    const onChange = () => apply();
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, [themeSource]);

  return (
    <div className="app-shell">
      <header className="top-nav">
        <div className="brand">
          <span className="brand-mark" />
          <span className="brand-text">{t("brand.title")}</span>
        </div>
        <div className="top-nav-right">
          <nav className="nav-links">
            <NavLink end className="nav-link" to="/">
              {t("nav.events")}
            </NavLink>
            <NavLink className="nav-link" to="/news">
              {t("nav.news")}
            </NavLink>
          </nav>
          <label className="lang-select">
            <span>{t("lang.label")}</span>
            <select value={lang} onChange={(e) => setLang(e.target.value)} aria-label={t("lang.label")}>
              {locales.map((code) => (
                <option key={code} value={code}>
                  {localeLabels[code]}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            className="theme-toggle"
            onClick={() => {
              setThemeSource("manual");
              setTheme((prev) => (prev === "dark" ? "light" : "dark"));
            }}
          >
            {theme === "dark" ? t("theme.light") : t("theme.dark")}
          </button>
        </div>
      </header>
      <main className="main">
        <Routes>
          <Route path="/" element={<EventsPage />} />
          <Route path="/news" element={<NewsPage />} />
          <Route path="/calendar" element={<Navigate to="/news" replace />} />
        </Routes>
      </main>
      <footer className="footer muted">
        <Link to="/">{t("footer.home")}</Link>
      </footer>
    </div>
  );
}

export default function App() {
  const Router =
    typeof window !== "undefined" && window.location.hostname.endsWith("github.io") ? HashRouter : BrowserRouter;
  return (
    <Router>
      <Layout />
    </Router>
  );
}
