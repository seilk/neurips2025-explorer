"use client";

import { Fragment, FormEvent, useEffect, useMemo, useState } from "react";
import { Icon } from "@iconify/react";
import type { ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import { visit, SKIP } from "unist-util-visit";
import type { PluggableList, Plugin } from "unified";
import type { Root, Element, Text } from "hast";
import type { Parent } from "unist";
import styles from "./page.module.css";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

interface SchemaField {
  name: string;
  type: string;
}

interface SchemaResponse {
  fields: SchemaField[];
  facets: Record<string, string[]>;
}

interface SearchPayload {
  query?: string;
  filters?: Record<string, string[]>;
  page: number;
  page_size: number;
  sort_by?: string;
  sort_order?: string;
  seed?: string;
}

interface SearchResponse {
  total: number;
  page: number;
  page_size: number;
  results: PaperRecord[];
}

export type PaperRecord = Record<string, unknown> & { id: number };

type FilterMap = { [field: string]: string[] };

type PaperCardProps = {
  paper: PaperRecord;
  tokens: string[];
};

const QUICK_FILTER_FIELDS = ["decision", "topic"];
const PAGE_SIZE = 20;
type SortMode = "random" | "az";

type FilterSectionProps = {
  field: string;
  label: string;
  options: string[];
  selected: string[];
  onToggle: (value: string) => void;
};

const friendlyFieldName = (name: string) =>
  name
    .replace(/_/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());

const escapeRegExp = (value: string) => value.replace(/[-/\\^$*+?.()|[\]{}]/g, "\\$&");

const decodeHtmlEntities = (value: string): string =>
  value
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'");

const formatValue = (value: unknown): string => {
  if (value === null || value === undefined) {
    return "-";
  }
  if (Array.isArray(value)) {
    if (value.length === 0) {
      return "-";
    }
    return value
      .map((item) => (typeof item === "string" ? item : JSON.stringify(item)))
      .join(", ");
  }
  if (typeof value === "object") {
    return JSON.stringify(value, null, 2);
  }
  return String(value);
};

function shuffleResults<T>(items: T[]): T[] {
  const arr = [...items];
  for (let i = arr.length - 1; i > 0; i -= 1) {
    const j = Math.floor(Math.random() * (i + 1));
    [arr[i], arr[j]] = [arr[j], arr[i]];
  }
  return arr;
}

function MarkdownBlock({ text, tokens }: { text: string; tokens: string[] }) {
  const normalised = useMemo(() => text.replace(/\r\n/g, "\n").trim(), [text]);
  const highlightPlugin = useMemo(() => createHighlightRehype(tokens, styles.highlight), [tokens]);
  const rehypePlugins = useMemo<PluggableList>(() => {
    const plugins: PluggableList = [rehypeKatex];
    if (highlightPlugin) {
      plugins.push(highlightPlugin);
    }
    return plugins;
  }, [highlightPlugin]);
  if (!normalised) {
    return null;
  }
  return (
    <div className={styles.markdown}>
      <ReactMarkdown remarkPlugins={[remarkMath]} rehypePlugins={rehypePlugins}>
        {normalised}
      </ReactMarkdown>
    </div>
  );
}

function MarkdownInline({ text, tokens }: { text: string; tokens: string[] }) {
  const normalised = useMemo(() => text.trim(), [text]);
  const highlightPlugin = useMemo(() => createHighlightRehype(tokens, styles.highlight), [tokens]);
  const rehypePlugins = useMemo<PluggableList>(() => {
    const plugins: PluggableList = [rehypeKatex];
    if (highlightPlugin) {
      plugins.push(highlightPlugin);
    }
    return plugins;
  }, [highlightPlugin]);
  if (!normalised) {
    return null;
  }
  return (
    <ReactMarkdown
      remarkPlugins={[remarkMath]}
      rehypePlugins={rehypePlugins}
      components={{
        p: ({ children }) => <>{children}</>,
      }}
    >
      {normalised}
    </ReactMarkdown>
  );
}

function formatAuthorsList(authorsValue: unknown): string {
  if (Array.isArray(authorsValue)) {
    const names = (authorsValue as unknown[])
      .map((entry) => {
        if (typeof entry === "string") {
          return entry;
        }
        if (entry && typeof entry === "object") {
          const candidate = entry as Record<string, unknown>;
          if (typeof candidate.fullname === "string") {
            return candidate.fullname;
          }
          if (typeof candidate.name === "string") {
            return candidate.name;
          }
          if (typeof candidate.display_name === "string") {
            return candidate.display_name;
          }
        }
        return null;
      })
      .filter((value): value is string => Boolean(value && value.trim().length > 0));
    if (names.length > 0) {
      return names.join(", ");
    }
  }
  return formatValue(authorsValue);
}

function formatInstitutionsList(authorsValue: unknown): string {
  if (Array.isArray(authorsValue)) {
    const institutions = (authorsValue as unknown[])
      .map((entry) => {
        if (entry && typeof entry === "object") {
          const candidate = entry as Record<string, unknown>;
          if (typeof candidate.institution === "string") {
            return decodeHtmlEntities(candidate.institution);
          }
          if (Array.isArray(candidate.institution)) {
            return (candidate.institution as unknown[])
              .map((item) => (typeof item === "string" ? decodeHtmlEntities(item) : null))
              .filter((value): value is string => Boolean(value && value.trim().length > 0))
              .join(", ");
          }
        }
        return null;
      })
      .filter((value): value is string => Boolean(value && value.trim().length > 0));
    if (institutions.length > 0) {
      const unique = Array.from(new Set(institutions.map((name) => name.trim()).filter(Boolean)));
      return unique.join(", ");
    }
  }
  return "";
}

function createHighlightRehype(tokens: string[], className: string): Plugin | null {
  const candidates = tokens.filter((token) => token.trim().length > 0);
  if (candidates.length === 0) {
    return null;
  }
  const pattern = new RegExp(`(${candidates.map(escapeRegExp).join("|")})`, "gi");

  const plugin = (() => (tree: Root) => {
    visit(tree, "text", (node: Text, index: number | undefined, parent: Parent | undefined) => {
      if (!parent || typeof node.value !== "string" || typeof index !== "number") {
        return;
      }
      const parentNode = parent as Parent & Partial<Element>;
      if (parentNode.type === "element" && parentNode.properties) {
        const classProp = parentNode.properties?.className;
        const classList = Array.isArray(classProp)
          ? classProp
          : typeof classProp === "string"
          ? classProp.split(/\s+/)
          : [];
        if (classList.some((cls) => typeof cls === "string" && cls.includes("katex"))) {
          return;
        }
      }

      if (parentNode.type === "element" && parentNode.tagName === "script") {
        return;
      }

      const parts = node.value.split(pattern);
      if (parts.length <= 1) {
        return;
      }

      const newNodes = parts
        .map((part, idx) => {
          if (!part) {
            return null;
          }
          if (idx % 2 === 1) {
            return {
              type: "element",
              tagName: "span",
              properties: { className: [className] },
              children: [{ type: "text", value: part }],
            };
          }
          return { type: "text", value: part };
        })
        .filter(Boolean);

      if (!newNodes.length) {
        return;
      }

      parentNode.children?.splice(index, 1, ...(newNodes as Parent["children"]));
      return SKIP;
    });
  }) as unknown as Plugin;

  return plugin;
}

function renderHighlightedText(text: string, tokens: string[]): ReactNode {
  if (!text) {
    return text;
  }
  const candidates = tokens.filter((token) => token.trim().length > 0);
  if (candidates.length === 0) {
    return text;
  }
  const regex = new RegExp(`(${candidates.map(escapeRegExp).join("|")})`, "gi");
  const parts = text.split(regex);
  if (parts.length <= 1) {
    return text;
  }
  return parts.map((part, idx) => {
    if (!part) {
      return null;
    }
    if (idx % 2 === 1) {
      return (
        <span key={idx} className={styles.highlight}>
          {part}
        </span>
      );
    }
    return <Fragment key={idx}>{part}</Fragment>;
  });
}

function renderValueWithHighlight(value: unknown, tokens: string[]): ReactNode {
  if (value === null || value === undefined) {
    return "-";
  }
  if (Array.isArray(value)) {
    const joined = value
      .map((item) => (typeof item === "string" ? item : JSON.stringify(item)))
      .filter((item) => item && item.length > 0)
      .join(", ");
    if (!joined) {
      return "-";
    }
    return renderHighlightedText(joined, tokens);
  }
  if (typeof value === "object") {
    return JSON.stringify(value, null, 2);
  }
  return renderHighlightedText(String(value), tokens);
}

function FilterSection({ field, label, options, selected, onToggle }: FilterSectionProps) {
  const [term, setTerm] = useState("");

  const filtered = useMemo(() => {
    if (!term) {
      return options;
    }
    const lowered = term.toLowerCase();
    return options.filter((option) => option.toLowerCase().includes(lowered));
  }, [options, term]);

  return (
    <div className={styles.filterGroup}>
      <div className={styles.filterGroupHeader}>
        <p className={styles.sectionTitle}>{label}</p>
        {options.length > 6 && (
          <input
            className={styles.filterSearch}
            placeholder={`Search ${label}`}
            value={term}
            onChange={(event) => setTerm(event.target.value)}
          />
        )}
      </div>
      <div className={styles.checkboxList}>
        {filtered.length === 0 ? (
          <span className={styles.summaryText}>No matching options.</span>
        ) : (
          filtered.map((option) => {
            const checked = selected.includes(option);
            return (
              <label key={`${field}-${option}`} className={styles.checkboxItem}>
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={() => onToggle(option)}
                />
                <span>{option}</span>
              </label>
            );
          })
        )}
      </div>
    </div>
  );
}

function PaperCard({ paper, tokens }: PaperCardProps) {
  const titleRaw = paper["name"];
  const abstractRaw = paper["abstract"];
  const authorsRaw = paper["authors"];
  const keywordsRaw = paper["keywords"];
  const eventTypeRaw = paper["event_type"] ?? paper["eventtype"];

  const title = typeof titleRaw === "string" ? titleRaw : "Title unavailable";
  const abstractText = abstractRaw ? String(abstractRaw) : "";
  const authors = formatAuthorsList(authorsRaw);
  const institutions = formatInstitutionsList(authorsRaw);
  const topicValue = paper["topic"];
  const topicText = Array.isArray(topicValue)
    ? (topicValue as unknown[])
        .map((value) => (value == null ? "" : String(value)))
        .filter((value) => value.trim().length > 0)
        .join(", ")
    : topicValue
    ? String(topicValue)
    : "";

  let firstAuthorInitial = "";
  let firstAuthorLast = "";
  if (Array.isArray(authorsRaw) && authorsRaw.length > 0) {
    const firstAuthorEntry = authorsRaw[0];
    let fullName = "";
    if (typeof firstAuthorEntry === "string") {
      fullName = firstAuthorEntry;
    } else if (firstAuthorEntry && typeof firstAuthorEntry === "object") {
      const candidate = firstAuthorEntry as Record<string, unknown>;
      if (typeof candidate.fullname === "string") {
        fullName = candidate.fullname;
      } else if (typeof candidate.name === "string") {
        fullName = candidate.name;
      } else if (typeof candidate.display_name === "string") {
        fullName = candidate.display_name;
      }
    }
    const parts = fullName
      .split(/\s+/)
      .map((segment) => segment.trim())
      .filter((segment) => segment.length > 0);
    if (parts.length >= 2) {
      firstAuthorInitial = parts[0][0]?.toUpperCase() ?? "";
      firstAuthorLast = parts[parts.length - 1];
    } else if (parts.length === 1) {
      firstAuthorLast = parts[0];
    }
  }
  const keywords = Array.isArray(keywordsRaw)
    ? (keywordsRaw as unknown[]).map((value) => String(value))
    : [];
  const metadata = [
    { label: "Decision", value: paper["decision"] },
    { label: "Event Type", value: eventTypeRaw },
    { label: "Session", value: paper["session"] },
    { label: "Poster Position", value: paper["poster_position"] },
  ].filter((item) => item.value !== undefined && item.value !== null && item.value !== "");

  const encodedTitle = title ? encodeURIComponent(title) : "";
  const fallbackArxiv = encodedTitle
    ? `https://www.google.com/search?q=${encodedTitle}`
    : undefined;
  const [arxivPending, setArxivPending] = useState(false);

  const handleArxivClick = async () => {
    if (!title) {
      if (fallbackArxiv) {
        window.open(fallbackArxiv, "_blank", "noopener,noreferrer");
      }
      return;
    }
    const fallback = fallbackArxiv ?? `https://www.google.com/search?q=${encodeURIComponent(title)}`;
    try {
      setArxivPending(true);
      const searchParams = new URLSearchParams({ title });
      if (firstAuthorInitial && firstAuthorLast) {
        searchParams.append("author_initial", firstAuthorInitial);
        searchParams.append("author_last", firstAuthorLast);
      }
      const response = await fetch(`${API_BASE_URL}/arxiv?${searchParams.toString()}`);
      if (!response.ok) {
        throw new Error(`ArXiv lookup failed: ${response.status}`);
      }
      const data: { url?: string } = await response.json();
      const target = typeof data.url === "string" && data.url.trim().length > 0 ? data.url : fallback;
      window.open(target, "_blank", "noopener,noreferrer");
    } catch {
      window.open(fallback, "_blank", "noopener,noreferrer");
    } finally {
      setArxivPending(false);
    }
  };

  return (
    <article className={styles.card}>
      <header>
        <h3 className={styles.cardTitle}>
          <MarkdownInline text={title} tokens={tokens} />
        </h3>
        <p className={styles.cardMeta}>
          <span className={styles.metaItem}>
            <span>Authors:</span> {renderHighlightedText(authors || "Unknown", tokens)}
          </span>
          {institutions && (
            <span className={styles.metaItem}>
              <span>Institutions:</span> {renderHighlightedText(institutions, tokens)}
            </span>
          )}
          {topicText && (
            <span className={styles.metaItem}>
              <span>Topic:</span> {renderHighlightedText(topicText, tokens)}
            </span>
          )}
        </p>
      </header>
      {abstractText && (
        <details className={styles.abstractToggle}>
          <summary>Show abstract</summary>
          <div className={styles.abstractContent}>
            <MarkdownBlock text={abstractText} tokens={tokens} />
          </div>
        </details>
      )}
      <div className={styles.cardMeta}>
        {topicText && (
          <span className={styles.metaItem}>
            <span>Topic:</span> {renderHighlightedText(topicText, tokens)}
          </span>
        )}
        {metadata.map((item) => (
          <span key={item.label} className={styles.metaItem}>
            <span>{item.label}:</span> {renderValueWithHighlight(item.value, tokens)}
          </span>
        ))}
      </div>
      {keywords.length > 0 && (
        <div className={styles.tags}>
          {keywords.map((keyword) => (
            <span key={keyword} className={styles.tag}>
              {renderHighlightedText(keyword, tokens)}
            </span>
          ))}
        </div>
      )}
      <div className={styles.links}>
        <button
          type="button"
          className={styles.linkButton}
          onClick={handleArxivClick}
          disabled={arxivPending}
        >
          <Icon icon="mdi:book-open-variant" fontSize={18} />
          {arxivPending ? "Opening..." : "Go to arXiv"}
        </button>
      </div>
    </article>
  );
}

export default function Home() {
  const [schema, setSchema] = useState<SchemaResponse | null>(null);
  const [schemaError, setSchemaError] = useState<string | null>(null);
  const [searchTerm, setSearchTerm] = useState("");
  const [query, setQuery] = useState("");
  const [filters, setFilters] = useState<FilterMap>({});
  const [results, setResults] = useState<PaperRecord[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [sortMode, setSortMode] = useState<SortMode>("random");
  const [randomSeed, setRandomSeed] = useState<string>(() => `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`);
  const [quickFiltersOpen, setQuickFiltersOpen] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const highlightTokens = useMemo(() => {
    if (!query) {
      return [] as string[];
    }
    const rawTokens = query
      .split(/\s+/)
      .map((token) => token.trim().toLowerCase())
      .filter((token) => token.length > 0);
    return Array.from(new Set(rawTokens));
  }, [query]);

  useEffect(() => {
    const loadSchema = async () => {
      try {
        const response = await fetch(`${API_BASE_URL}/papers/schema`);
        if (!response.ok) {
          throw new Error(`Failed to load schema. (HTTP ${response.status})`);
        }
        const payload: SchemaResponse = await response.json();
        setSchema(payload);
      } catch (err) {
        const message = err instanceof Error ? err.message : "An unexpected issue occurred while loading the schema.";
        setSchemaError(message);
      }
    };
    loadSchema();
  }, []);

  useEffect(() => {
    const timer = setTimeout(() => {
      setQuery(searchTerm.trim());
      setPage(1);
    }, 300);
    return () => clearTimeout(timer);
  }, [searchTerm]);

  useEffect(() => {
    const controller = new AbortController();
    const runSearch = async () => {
      setLoading(true);
      setError(null);
      try {
        const payload: SearchPayload = {
          page,
          page_size: PAGE_SIZE,
        };
        if (sortMode === "random") {
          payload.sort_by = "random";
          payload.seed = randomSeed;
        } else if (sortMode === "az") {
          payload.sort_by = "name";
          payload.sort_order = "asc";
        }
        if (query) {
          payload.query = query;
        }
        if (Object.keys(filters).length > 0) {
          payload.filters = filters;
        }
        const response = await fetch(`${API_BASE_URL}/papers/search`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
          signal: controller.signal,
        });
        if (!response.ok) {
          throw new Error(`Search request failed. (HTTP ${response.status})`);
        }
        const data: SearchResponse = await response.json();
        const totalPages = Math.max(1, Math.ceil(data.total / PAGE_SIZE));
        if (page > totalPages && data.total > 0) {
          setPage(totalPages);
          return;
        }
        setResults(data.results);
        setTotal(data.total);
      } catch (err) {
        if ((err as Error).name === "AbortError") {
          return;
        }
        const message = err instanceof Error ? err.message : "Something went wrong during the search.";
        setError(message);
        setResults([]);
        setTotal(0);
      } finally {
        setLoading(false);
      }
    };

    runSearch();
    return () => controller.abort();
  }, [query, filters, page, sortMode, randomSeed]);

  const quickFilters = useMemo(() => {
    if (!schema) {
      return [] as string[];
    }
    return QUICK_FILTER_FIELDS.filter((field) => field in schema.facets);
  }, [schema]);

  const activeFilters = useMemo(() => {
    return Object.entries(filters).flatMap(([field, values]) =>
      values.map((value) => ({ field, value }))
    );
  }, [filters]);

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    setQuery(searchTerm.trim());
    setPage(1);
  };

  const toggleFilter = (field: string, value: string) => {
    const trimmed = value.trim();
    if (!trimmed) {
      return;
    }
    setFilters((previous) => {
      const currentValues = previous[field] ?? [];
      if (currentValues.includes(trimmed)) {
        const nextValues = currentValues.filter((item) => item !== trimmed);
        if (nextValues.length === 0) {
          const rest = { ...previous };
          delete rest[field];
          return rest;
        }
        return { ...previous, [field]: nextValues };
      }
      return { ...previous, [field]: [...currentValues, trimmed] };
    });
    setPage(1);
  };

  const removeFilter = (field: string, value?: string) => {
    setFilters((previous) => {
      const updated = { ...previous };
      if (value === undefined) {
        delete updated[field];
        return updated;
      }
      const currentValues = previous[field] ?? [];
      const nextValues = currentValues.filter((item) => item !== value);
      if (nextValues.length === 0) {
        delete updated[field];
        return updated;
      }
      return { ...updated, [field]: nextValues };
    });
    setPage(1);
  };

  const clearFilters = () => {
    setFilters({});
    setPage(1);
  };

  const handleSortModeChange = (mode: SortMode) => {
    setSortMode((prev) => {
      if (prev === mode) {
        return prev;
      }
      return mode;
    });
    setPage(1);
  };

  const handleShuffleClick = () => {
    if (sortMode !== "random") {
      setSortMode("random");
    }
    // Bump seed to reshuffle globally across pages
    setRandomSeed(`${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`);
    setPage(1);
  };

  const handleTitleClick = () => {
    if (typeof window !== "undefined") {
      window.location.href = window.location.pathname;
    }
  };

  const scrollToTop = () => {
    if (typeof window !== "undefined") {
      window.scrollTo({ top: 0, behavior: "smooth" });
    }
  };

  return (
    <div className={styles.page}>
      <div className={styles.container}>
        <header className={styles.header}>
          <button type="button" className={styles.titleButton} onClick={handleTitleClick}>
            NeurIPS 2025 Papers Explorer
          </button>
          <p className={styles.subtitle}>Browse 5,871 accepted papers.</p>
          <section className={styles.searchBar}>
            <form onSubmit={handleSubmit}>
              <input
                className={styles.searchInput}
                value={searchTerm}
                onChange={(event) => setSearchTerm(event.target.value)}
                placeholder="Search title, authors, abstract, keywords, or any keyword you like"
              />
              <button type="submit" className={styles.searchButton} aria-label="Search">
                <Icon icon="mdi:magnify" fontSize={22} />
              </button>
            </form>
            {schemaError && <div className={styles.error}>{schemaError}</div>}
          </section>
        </header>

        <section className={styles.mainContent}>
          <aside className={styles.sidebar}>
            <div className={styles.panel}>
              <button
                type="button"
                className={styles.panelToggle}
                onClick={() => setQuickFiltersOpen((prev) => !prev)}
              >
                <span>Quick filters</span>
                <Icon
                  icon={quickFiltersOpen ? "mdi:chevron-up" : "mdi:chevron-down"}
                  fontSize={20}
                  className={styles.panelToggleIcon}
                />
              </button>
              <div
                className={`${styles.panelContent} ${quickFiltersOpen ? styles.panelContentOpen : ""}`}
                aria-hidden={!quickFiltersOpen}
              >
                {quickFilters.length === 0 && (
                  <p className={styles.summaryText}>No recommended filters are available.</p>
                )}
                {quickFilters.map((field) => (
                  <FilterSection
                    key={field}
                    field={field}
                    label={friendlyFieldName(field)}
                    options={schema?.facets?.[field] ?? []}
                    selected={filters[field] ?? []}
                    onToggle={(value) => toggleFilter(field, value)}
                  />
                ))}
                <button className={styles.clearButton} onClick={clearFilters} type="button">
                  Clear all filters
                </button>
              </div>
              {activeFilters.length > 0 && (
                <div className={styles.activeFilters}>
                  {activeFilters.map((item) => (
                    <span key={`${item.field}-${item.value}`} className={styles.chip}>
                      {friendlyFieldName(item.field)}: {item.value}
                      <button type="button" onClick={() => removeFilter(item.field, item.value)}>
                        ×
                      </button>
                    </span>
                  ))}
                </div>
              )}
            </div>
          </aside>

          <section className={styles.results}>
            <div className={styles.summaryBar}>
              <div className={styles.summaryInfo}>
                <p className={styles.summaryText}>
                  Showing {total === 0 ? 0 : (page - 1) * PAGE_SIZE + 1}-{Math.min(page * PAGE_SIZE, total)} of {total.toLocaleString()} results.
                </p>
                <div className={styles.sortToggle}>
                  <span className={styles.sortLabel}>Sort:</span>
                  <button
                    type="button"
                    className={sortMode === "random" ? styles.sortButtonActive : styles.sortButton}
                    onClick={handleShuffleClick}
                  >
                    Shuffle
                  </button>
                  <button
                    type="button"
                    className={sortMode === "az" ? styles.sortButtonActive : styles.sortButton}
                    onClick={() => handleSortModeChange("az")}
                  >
                    A-Z
                  </button>
                </div>
              </div>
              <div className={`${styles.pagination} ${styles.summaryText}`}>
                <div className={styles.paginationControls}>
                  <button
                    type="button"
                    onClick={() => setPage((current) => Math.max(1, current - 1))}
                    disabled={page === 1 || loading}
                  >
                    Previous
                  </button>
                  <button
                    type="button"
                    onClick={() => setPage((current) => Math.min(totalPages, current + 1))}
                    disabled={page >= totalPages || loading}
                  >
                    Next
                  </button>
                </div>
                <span>
                  Page {page} of {totalPages}
                </span>
              </div>
            </div>

            {loading && <div className={styles.summaryText}>Searching…</div>}
            {error && <div className={styles.error}>{error}</div>}

            {!loading && !error && results.length === 0 && (
              <div className={styles.empty}>No papers match your filters. Try adjusting the search or filter set.</div>
            )}

            {results.map((paper) => (
              <PaperCard key={String(paper.id)} paper={paper} tokens={highlightTokens} />
            ))}
            {results.length > 0 && (
              <button
                type="button"
                onClick={scrollToTop}
                className={styles.floatingTopButton}
                aria-label="Go to top"
              >
                <Icon icon="mdi:arrow-up" fontSize={24} />
              </button>
            )}
          </section>
        </section>
      </div>
    </div>
  );
}
