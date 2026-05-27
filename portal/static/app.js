// Schwarz Git Ready Barcelona Hackathon data portal — preact + htm SPA, no build step.
// Three views: catalog (list+search), detail (one model), chat (Gemini loop).
// Routing is hash-based so the FastAPI SPA fallback only has to serve one
// HTML file regardless of which page the user lands on.

import { render } from "preact";
import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import { html } from "htm/preact";

const api = async (path, init) => {
  const r = await fetch(path, init);
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
};

// -------- Routing --------

function useHashRoute() {
  const [hash, setHash] = useState(window.location.hash.slice(1) || "/");
  useEffect(() => {
    const onHash = () => setHash(window.location.hash.slice(1) || "/");
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  return hash;
}

const go = (path) => {
  window.location.hash = path;
};

// -------- Shared UI --------

function Nav({ active }) {
  const link = (path, label) =>
    html`<a
      class=${`px-3 py-2 rounded text-sm ${
        active === path ? "bg-slate-900 text-white" : "text-slate-700 hover:bg-slate-200"
      }`}
      href=${`#${path}`}
    >${label}</a>`;
  return html`
    <header class="bg-white border-b border-slate-200">
      <div class="max-w-6xl mx-auto px-6 py-3 flex items-center gap-4">
        <span class="font-bold tracking-tight text-slate-900">
          Schwarz Git Ready Barcelona Hackathon <span class="text-slate-400 font-normal">data portal</span>
        </span>
        <nav class="ml-6 flex gap-1">
          ${link("/", "Catalog")}
          ${link("/chat", "Chat")}
          ${link("/publish", "Publish")}
          ${link("/approvals", "Approvals")}
          ${link("/requests", "My requests")}
          ${link("/admin", "Admin")}
        </nav>
      </div>
    </header>
  `;
}

function Chip({ children }) {
  return html`<span class="text-xs px-2 py-0.5 rounded-full bg-slate-100 text-slate-700 border border-slate-200 mr-1 mb-1 inline-block">
    ${children}
  </span>`;
}

function Pill({ children, tone = "indigo" }) {
  const tones = {
    indigo: "bg-indigo-50 text-indigo-700 border-indigo-200",
    emerald: "bg-emerald-50 text-emerald-700 border-emerald-200",
    amber: "bg-amber-50 text-amber-700 border-amber-200",
    slate: "bg-slate-50 text-slate-700 border-slate-200",
  };
  return html`<span class=${`text-xs px-2 py-0.5 rounded-full border ${tones[tone]}`}>${children}</span>`;
}

// -------- Catalog view --------

function Catalog() {
  const [q, setQ] = useState("");
  const [models, setModels] = useState([]);
  const [allMetrics, setAllMetrics] = useState([]);
  const [hits, setHits] = useState(null);
  const [fallback, setFallback] = useState(null);
  const [loadingFallback, setLoadingFallback] = useState(false);

  useEffect(() => {
    api("/api/models").then(setModels).catch(console.error);
    api("/api/metrics").then(setAllMetrics).catch(console.error);
  }, []);

  // Search-as-you-type, debounced.
  useEffect(() => {
    const t = setTimeout(async () => {
      if (!q.trim()) {
        setHits(null);
        setFallback(null);
        return;
      }
      const res = await api(`/api/search?q=${encodeURIComponent(q)}`);
      setHits(res.hits);
      if (res.hits.length === 0) {
        setLoadingFallback(true);
        try {
          const fb = await api("/api/search/fallback", {
            method: "POST",
            headers: { "content-type": "application/json" },
            body: JSON.stringify({ query: q }),
          });
          setFallback(fb);
        } catch (e) {
          setFallback({ query: q, rationale: String(e), suggested_models: [], owner_contacts: [], request_action: "" });
        } finally {
          setLoadingFallback(false);
        }
      } else {
        setFallback(null);
      }
    }, 250);
    return () => clearTimeout(t);
  }, [q]);

  return html`
    <div class="max-w-6xl mx-auto px-6 py-8">
      <h1 class="text-2xl font-semibold mb-2">Find a metric</h1>
      <p class="text-slate-600 mb-6">
        Search every OSI-registered metric across the four datasets. Try
        <span class="text-slate-900 font-medium">"basket"</span>,
        <span class="text-slate-900 font-medium">"fare"</span>, or
        <span class="text-slate-900 font-medium">"net sales"</span>.
      </p>
      <input
        autoFocus
        value=${q}
        onInput=${(e) => setQ(e.target.value)}
        placeholder="Search metrics, synonyms, descriptions…"
        class="w-full px-4 py-3 rounded-lg border border-slate-300 bg-white shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-200"
      />

      ${hits === null
        ? html`
            <div class="mt-8">
              <h2 class="text-sm font-semibold uppercase tracking-wider text-slate-500 mb-3">All models</h2>
              <div class="grid md:grid-cols-2 gap-3">
                ${models.map(
                  (m) => html`
                    <a href=${`#/m/${m.name}`} class="block bg-white border border-slate-200 rounded-lg p-4 hover:border-indigo-300 hover:shadow-sm transition">
                      <div class="flex items-start justify-between gap-3">
                        <div>
                          <div class="font-medium text-slate-900">${m.name}</div>
                          <div class="text-sm text-slate-600 mt-1">${m.description}</div>
                        </div>
                        <${Pill} tone=${m.domain ? "emerald" : "slate"}>
                          ${m.domain || "no domain"}
                        <//>
                      </div>
                      <div class="mt-3 flex items-center gap-3 text-xs text-slate-500">
                        <span>${m.metric_count} metrics</span>
                        <span>·</span>
                        <span>${m.dimension_count} dimensions</span>
                        <span>·</span>
                        <span class="font-mono">${m.source || "—"}</span>
                      </div>
                      <div class="mt-2 flex flex-wrap items-center gap-1">
                        ${(m.engines || []).map(
                          (eng) => html`<${Pill} tone=${eng === m.default_engine ? "indigo" : "slate"}>${eng}<//>`,
                        )}
                      </div>
                    </a>
                  `,
                )}
              </div>

              <h2 class="text-sm font-semibold uppercase tracking-wider text-slate-500 mt-8 mb-3">All metrics</h2>
              <div class="bg-white border border-slate-200 rounded-lg divide-y divide-slate-100">
                ${allMetrics.map(
                  (m) => html`
                    <a href=${`#/m/${m.model}`} class="flex items-center justify-between px-4 py-2 hover:bg-slate-50">
                      <div>
                        <span class="font-medium">${m.display_name || m.name}</span>
                        <span class="text-slate-400 ml-2 text-sm">${m.name}</span>
                      </div>
                      <span class="text-xs text-slate-500 font-mono">${m.model}</span>
                    </a>
                  `,
                )}
              </div>
            </div>
          `
        : hits.length > 0
        ? html`
            <div class="mt-8 grid md:grid-cols-2 gap-3">
              ${hits.map(
                (h) => html`
                  <a href=${`#/m/${h.model}`} class="block bg-white border border-slate-200 rounded-lg p-4 hover:border-indigo-300 hover:shadow-sm transition">
                    <div class="flex items-start justify-between gap-3">
                      <div>
                        <div class="font-medium">${h.display_name || h.name}</div>
                        <div class="text-sm text-slate-600 mt-1">${h.description}</div>
                      </div>
                      <${Pill}>${h.score.toFixed(1)}<//>
                    </div>
                    <div class="mt-2 text-xs text-slate-500 font-mono">${h.model}.${h.name}</div>
                    <div class="mt-2">
                      ${(h.synonyms || []).map((s) => html`<${Chip}>${s}<//>`)}
                    </div>
                  </a>
                `,
              )}
            </div>
          `
        : html`
            <div class="mt-8 bg-amber-50 border border-amber-200 rounded-lg p-5">
              <div class="text-amber-900 font-medium">No metric matches "${q}".</div>
              ${loadingFallback
                ? html`<div class="text-amber-800 text-sm mt-2">Asking Gemini for a suggestion…</div>`
                : fallback
                ? html`
                    <div class="mt-3 space-y-2 text-amber-900 text-sm">
                      <div><span class="font-semibold">Rationale:</span> ${fallback.rationale}</div>
                      ${fallback.suggested_models?.length
                        ? html`
                            <div>
                              <span class="font-semibold">Try:</span>
                              ${fallback.suggested_models.map(
                                (m) =>
                                  html`<a href=${`#/m/${m}`} class="ml-2 underline text-indigo-700">${m}</a>`,
                              )}
                            </div>
                          `
                        : null}
                      ${fallback.owner_contacts?.length
                        ? html`
                            <div>
                              <span class="font-semibold">Contact:</span>
                              ${fallback.owner_contacts.map((o) => html`<span class="ml-1 font-mono">${o}</span>`)}
                            </div>
                          `
                        : null}
                      ${fallback.request_action
                        ? html`<div><span class="font-semibold">Next step:</span> ${fallback.request_action}</div>`
                        : null}
                    </div>
                  `
                : null}
            </div>
          `}
    </div>
  `;
}

// -------- Detail view --------

function Detail({ name }) {
  const [model, setModel] = useState(null);
  const [requesting, setRequesting] = useState(false);
  const [requestResult, setRequestResult] = useState(null);
  const [requester, setRequester] = useState("");
  const [reason, setReason] = useState("");
  const [lineage, setLineage] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    setModel(null);
    setRequestResult(null);
    setLineage(null);
    setError(null);
    api(`/api/models/${encodeURIComponent(name)}`).then(setModel).catch((e) => setError(String(e)));
    api(`/api/models/${encodeURIComponent(name)}/lineage`).then(setLineage).catch(() => {});
  }, [name]);

  if (error) {
    return html`<div class="max-w-6xl mx-auto px-6 py-8 text-red-700">Error: ${error}</div>`;
  }
  if (!model) {
    return html`<div class="max-w-6xl mx-auto px-6 py-8 text-slate-500">Loading…</div>`;
  }

  const requestAccess = async () => {
    setRequesting(true);
    try {
      const r = await api("/api/access-requests", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ model: name, requester, business_justification: reason }),
      });
      setRequestResult(r);
    } catch (e) {
      setError(String(e));
    } finally {
      setRequesting(false);
    }
  };

  return html`
    <div class="max-w-6xl mx-auto px-6 py-8">
      <a href="#/" class="text-sm text-indigo-600 hover:underline">← Catalog</a>
      <div class="mt-2 flex flex-wrap items-center gap-2">
        <h1 class="text-2xl font-semibold">${model.name}</h1>
        ${model.odcs?.domain ? html`<${Pill} tone="emerald">${model.odcs.domain}<//>` : null}
        ${model.odcs?.data_product ? html`<${Pill} tone="indigo">${model.odcs.data_product}<//>` : null}
        ${(model.engines || []).map(
          (eng) => html`<${Pill} tone=${eng === model.default_engine ? "indigo" : "slate"}>${eng}<//>`,
        )}
      </div>
      <p class="text-slate-600 mt-1">${model.description}</p>

      <div class="mt-6 grid md:grid-cols-3 gap-3 text-sm">
        <div class="bg-white border border-slate-200 rounded p-4">
          <div class="text-slate-500 text-xs uppercase tracking-wider">Source</div>
          <div class="font-mono mt-1">${model.source || "—"}</div>
        </div>
        <div class="bg-white border border-slate-200 rounded p-4">
          <div class="text-slate-500 text-xs uppercase tracking-wider">Owner</div>
          <div class="mt-1">${model.odcs?.owner || "—"}</div>
        </div>
        <div class="bg-white border border-slate-200 rounded p-4">
          <div class="text-slate-500 text-xs uppercase tracking-wider">Engine FQN</div>
          <div class="font-mono mt-1 text-xs">${model.fqn || "—"}</div>
        </div>
      </div>

      <h2 class="text-sm font-semibold uppercase tracking-wider text-slate-500 mt-8 mb-2">Metrics (${model.metrics.length})</h2>
      <div class="bg-white border border-slate-200 rounded-lg divide-y divide-slate-100">
        ${model.metrics.map(
          (m) => html`
            <div class="px-4 py-3">
              <div class="flex items-center justify-between">
                <div>
                  <span class="font-medium">${m.display_name || m.name}</span>
                  <span class="text-slate-400 ml-2 text-sm">${m.name}</span>
                </div>
              </div>
              <div class="text-sm text-slate-600 mt-1">${m.description}</div>
              <div class="mt-2">
                ${(m.synonyms || []).map((s) => html`<${Chip}>${s}<//>`)}
              </div>
            </div>
          `,
        )}
      </div>

      <h2 class="text-sm font-semibold uppercase tracking-wider text-slate-500 mt-8 mb-2">Dimensions (${model.dimensions.length})</h2>
      <div class="bg-white border border-slate-200 rounded-lg divide-y divide-slate-100">
        ${model.dimensions.map(
          (d) => html`
            <div class="px-4 py-3 flex items-center justify-between">
              <div>
                <span class="font-medium">${d.display_name || d.name}</span>
                <span class="text-slate-400 ml-2 text-sm">${d.name}</span>
                ${d.is_time ? html`<${Pill} tone="amber">time<//>` : null}
              </div>
              <div class="text-xs text-slate-500">${(d.synonyms || []).join(", ")}</div>
            </div>
          `,
        )}
      </div>

      <h2 class="text-sm font-semibold uppercase tracking-wider text-slate-500 mt-8 mb-2">
        Lineage
        ${lineage ? html`<${Pill} tone=${lineage.mode === "live" ? "emerald" : "slate"}>${lineage.mode}<//>` : null}
      </h2>
      <div class="bg-white border border-slate-200 rounded-lg p-4 grid md:grid-cols-2 gap-4 text-sm">
        <div>
          <div class="text-slate-500 text-xs uppercase tracking-wider mb-1">Upstream</div>
          ${!lineage ? html`<div class="text-slate-400">Loading…</div>` :
            lineage.upstream?.length === 0 ? html`<div class="text-slate-400 text-xs">No upstream tables found.</div>` :
            lineage.upstream.map((u) => html`<div class="font-mono text-xs py-0.5">${u.fqn}</div>`)}
        </div>
        <div>
          <div class="text-slate-500 text-xs uppercase tracking-wider mb-1">Downstream</div>
          ${!lineage ? html`<div class="text-slate-400">Loading…</div>` :
            lineage.downstream?.length === 0 ? html`<div class="text-slate-400 text-xs">No downstream consumers found.</div>` :
            lineage.downstream.map((d) => html`<div class="font-mono text-xs py-0.5">${d.fqn}</div>`)}
        </div>
        ${lineage && lineage.versions?.length ? html`
          <div class="md:col-span-2">
            <div class="text-slate-500 text-xs uppercase tracking-wider mb-1 mt-2">Contract revisions</div>
            ${lineage.versions.map((v) => html`
              <div class="text-xs flex items-center gap-2 py-0.5">
                <${Pill} tone="slate">v${v.version}<//>
                <span class="text-slate-500 font-mono">${v.created_at}</span>
              </div>
            `)}
          </div>
        ` : null}
      </div>

      <h2 class="text-sm font-semibold uppercase tracking-wider text-slate-500 mt-8 mb-2">Request access</h2>
      <div class="bg-white border border-slate-200 rounded-lg p-4 space-y-3">
        ${requestResult
          ? html`
              <div>
                <div class="flex items-center gap-2">
                  <span class="text-slate-900 font-medium">Request ${requestResult.id.slice(0, 8)}</span>
                  <${Pill} tone=${
                    requestResult.status === "granted" ? "emerald" :
                    requestResult.status === "pending_approval" ? "amber" :
                    requestResult.status === "rejected" ? "amber" :
                    requestResult.status === "failed" ? "amber" : "slate"
                  }>${requestResult.status}<//>
                </div>
                ${requestResult.status === "pending_approval"
                  ? html`<div class="mt-2 text-sm text-amber-800">${requestResult.note}</div>`
                  : html`
                      <div class="mt-3 space-y-2">
                        ${(requestResult.grants || []).map(
                          (g) => html`
                            <div class="flex items-start gap-3 text-sm">
                              <${Pill} tone=${
                                g.status === "granted" ? "emerald" :
                                g.status === "failed" ? "amber" :
                                g.status === "rejected" ? "amber" :
                                g.status === "dry-run" ? "indigo" : "slate"
                              }>${g.engine} · ${g.status}<//>
                              <span class="text-slate-600 font-mono text-xs">${g.detail}</span>
                            </div>
                          `,
                        )}
                      </div>
                    `}
              </div>
            `
          : html`
              <input
                value=${requester}
                onInput=${(e) => setRequester(e.target.value)}
                placeholder="Your email"
                class="w-full px-3 py-2 rounded border border-slate-300"
              />
              <textarea
                value=${reason}
                onInput=${(e) => setReason(e.target.value)}
                placeholder="Why you need access (optional)"
                class="w-full px-3 py-2 rounded border border-slate-300 h-20"
              ></textarea>
              <button
                disabled=${requesting || !requester}
                onClick=${requestAccess}
                class="px-4 py-2 rounded bg-indigo-600 hover:bg-indigo-700 disabled:bg-slate-300 text-white text-sm"
              >${requesting ? "Submitting…" : "Request access"}</button>
              <div class="text-xs text-slate-500">
                Access is granted across every engine the model declares in
                <span class="font-mono">custom_extensions</span>. Engines whose REST
                credentials are not set return <span class="font-mono">skipped</span>
                instead of failing the whole request.
              </div>
            `}
      </div>
    </div>
  `;
}

// -------- Chat view --------

function Chat() {
  const [question, setQuestion] = useState("");
  const [history, setHistory] = useState([]); // [{q, answer, trace}]
  const [busy, setBusy] = useState(false);
  const scroller = useRef(null);

  const send = async () => {
    const q = question.trim();
    if (!q) return;
    setQuestion("");
    setBusy(true);
    const placeholder = { q, answer: null, trace: [] };
    setHistory((h) => [...h, placeholder]);
    try {
      const res = await api("/api/chat", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ question: q }),
      });
      setHistory((h) => {
        const copy = h.slice();
        copy[copy.length - 1] = { q, answer: res.answer, trace: res.trace || [] };
        return copy;
      });
    } catch (e) {
      setHistory((h) => {
        const copy = h.slice();
        copy[copy.length - 1] = { q, answer: `Error: ${e}`, trace: [] };
        return copy;
      });
    } finally {
      setBusy(false);
      setTimeout(() => scroller.current?.scrollTo(0, scroller.current.scrollHeight), 50);
    }
  };

  return html`
    <div class="max-w-4xl mx-auto px-6 py-8">
      <h1 class="text-2xl font-semibold">Ask the data</h1>
      <p class="text-slate-600 mt-1 mb-4">
        The agent uses the OSI Bridge tool surface: it discovers models, picks a metric,
        and executes <span class="font-mono">MEASURE()</span> against the Databricks engine —
        no free-form SQL.
      </p>
      <div ref=${scroller} class="bg-white border border-slate-200 rounded-lg p-4 space-y-6 min-h-[60vh]">
        ${history.length === 0
          ? html`<div class="text-slate-400 text-sm">
              Try: <em>"What is the average basket in Germany by loyalty tier?"</em>,
              <em>"Top pickup zip codes by total fare last month"</em>,
              <em>"Net sales by ship mode"</em>
            </div>`
          : null}
        ${history.map(
          (h) => html`
            <div>
              <div class="flex items-start gap-3">
                <div class="rounded-full bg-indigo-600 text-white text-xs px-2 py-1">You</div>
                <div class="text-slate-800">${h.q}</div>
              </div>
              ${h.trace?.length
                ? html`
                    <details class="mt-3 ml-9 text-xs text-slate-500">
                      <summary class="cursor-pointer hover:text-slate-700">${h.trace.length} tool call${h.trace.length === 1 ? "" : "s"}</summary>
                      <div class="mt-2 space-y-2">
                        ${h.trace.map(
                          (t) => html`
                            <div class="bg-slate-50 border border-slate-200 rounded p-2">
                              <div class="font-mono"><span class="text-indigo-700">${t.name}</span>(${JSON.stringify(t.arguments)})</div>
                              <pre class="mt-1 text-slate-600">${t.result_preview}</pre>
                            </div>
                          `,
                        )}
                      </div>
                    </details>
                  `
                : null}
              <div class="mt-3 ml-9">
                ${h.answer === null
                  ? html`<div class="text-slate-400">Thinking…</div>`
                  : html`<div class="whitespace-pre-wrap text-slate-900">${h.answer}</div>`}
              </div>
            </div>
          `,
        )}
      </div>
      <div class="mt-4 flex gap-2">
        <input
          value=${question}
          onInput=${(e) => setQuestion(e.target.value)}
          onKeyDown=${(e) => e.key === "Enter" && send()}
          placeholder="Ask the data a question…"
          class="flex-1 px-3 py-2 rounded border border-slate-300"
        />
        <button
          disabled=${busy || !question.trim()}
          onClick=${send}
          class="px-4 py-2 rounded bg-indigo-600 hover:bg-indigo-700 disabled:bg-slate-300 text-white text-sm"
        >${busy ? "Asking…" : "Ask"}</button>
      </div>
    </div>
  `;
}

// -------- Access requests view --------

function Requests() {
  const [items, setItems] = useState([]);
  const [selected, setSelected] = useState(null);
  useEffect(() => {
    api("/api/access-requests").then(setItems).catch(console.error);
  }, []);
  const openDetail = async (id) => {
    setSelected(null);
    const d = await api(`/api/access-requests/${encodeURIComponent(id)}`);
    setSelected(d);
  };
  const toneFor = (s) =>
    s === "granted" ? "emerald" :
    s === "partial" ? "indigo" :
    s === "failed" ? "amber" :
    s === "dry-run" ? "indigo" : "slate";
  return html`
    <div class="max-w-4xl mx-auto px-6 py-8">
      <h1 class="text-2xl font-semibold">Access requests</h1>
      <p class="text-slate-600 mt-1 mb-4">
        Each request fires a grant against every engine the model declares. Granted /
        skipped / failed are recorded per engine so the audit trail captures exactly
        what ran.
      </p>
      <div class="bg-white border border-slate-200 rounded-lg divide-y divide-slate-100">
        ${items.length === 0
          ? html`<div class="px-4 py-3 text-slate-500 text-sm">No requests yet.</div>`
          : items.map(
              (r) => html`
                <button onClick=${() => openDetail(r.id)} class="w-full text-left px-4 py-3 hover:bg-slate-50">
                  <div class="flex items-center justify-between">
                    <div class="font-medium">${r.model}</div>
                    <${Pill} tone=${toneFor(r.status)}>${r.status}<//>
                  </div>
                  <div class="text-sm text-slate-600">by ${r.requester}</div>
                  <div class="text-xs text-slate-400 mt-1 font-mono">${r.id}</div>
                </button>
              `,
            )}
      </div>

      ${selected
        ? html`
            <div class="mt-6 bg-white border border-slate-200 rounded-lg p-4">
              <div class="flex items-center justify-between">
                <div>
                  <div class="font-medium">${selected.model}</div>
                  <div class="text-sm text-slate-500">by ${selected.requester}</div>
                </div>
                <${Pill} tone=${toneFor(selected.status)}>${selected.status}<//>
              </div>
              <div class="mt-3 space-y-2">
                ${(selected.grants || []).map(
                  (g) => html`
                    <div class="flex items-start gap-3 text-sm">
                      <${Pill} tone=${toneFor(g.status)}>${g.engine} · ${g.status}<//>
                      <span class="text-slate-600 font-mono text-xs">${g.detail}</span>
                    </div>
                  `,
                )}
              </div>
            </div>
          `
        : null}
    </div>
  `;
}

// -------- Approvals view --------

function Approvals() {
  // Owner identity comes from a ?as=email query in the hash for the demo;
  // in production this is X-Forwarded-User from the Databricks Apps runtime.
  const initial = useMemo(() => {
    const m = window.location.hash.match(/[?&]as=([^&]+)/);
    return m ? decodeURIComponent(m[1]) : localStorage.getItem("portal_as") || "";
  }, []);
  const [owner, setOwner] = useState(initial);
  const [items, setItems] = useState([]);
  const [approver, setApprover] = useState(initial);
  const [reason, setReason] = useState("");
  const [busyId, setBusyId] = useState(null);

  const refresh = async (eml) => {
    const target = eml ?? owner;
    if (!target) {
      setItems([]);
      return;
    }
    const res = await api(`/api/access-requests?owner=${encodeURIComponent(target)}&status=pending_approval`);
    setItems(res);
  };

  useEffect(() => {
    refresh(initial);
  }, [initial]);

  const onSignIn = () => {
    localStorage.setItem("portal_as", owner);
    setApprover(owner);
    refresh(owner);
  };

  const decide = async (id, verb) => {
    if (!approver) return;
    setBusyId(id);
    try {
      await api(`/api/access-requests/${encodeURIComponent(id)}/${verb}`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ approver, reason }),
      });
      await refresh();
    } catch (e) {
      console.error(e);
    } finally {
      setBusyId(null);
      setReason("");
    }
  };

  return html`
    <div class="max-w-4xl mx-auto px-6 py-8">
      <h1 class="text-2xl font-semibold">Pending approvals</h1>
      <p class="text-slate-600 mt-1 mb-4">
        Requests on models you own. Approve to fire the provisioning fan-out; reject to record a denial with reason.
      </p>

      <div class="bg-white border border-slate-200 rounded p-4 mb-4 flex items-center gap-2">
        <input value=${owner} onInput=${(e) => setOwner(e.target.value)}
               placeholder="Sign in as owner email"
               class="flex-1 px-3 py-2 rounded border border-slate-300" />
        <button onClick=${onSignIn} class="px-3 py-2 rounded bg-indigo-600 text-white text-sm">Sign in</button>
      </div>

      ${!approver ? html`<div class="text-slate-500 text-sm">Sign in as a model owner to see pending requests.</div>` :
        items.length === 0 ? html`<div class="text-slate-500 text-sm">No requests waiting for ${approver}.</div>` :
        html`
          <div class="bg-white border border-slate-200 rounded-lg divide-y divide-slate-100">
            ${items.map(
              (r) => html`
                <div class="px-4 py-3">
                  <div class="flex items-center justify-between">
                    <div>
                      <div class="font-medium">${r.model}</div>
                      <div class="text-sm text-slate-500">requested by ${r.requester}</div>
                    </div>
                    <${Pill} tone="amber">${r.status}<//>
                  </div>
                  <div class="mt-3 flex flex-wrap items-center gap-2">
                    <input value=${reason} onInput=${(e) => setReason(e.target.value)}
                           placeholder="Reason (optional)"
                           class="flex-1 px-3 py-1.5 rounded border border-slate-300 text-sm" />
                    <button disabled=${busyId === r.id} onClick=${() => decide(r.id, "approve")}
                            class="px-3 py-1.5 rounded bg-emerald-600 hover:bg-emerald-700 disabled:bg-slate-300 text-white text-sm">
                      ${busyId === r.id ? "…" : "Approve"}
                    </button>
                    <button disabled=${busyId === r.id} onClick=${() => decide(r.id, "reject")}
                            class="px-3 py-1.5 rounded bg-slate-200 hover:bg-slate-300 disabled:bg-slate-100 text-slate-900 text-sm">
                      Reject
                    </button>
                  </div>
                </div>
              `,
            )}
          </div>
        `}
    </div>
  `;
}

// -------- Publish view (producer journey) --------

function Publish() {
  const [step, setStep] = useState("compose"); // compose | review | done
  const [fqn, setFqn] = useState("main.sales.transactions");
  const [domain, setDomain] = useState("sales");
  const [owner, setOwner] = useState("");
  const [description, setDescription] = useState("");
  const [dryRun, setDryRun] = useState(true);
  const [inferring, setInferring] = useState(false);
  const [inferred, setInferred] = useState(null);
  const [osiYaml, setOsiYaml] = useState("");
  const [odcsYaml, setOdcsYaml] = useState("");
  const [publishing, setPublishing] = useState(false);
  const [published, setPublished] = useState(null);
  const [error, setError] = useState(null);

  const runInfer = async () => {
    setInferring(true);
    setError(null);
    try {
      const result = await api("/api/producer/infer", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ fqn, domain, owner, description, dry_run: dryRun }),
      });
      setInferred(result);
      setOsiYaml(result.osi_yaml);
      setOdcsYaml(result.odcs_yaml);
      setStep("review");
    } catch (e) {
      setError(String(e));
    } finally {
      setInferring(false);
    }
  };

  const runPublish = async () => {
    setPublishing(true);
    setError(null);
    try {
      // We publish the originally-inferred OSI/ODCS dicts, not the YAML
      // textareas — browsers don't ship a YAML parser and the textareas
      // here are a review surface, not an editor. Phase 6 stretch: ship a
      // structured form for per-field edits.
      const result = await api("/api/producer/publish", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ osi: inferred.osi, odcs: inferred.odcs, dry_run: dryRun }),
      });
      setPublished(result);
      setStep("done");
    } catch (e) {
      setError(String(e));
    } finally {
      setPublishing(false);
    }
  };

  return html`
    <div class="max-w-5xl mx-auto px-6 py-8">
      <h1 class="text-2xl font-semibold">Publish a dataset</h1>
      <p class="text-slate-600 mt-1 mb-6">
        Producer journey: point at a Unity Catalog table, get an AI-drafted OSI + ODCS contract,
        review and edit it, then publish to the contracts repo and the model store in one click.
      </p>

      ${error ? html`<div class="bg-amber-50 border border-amber-200 rounded p-3 text-amber-900 mb-4">${error}</div>` : null}

      ${step === "compose"
        ? html`
            <div class="bg-white border border-slate-200 rounded-lg p-5 space-y-3">
              <label class="block">
                <span class="text-sm text-slate-600">Source table FQN</span>
                <input value=${fqn} onInput=${(e) => setFqn(e.target.value)}
                       class="w-full mt-1 px-3 py-2 rounded border border-slate-300 font-mono"
                       placeholder="catalog.schema.table" />
              </label>
              <div class="grid md:grid-cols-2 gap-3">
                <label class="block">
                  <span class="text-sm text-slate-600">Domain</span>
                  <input value=${domain} onInput=${(e) => setDomain(e.target.value)}
                         class="w-full mt-1 px-3 py-2 rounded border border-slate-300" placeholder="retail / sales / mobility" />
                </label>
                <label class="block">
                  <span class="text-sm text-slate-600">Owner email</span>
                  <input value=${owner} onInput=${(e) => setOwner(e.target.value)}
                         class="w-full mt-1 px-3 py-2 rounded border border-slate-300" placeholder="team@schwarz.com" />
                </label>
              </div>
              <label class="block">
                <span class="text-sm text-slate-600">Short description</span>
                <textarea value=${description} onInput=${(e) => setDescription(e.target.value)}
                          class="w-full mt-1 px-3 py-2 rounded border border-slate-300 h-20"
                          placeholder="One sentence describing the dataset's purpose."></textarea>
              </label>
              <label class="flex items-center gap-2 text-sm text-slate-600">
                <input type="checkbox" checked=${dryRun} onChange=${(e) => setDryRun(e.target.checked)} />
                Dry-run (no warehouse / Gemini / GitHub calls)
              </label>
              <button onClick=${runInfer} disabled=${inferring || !fqn || !domain || !owner}
                      class="px-4 py-2 rounded bg-indigo-600 hover:bg-indigo-700 disabled:bg-slate-300 text-white text-sm">
                ${inferring ? "Inferring…" : "Infer contract"}
              </button>
            </div>
          `
        : null}

      ${step === "review" && inferred
        ? html`
            <div class="space-y-4">
              <div class="bg-white border border-slate-200 rounded p-4">
                <div class="text-sm text-slate-600">
                  Inferred ${inferred.columns.length} columns. AI enrichment:
                  <${Pill} tone=${inferred.ai_used ? "emerald" : "slate"}>${inferred.ai_used ? "Gemini" : "heuristic"}<//>
                </div>
                <div class="mt-2 text-xs text-slate-500">
                  Metrics: ${inferred.metrics_summary.join(", ")}
                </div>
              </div>
              <div>
                <label class="text-sm text-slate-600 font-medium">OSI YAML preview</label>
                <pre class="w-full mt-1 px-3 py-2 rounded border border-slate-200 bg-slate-50 font-mono text-xs h-64 overflow-auto">${osiYaml}</pre>
              </div>
              <div>
                <label class="text-sm text-slate-600 font-medium">ODCS YAML preview</label>
                <pre class="w-full mt-1 px-3 py-2 rounded border border-slate-200 bg-slate-50 font-mono text-xs h-64 overflow-auto">${odcsYaml}</pre>
              </div>
              <div class="text-xs text-slate-500">
                Previews are read-only. Edit the committed YAMLs in the contracts repo after
                the first publish, or refine the input prompt and re-infer.
              </div>
              <div class="flex items-center gap-3">
                <button onClick=${() => setStep("compose")}
                        class="px-4 py-2 rounded border border-slate-300 text-sm">Back</button>
                <button onClick=${runPublish} disabled=${publishing}
                        class="px-4 py-2 rounded bg-indigo-600 hover:bg-indigo-700 disabled:bg-slate-300 text-white text-sm">
                  ${publishing ? "Publishing…" : "Publish contract"}
                </button>
                <label class="flex items-center gap-2 text-sm text-slate-600">
                  <input type="checkbox" checked=${dryRun} onChange=${(e) => setDryRun(e.target.checked)} />
                  Dry-run
                </label>
              </div>
            </div>
          `
        : null}

      ${step === "done" && published
        ? html`
            <div class="bg-white border border-slate-200 rounded-lg p-5 space-y-3">
              <div class="flex items-center gap-2">
                <span class="text-slate-900 font-medium">${published.model}</span>
                <${Pill} tone=${published.mode === "live" ? "emerald" : "indigo"}>${published.mode}<//>
                ${published.persisted_to_store ? html`<${Pill} tone="emerald">store: persisted<//>` : html`<${Pill} tone="slate">store: in-memory<//>`}
              </div>
              <div class="text-sm text-slate-600">${published.commit_message}</div>
              <div class="space-y-2">
                ${published.files.map(
                  (f) => html`
                    <div class="flex items-start gap-3 text-sm">
                      <${Pill} tone=${f.status === "committed" ? "emerald" : f.status === "failed" ? "amber" : "indigo"}>${f.status}<//>
                      <span class="font-mono text-xs">${f.path}</span>
                      ${f.html_url ? html`<a class="text-indigo-600 underline text-xs" href=${f.html_url} target="_blank">commit</a>` : null}
                      ${f.detail ? html`<span class="text-slate-500 text-xs">${f.detail}</span>` : null}
                    </div>
                  `,
                )}
              </div>
              <div class="flex gap-2 pt-2">
                <a class="px-3 py-1.5 rounded border border-slate-300 text-sm" href=${`#/m/${published.model}`}>View in catalog</a>
                <button onClick=${() => { setStep("compose"); setInferred(null); setPublished(null); }}
                        class="px-3 py-1.5 rounded border border-slate-300 text-sm">Publish another</button>
              </div>
            </div>
          `
        : null}
    </div>
  `;
}

// -------- Root --------

function ImportOsi() {
  const [file, setFile] = useState(null);
  const [targetCatalog, setTargetCatalog] = useState("peymandemoaws_catalog");
  const [targetSchema, setTargetSchema] = useState("osi_demo");
  const [targetName, setTargetName] = useState("");
  const [orReplace, setOrReplace] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);

  const submit = async () => {
    if (!file) {
      setError("Pick a YAML file first.");
      return;
    }
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("target_catalog", targetCatalog);
      fd.append("target_schema", targetSchema);
      if (targetName.trim()) fd.append("target_name", targetName.trim());
      fd.append("or_replace", String(orReplace));
      const res = await fetch("/api/admin/import-osi", { method: "POST", body: fd });
      if (!res.ok) {
        const body = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(body.detail || res.statusText);
      }
      setResult(await res.json());
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setBusy(false);
    }
  };

  return html`
    <div class="bg-white border border-slate-200 rounded p-4 mb-6">
      <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
        <label class="block md:col-span-3">
          <span class="text-sm text-slate-600">OSI YAML file</span>
          <input type="file" accept=".yaml,.yml,application/x-yaml,text/yaml"
                 class="mt-1 block w-full text-sm"
                 onChange=${(e) => setFile(e.target.files?.[0] || null)} />
        </label>
        <label class="block">
          <span class="text-sm text-slate-600">Target catalog</span>
          <input class="mt-1 w-full border border-slate-300 rounded px-2 py-1 text-sm font-mono"
                 value=${targetCatalog} onInput=${(e) => setTargetCatalog(e.target.value)} />
        </label>
        <label class="block">
          <span class="text-sm text-slate-600">Target schema</span>
          <input class="mt-1 w-full border border-slate-300 rounded px-2 py-1 text-sm font-mono"
                 value=${targetSchema} onInput=${(e) => setTargetSchema(e.target.value)} />
        </label>
        <label class="block">
          <span class="text-sm text-slate-600">Override target name (optional)</span>
          <input class="mt-1 w-full border border-slate-300 rounded px-2 py-1 text-sm font-mono"
                 placeholder="defaults to OSI semantic_model.name"
                 value=${targetName} onInput=${(e) => setTargetName(e.target.value)} />
        </label>
      </div>
      <label class="block mt-3">
        <input type="checkbox" checked=${orReplace} onChange=${(e) => setOrReplace(e.target.checked)} />
        <span class="text-sm text-slate-600 ml-2">CREATE OR REPLACE (uncheck to fail if the view already exists)</span>
      </label>
      <div class="mt-4 flex items-center gap-3">
        <button class=${`px-4 py-2 rounded text-sm font-medium ${busy ? "bg-slate-300 text-slate-600" : "bg-amber-600 text-white hover:bg-amber-500"}`}
                disabled=${busy} onClick=${submit}>
          ${busy ? "Importing…" : "Import to Databricks"}
        </button>
        ${error && html`<span class="text-sm text-rose-600">${error}</span>`}
      </div>
      ${result && html`
        <div class="mt-4">
          <div class="flex items-center gap-2 mb-2">
            <${Pill} tone="emerald">imported</${Pill}>
            <span class="font-mono text-xs">${result.target_fqn}</span>
          </div>
          <details>
            <summary class="text-xs text-slate-500 cursor-pointer">Generated Databricks Metric View YAML</summary>
            <pre class="text-xs bg-slate-50 border border-slate-200 rounded p-2 mt-2">${result.mv_yaml}</pre>
          </details>
        </div>
      `}
    </div>
  `;
}

function Admin() {
  const [catalogs, setCatalogs] = useState("");
  const [schemas, setSchemas] = useState("");
  const [discovering, setDiscovering] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState(null);
  const [discovered, setDiscovered] = useState(null); // {total, metric_views}
  const [rowState, setRowState] = useState({}); // fqn -> {uploading, version, error}
  const [bulkResult, setBulkResult] = useState(null);
  const [stored, setStored] = useState([]);

  const refresh = async () => {
    try {
      const r = await api("/api/admin/mongo-models");
      setStored(r.models || []);
    } catch (e) {
      setError(String(e));
    }
  };
  useEffect(() => { refresh(); }, []);

  const scopeQS = () => {
    const qs = new URLSearchParams();
    if (catalogs.trim()) qs.set("catalogs", catalogs.trim());
    if (schemas.trim()) qs.set("schemas", schemas.trim());
    return qs.toString();
  };

  const discover = async () => {
    setDiscovering(true);
    setError(null);
    setDiscovered(null);
    setRowState({});
    try {
      const qs = scopeQS();
      const r = await api("/api/admin/discover" + (qs ? "?" + qs : ""));
      setDiscovered(r);
    } catch (e) {
      setError(String(e));
    } finally {
      setDiscovering(false);
    }
  };

  const syncAll = async () => {
    setSyncing(true);
    setError(null);
    setBulkResult(null);
    try {
      const qs = scopeQS();
      const r = await api("/api/admin/sync-from-workspace" + (qs ? "?" + qs : ""), { method: "POST" });
      setBulkResult(r);
      await refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setSyncing(false);
    }
  };

  const uploadOne = async (fqn) => {
    setRowState((s) => ({ ...s, [fqn]: { ...(s[fqn] || {}), uploading: true, error: null } }));
    try {
      const r = await api("/api/admin/upload-to-mongo", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ fqn }),
      });
      setRowState((s) => ({ ...s, [fqn]: { uploading: false, version: r.version, model: r.model } }));
      await refresh();
    } catch (e) {
      setRowState((s) => ({ ...s, [fqn]: { uploading: false, error: String(e) } }));
    }
  };

  return html`
    <div class="max-w-6xl mx-auto px-6 py-8">
      <h1 class="text-2xl font-semibold mb-2">Workspace sync</h1>
      <p class="text-slate-600 mb-6">
        Discover the Metric Views the SQL warehouse can see, then export each
        one to an OSI YAML file or push it into the central catalog (mock
        MongoDB). Leave the filters blank to scan the whole metastore.
      </p>

      <div class="bg-white border border-slate-200 rounded p-4 mb-6">
        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
          <label class="block">
            <span class="text-sm text-slate-600">Catalogs (comma-separated, optional)</span>
            <input class="mt-1 w-full border border-slate-300 rounded px-2 py-1 text-sm font-mono"
                   placeholder="peymandemoaws_catalog"
                   value=${catalogs} onInput=${(e) => setCatalogs(e.target.value)} />
          </label>
          <label class="block">
            <span class="text-sm text-slate-600">Schemas (comma-separated, optional)</span>
            <input class="mt-1 w-full border border-slate-300 rounded px-2 py-1 text-sm font-mono"
                   placeholder="osi_demo"
                   value=${schemas} onInput=${(e) => setSchemas(e.target.value)} />
          </label>
        </div>
        <div class="mt-4 flex items-center gap-3">
          <button class=${`px-4 py-2 rounded text-sm font-medium ${discovering ? "bg-slate-300 text-slate-600" : "bg-slate-900 text-white hover:bg-slate-700"}`}
                  disabled=${discovering || syncing} onClick=${discover}>
            ${discovering ? "Discovering…" : "Discover metric views"}
          </button>
          <button class=${`px-4 py-2 rounded text-sm font-medium ${syncing ? "bg-slate-300 text-slate-600" : "bg-indigo-600 text-white hover:bg-indigo-500"}`}
                  disabled=${discovering || syncing} onClick=${syncAll}>
            ${syncing ? "Syncing all…" : "Sync all to MongoDB"}
          </button>
          ${error && html`<span class="text-sm text-rose-600">${error}</span>`}
        </div>
      </div>

      ${discovered && html`
        <div class="bg-white border border-slate-200 rounded p-4 mb-6">
          <div class="flex items-center justify-between mb-3">
            <h2 class="font-semibold">Found ${discovered.total} metric view${discovered.total === 1 ? "" : "s"}</h2>
          </div>
          ${discovered.total === 0
            ? html`<p class="text-sm text-slate-500">No metric views in the selected scope.</p>`
            : html`
              <table class="w-full text-sm">
                <thead class="text-left text-slate-500">
                  <tr>
                    <th class="py-1 pr-3">FQN</th>
                    <th class="py-1 pr-3">Actions</th>
                    <th class="py-1">Status</th>
                  </tr>
                </thead>
                <tbody>
                  ${discovered.metric_views.map((mv) => {
                    const st = rowState[mv.fqn] || {};
                    return html`
                      <tr class="border-t border-slate-100">
                        <td class="py-1 pr-3 font-mono text-xs">${mv.fqn}</td>
                        <td class="py-1 pr-3">
                          <a class="inline-block px-2 py-1 rounded border border-slate-300 text-xs mr-2 hover:bg-slate-100"
                             href=${`/api/admin/export-osi?fqn=${encodeURIComponent(mv.fqn)}`}>
                            Download OSI YAML
                          </a>
                          <button class=${`inline-block px-2 py-1 rounded text-xs font-medium ${st.uploading ? "bg-slate-300 text-slate-600" : "bg-emerald-600 text-white hover:bg-emerald-500"}`}
                                  disabled=${st.uploading} onClick=${() => uploadOne(mv.fqn)}>
                            ${st.uploading ? "Uploading…" : "Upload to MongoDB"}
                          </button>
                        </td>
                        <td class="py-1">
                          ${st.version
                            ? html`<${Pill} tone="emerald">stored v${st.version}</${Pill}>`
                            : st.error
                              ? html`<span class="text-rose-600 text-xs">${st.error}</span>`
                              : html`<span class="text-slate-400 text-xs">—</span>`}
                        </td>
                      </tr>
                    `;
                  })}
                </tbody>
              </table>
            `}
        </div>
      `}

      ${bulkResult && html`
        <div class="bg-white border border-slate-200 rounded p-4 mb-6">
          <div class="flex gap-4 text-sm mb-3">
            <${Pill} tone="slate">Scanned ${bulkResult.total}</${Pill}>
            <${Pill} tone="emerald">Succeeded ${bulkResult.succeeded}</${Pill}>
            <${Pill} tone=${bulkResult.failed ? "amber" : "slate"}>Failed ${bulkResult.failed}</${Pill}>
          </div>
          <table class="w-full text-sm">
            <thead class="text-left text-slate-500">
              <tr><th class="py-1 pr-3">FQN</th><th class="py-1 pr-3">Model</th><th class="py-1 pr-3">Version</th><th class="py-1">Status</th></tr>
            </thead>
            <tbody>
              ${bulkResult.results.map((r) => html`
                <tr class="border-t border-slate-100">
                  <td class="py-1 pr-3 font-mono text-xs">${r.fqn}</td>
                  <td class="py-1 pr-3">${r.model || "—"}</td>
                  <td class="py-1 pr-3">${r.version ?? "—"}</td>
                  <td class="py-1">
                    ${r.status === "ok"
                      ? html`<${Pill} tone="emerald">ok</${Pill}>`
                      : html`<span class="text-rose-600 text-xs">${r.error}</span>`}
                  </td>
                </tr>
              `)}
            </tbody>
          </table>
        </div>
      `}

      <h2 class="text-lg font-semibold mb-2 mt-2">Import OSI → Databricks Metric View</h2>
      <p class="text-slate-600 mb-3 text-sm">
        Pick an OSI v1.0 YAML file and a target catalog/schema. The portal
        translates it to a Databricks Metric View YAML and runs
        <span class="font-mono">CREATE OR REPLACE VIEW … WITH METRICS</span>
        against the warehouse.
      </p>
      <${ImportOsi} />

      <h2 class="text-lg font-semibold mb-2 mt-8">Currently in central catalog (MongoDB)</h2>
      ${stored.length === 0
        ? html`<p class="text-sm text-slate-500">Nothing stored yet — discover then upload, or use "Sync all".</p>`
        : html`
          <table class="w-full text-sm bg-white border border-slate-200 rounded">
            <thead class="text-left text-slate-500">
              <tr><th class="py-2 px-3">Model</th><th class="py-2 px-3">Source FQN</th><th class="py-2 px-3">Updated</th></tr>
            </thead>
            <tbody>
              ${stored.map((m) => html`
                <tr class="border-t border-slate-100">
                  <td class="py-1 px-3 font-medium">${m.name}</td>
                  <td class="py-1 px-3 font-mono text-xs">${m.source || "—"}</td>
                  <td class="py-1 px-3 text-xs text-slate-500">${m.updated_at || ""}</td>
                </tr>
              `)}
            </tbody>
          </table>
        `}
    </div>
  `;
}

