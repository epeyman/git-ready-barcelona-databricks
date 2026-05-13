// GIT READY data portal — preact + htm SPA, no build step.
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
          GIT&nbsp;READY <span class="text-slate-400 font-normal">data portal</span>
        </span>
        <nav class="ml-6 flex gap-1">
          ${link("/", "Catalog")}
          ${link("/chat", "Chat")}
          ${link("/requests", "My requests")}
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
  const [error, setError] = useState(null);

  useEffect(() => {
    setModel(null);
    setRequestResult(null);
    setError(null);
    api(`/api/models/${encodeURIComponent(name)}`).then(setModel).catch((e) => setError(String(e)));
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
      <div class="mt-2 flex items-center gap-3">
        <h1 class="text-2xl font-semibold">${model.name}</h1>
        ${model.odcs?.domain ? html`<${Pill} tone="emerald">${model.odcs.domain}<//>` : null}
        ${model.odcs?.data_product ? html`<${Pill} tone="indigo">${model.odcs.data_product}<//>` : null}
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

      <h2 class="text-sm font-semibold uppercase tracking-wider text-slate-500 mt-8 mb-2">Request access</h2>
      <div class="bg-white border border-slate-200 rounded-lg p-4 space-y-3">
        ${requestResult
          ? html`
              <div class="text-emerald-700">
                Request ${requestResult.id.slice(0, 8)} submitted. Status: ${requestResult.status}.
                <div class="text-xs text-slate-500 mt-1">${requestResult.note}</div>
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
                Phase 4 will provision access across Databricks, Dremio, and Strategy via REST.
                For now this logs the request in-process.
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
  useEffect(() => {
    api("/api/access-requests").then(setItems).catch(console.error);
  }, []);
  return html`
    <div class="max-w-4xl mx-auto px-6 py-8">
      <h1 class="text-2xl font-semibold">Access requests</h1>
      <p class="text-slate-600 mt-1 mb-4">
        In-memory log for the hackathon prototype. Phase 4 will persist these and trigger
        REST-based provisioning across Databricks, Dremio, and Strategy.
      </p>
      <div class="bg-white border border-slate-200 rounded-lg divide-y divide-slate-100">
        ${items.length === 0
          ? html`<div class="px-4 py-3 text-slate-500 text-sm">No requests yet.</div>`
          : items.map(
              (r) => html`
                <div class="px-4 py-3">
                  <div class="flex items-center justify-between">
                    <div class="font-medium">${r.model}</div>
                    <${Pill} tone="amber">${r.status}<//>
                  </div>
                  <div class="text-sm text-slate-600">by ${r.requester}</div>
                  <div class="text-xs text-slate-400 mt-1">${r.id}</div>
                </div>
              `,
            )}
      </div>
    </div>
  `;
}

// -------- Root --------

function App() {
  const hash = useHashRoute();
  const view = useMemo(() => {
    if (hash.startsWith("/m/")) return { kind: "detail", name: decodeURIComponent(hash.slice(3)) };
    if (hash === "/chat") return { kind: "chat" };
    if (hash === "/requests") return { kind: "requests" };
    return { kind: "catalog" };
  }, [hash]);

  let body;
  if (view.kind === "detail") body = html`<${Detail} name=${view.name} />`;
  else if (view.kind === "chat") body = html`<${Chat} />`;
  else if (view.kind === "requests") body = html`<${Requests} />`;
  else body = html`<${Catalog} />`;

  return html`
    <${Nav} active=${view.kind === "detail" ? "/" : `/${view.kind === "catalog" ? "" : view.kind}`} />
    ${body}
  `;
}

render(html`<${App} />`, document.getElementById("app"));