function App() {
  const hash = useHashRoute();
  const view = useMemo(() => {
    if (hash.startsWith("/m/")) return { kind: "detail", name: decodeURIComponent(hash.split("?")[0].slice(3)) };
    if (hash.startsWith("/chat")) return { kind: "chat" };
    if (hash.startsWith("/publish")) return { kind: "publish" };
    if (hash.startsWith("/approvals")) return { kind: "approvals" };
    if (hash.startsWith("/requests")) return { kind: "requests" };
    if (hash.startsWith("/admin")) return { kind: "admin" };
    return { kind: "catalog" };
  }, [hash]);

  let body;
  if (view.kind === "detail") body = html`<${Detail} name=${view.name} />`;
  else if (view.kind === "chat") body = html`<${Chat} />`;
  else if (view.kind === "publish") body = html`<${Publish} />`;
  else if (view.kind === "approvals") body = html`<${Approvals} />`;
  else if (view.kind === "requests") body = html`<${Requests} />`;
  else if (view.kind === "admin") body = html`<${Admin} />`;
  else body = html`<${Catalog} />`;

  return html`
    <${Nav} active=${view.kind === "detail" ? "/" : `/${view.kind === "catalog" ? "" : view.kind}`} />
    ${body}
  `;
}

render(html`<${App} />`, document.getElementById("app"));
