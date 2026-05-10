"use strict";

const DATA_URL = "offers.json";
const REFRESH_MS = 60_000;
const FRESH_WINDOW_MS = 30 * 60 * 1000; // 30 min — pulse cards newer than this
const HOT_MIN_OPP = 75;

const state = {
  data: null,
  filtered: [],
  seenIds: new Set(),
  filters: {
    q: "",
    type: "",
    sort: "latest_seen_ts",
    minReward: 0,
    minTrust: 0,
    maxScam: 100,
    urgentOnly: false,
    hideSaturated: false,
    hideScammy: true,
  },
};

const el = {
  status: document.getElementById("status-line"),
  total: document.getElementById("stat-total"),
  shown: document.getElementById("stat-shown"),
  updated: document.getElementById("stat-updated"),
  q: document.getElementById("q"),
  type: document.getElementById("type"),
  sort: document.getElementById("sort"),
  minReward: document.getElementById("min-reward"),
  minTrust: document.getElementById("min-trust"),
  maxScam: document.getElementById("max-scam"),
  urgentOnly: document.getElementById("urgent-only"),
  hideSaturated: document.getElementById("hide-saturated"),
  hideScammy: document.getElementById("hide-scammy"),
  reset: document.getElementById("reset"),
  chips: document.getElementById("type-chips"),
  grid: document.getElementById("grid"),
  genStamp: document.getElementById("gen-stamp"),
  tpl: document.getElementById("card-tpl"),
  repoLink: document.getElementById("repo-link"),
};

// ---------------- helpers ----------------
function relTime(iso) {
  if (!iso) return "—";
  const ts = typeof iso === "number" ? iso * 1000 : Date.parse(iso);
  if (Number.isNaN(ts)) return "—";
  const d = Math.max(0, Date.now() - ts);
  const s = Math.floor(d / 1000);
  if (s < 60) return s + "s ago";
  const m = Math.floor(s / 60);
  if (m < 60) return m + "m ago";
  const h = Math.floor(m / 60);
  if (h < 24) return h + "h ago";
  const days = Math.floor(h / 24);
  if (days < 30) return days + "d ago";
  const months = Math.floor(days / 30);
  if (months < 12) return months + "mo ago";
  return Math.floor(days / 365) + "y ago";
}

function fmtScore(v) {
  if (v == null) return "—";
  const n = Number(v);
  if (Number.isNaN(n)) return "—";
  return n.toFixed(0);
}

function domainOf(u) {
  try {
    return new URL(u).hostname.replace(/^www\./, "");
  } catch (_) {
    return u || "";
  }
}

function debounce(fn, ms) {
  let t;
  return (...a) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...a), ms);
  };
}

function repoLinkFromLocation() {
  // user.github.io/Repo -> https://github.com/user/Repo
  const host = location.hostname;
  const match = host.match(/^([^.]+)\.github\.io$/i);
  const path = location.pathname.split("/").filter(Boolean);
  if (match && path.length > 0) {
    return "https://github.com/" + match[1] + "/" + path[0];
  }
  return "https://github.com/";
}

// ---------------- load ----------------
async function loadData() {
  try {
    const res = await fetch(DATA_URL + "?t=" + Date.now(), { cache: "no-store" });
    if (!res.ok) throw new Error("HTTP " + res.status);
    const data = await res.json();
    onData(data);
  } catch (err) {
    if (!state.data) {
      el.grid.innerHTML =
        '<div class="empty"><b>Could not load offers.json</b>The cron has not run yet, or this page is being viewed from a non-Pages host.<br><br><code style="color:#f85149">' +
        String(err) +
        "</code></div>";
      el.status.textContent = "Error loading offers.json";
    }
  }
}

function onData(data) {
  const wasNull = state.data === null;
  state.data = data;

  buildTypeOptions(data.offer_types || {});

  if (wasNull) {
    state.seenIds = new Set((data.offers || []).map((o) => o.id));
  } else {
    const newIds = new Set();
    for (const o of data.offers || []) {
      if (!state.seenIds.has(o.id)) {
        newIds.add(o.id);
        state.seenIds.add(o.id);
      }
    }
    state._newIds = newIds;
  }

  el.total.textContent = data.total_offers ?? "—";
  el.updated.textContent = relTime(data.generated_at_ts || data.generated_at);
  el.status.textContent =
    "Snapshot from " +
    (data.generated_at || "—") +
    " · " +
    (data.total_offers || 0) +
    " offers in DB · auto-refreshes every " +
    REFRESH_MS / 1000 +
    "s";
  el.genStamp.textContent = "snapshot " + (data.generated_at || "");

  render();
}

// ---------------- filters / sort ----------------
function applyFilters() {
  if (!state.data) {
    state.filtered = [];
    return;
  }
  const f = state.filters;
  const q = f.q.trim().toLowerCase();

  state.filtered = (state.data.offers || []).filter((o) => {
    if (f.type && o.type !== f.type) return false;
    if (f.urgentOnly && !o.urgent) return false;
    if (f.hideSaturated && (o.saturation || 0) >= 70) return false;
    if (f.hideScammy && (o.scam || 0) >= 60) return false;
    if ((o.reward_usd || 0) < f.minReward) return false;
    if ((o.trust || 0) < f.minTrust) return false;
    if ((o.scam || 0) > f.maxScam) return false;
    if (q) {
      const hay = (
        (o.company || "") +
        " " +
        (o.post_title || "") +
        " " +
        (o.ai_summary || "") +
        " " +
        (o.primary_domain || "") +
        " " +
        (o.subreddits || []).join(" ") +
        " " +
        (o.type || "")
      ).toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });

  const k = f.sort;
  state.filtered.sort((a, b) => (b[k] || 0) - (a[k] || 0));
}

function buildTypeOptions(typeCounts) {
  const opts = Object.entries(typeCounts).sort((a, b) => b[1] - a[1]);
  const current = el.type.value;

  el.type.innerHTML = '<option value="">All types</option>';
  for (const [t, n] of opts) {
    const opt = document.createElement("option");
    opt.value = t;
    opt.textContent = t + " (" + n + ")";
    el.type.appendChild(opt);
  }
  el.type.value = current;

  el.chips.innerHTML = "";
  const allChip = mkChip("", "All", state.data?.total_offers || 0);
  el.chips.appendChild(allChip);
  for (const [t, n] of opts.slice(0, 10)) el.chips.appendChild(mkChip(t, t, n));

  syncChipActive();
  renderDiscovered();
}

function renderDiscovered() {
  const host = document.getElementById("discovered-list");
  if (!host) return;
  host.innerHTML = "";
  const items = (state.data && state.data.discovered_subreddits) || [];
  if (!items.length) {
    host.innerHTML =
      '<div style="grid-column:1/-1;color:var(--muted)">No subs discovered yet — runs every cron tick.</div>';
    return;
  }
  for (const d of items.slice(0, 40)) {
    const row = document.createElement("div");
    row.className = "disc-item";
    const sub = (d.subreddit || "").toLowerCase();
    row.innerHTML =
      '<a href="https://reddit.com/r/' +
      encodeURIComponent(sub) +
      '" target="_blank" rel="noopener">r/' +
      sub +
      '</a><span class="hits">' +
      (d.hit_count || 0) +
      "</span>";
    host.appendChild(row);
  }
}

function mkChip(type, label, count) {
  const c = document.createElement("button");
  c.type = "button";
  c.className = "chip";
  c.dataset.type = type;
  c.innerHTML = label + ' <span class="n">' + count + "</span>";
  c.addEventListener("click", () => {
    state.filters.type = type;
    el.type.value = type;
    syncChipActive();
    render();
  });
  return c;
}

function syncChipActive() {
  for (const ch of el.chips.querySelectorAll(".chip")) {
    ch.classList.toggle("active", ch.dataset.type === state.filters.type);
  }
}

// ---------------- render ----------------
function render() {
  applyFilters();
  el.shown.textContent = state.filtered.length;
  el.grid.innerHTML = "";

  if (!state.filtered.length) {
    const why = state.data
      ? "Nothing matches your filters. Try lowering the min-trust slider, clearing the search box, or hitting Reset."
      : "Loading…";
    el.grid.innerHTML =
      '<div class="empty"><b>No matching offers</b>' + why + "</div>";
    return;
  }

  const frag = document.createDocumentFragment();
  for (const o of state.filtered) frag.appendChild(renderCard(o));
  el.grid.appendChild(frag);
}

function renderCard(o) {
  const node = el.tpl.content.firstElementChild.cloneNode(true);
  node.dataset.id = o.id || "";

  const isFresh =
    o.latest_seen_ts &&
    Date.now() - o.latest_seen_ts * 1000 < FRESH_WINDOW_MS;
  const isHot = (o.opportunity || 0) >= HOT_MIN_OPP || o.urgent;

  if (isHot) node.classList.add("hot");
  if (state._newIds && state._newIds.has(o.id)) node.classList.add("fresh");
  if (isFresh && !isHot) node.classList.add("hot");

  node.querySelector(".company").textContent = o.company || "(unknown)";
  const reward = (o.reward || "").trim();
  node.querySelector(".reward").textContent = reward
    ? reward.startsWith("$")
      ? reward
      : "$" + reward
    : "";
  // Render the cleaned actual Reddit post title under the brand, so the
  // card communicates what the post is really about — independent of
  // whether the brand picker matched.
  const ptEl = node.querySelector(".post-title");
  const titleText = (o.post_title || "").trim();
  if (titleText && titleText.toLowerCase() !== (o.company || "").toLowerCase()) {
    ptEl.textContent = titleText;
  } else {
    ptEl.textContent = "";
  }

  const badges = node.querySelector(".badges");
  if (o.type) badges.appendChild(mkBadge(o.type, "type"));
  if (o.urgent) badges.appendChild(mkBadge("urgent", "urgent"));
  if ((o.gem || 0) >= 80) badges.appendChild(mkBadge("gem", "gem"));
  if ((o.launch_status || "").includes("first_seen"))
    badges.appendChild(mkBadge("fresh launch", "fresh"));
  if (o.direct_deposit_required) badges.appendChild(mkBadge("DD req", "dd"));
  if (o.ssn_required) badges.appendChild(mkBadge("SSN", "ssn"));
  if (o.deposit_required) badges.appendChild(mkBadge("$ deposit", "deposit"));

  node.querySelector(".s-opp").textContent = fmtScore(o.opportunity);
  node.querySelector(".s-trust").textContent = fmtScore(o.trust);
  node.querySelector(".s-gem").textContent = fmtScore(o.gem);
  node.querySelector(".s-scam").textContent = fmtScore(o.scam);
  node.querySelector(".s-fm").textContent = fmtScore(o.first_mover);
  node.querySelector(".s-mentions").textContent = o.mentions || 0;

  node.querySelector(".summary").textContent = o.ai_summary || "(no summary)";

  const linksEl = node.querySelector(".links");
  const seenDomains = new Set();
  for (const u of (o.reddit_links || []).slice(0, 2)) {
    linksEl.appendChild(mkLink(u, "reddit", "reddit"));
  }
  for (const u of o.referral_links || []) {
    const d = domainOf(u);
    if (!d || seenDomains.has(d)) continue;
    seenDomains.add(d);
    linksEl.appendChild(mkLink(u, "ref", d));
    if (seenDomains.size >= 4) break;
  }

  const dg = node.querySelector(".detail-grid");
  const rows = [
    ["Type", o.type],
    ["Reward", o.reward],
    ["Risk", fmtScore(o.risk)],
    ["Engagement", fmtScore(o.engagement)],
    ["Saturation", fmtScore(o.saturation)],
    ["Trend", o.trend],
    ["Launch", o.launch_status],
    ["Profit window", o.profit_window],
    [
      "Eligible states",
      o.eligible_states && o.eligible_states.length
        ? o.eligible_states.join(", ")
        : "",
    ],
    [
      "Excluded states",
      o.excluded_states && o.excluded_states.length
        ? o.excluded_states.join(", ")
        : "",
    ],
    [
      "Requirements",
      o.requirements && o.requirements.length ? o.requirements.join(", ") : "",
    ],
    ["Domain", o.primary_domain],
    ["Trust reasoning", o.trust_reasoning],
    ["Strategy", o.strategy],
    ["First seen", o.first_seen ? new Date(o.first_seen).toLocaleString() : ""],
    [
      "Latest seen",
      o.latest_seen ? new Date(o.latest_seen).toLocaleString() : "",
    ],
    [
      "Reddit threads",
      (o.reddit_links || []).join("\n") || "",
    ],
    [
      "Referral links",
      (o.referral_links || []).join("\n") || "",
    ],
  ];
  for (const [k, v] of rows) {
    if (!v) continue;
    const kEl = document.createElement("span");
    kEl.className = "k";
    kEl.textContent = k;
    const vEl = document.createElement("span");
    vEl.className = "v";
    vEl.textContent = String(v);
    if (String(v).startsWith("http")) {
      vEl.innerHTML = String(v)
        .split("\n")
        .map(
          (u) =>
            '<a href="' +
            u.replace(/"/g, "&quot;") +
            '" target="_blank" rel="noopener">' +
            u +
            "</a>",
        )
        .join("<br>");
    }
    dg.appendChild(kEl);
    dg.appendChild(vEl);
  }

  node.querySelector(".when").textContent = relTime(o.latest_seen_ts);
  const subs = (o.subreddits || []).slice(0, 3).join(" · ");
  node.querySelector(".subs").textContent = subs ? "r/" + subs.replace(/ · /g, " · r/") : "";

  return node;
}

function mkBadge(text, kind) {
  const b = document.createElement("span");
  b.className = "badge " + (kind || "");
  b.textContent = text;
  return b;
}

function mkLink(href, kind, label) {
  const a = document.createElement("a");
  a.href = href;
  a.target = "_blank";
  a.rel = "noopener";
  a.className = kind;
  a.textContent = label;
  a.title = href;
  return a;
}

// ---------------- wiring ----------------
function readControls() {
  state.filters.q = el.q.value;
  state.filters.type = el.type.value;
  state.filters.sort = el.sort.value;
  state.filters.minReward = Number(el.minReward.value) || 0;
  state.filters.minTrust = Number(el.minTrust.value) || 0;
  state.filters.maxScam = Number(el.maxScam.value) || 100;
  state.filters.urgentOnly = el.urgentOnly.checked;
  state.filters.hideSaturated = el.hideSaturated.checked;
  state.filters.hideScammy = el.hideScammy.checked;
  syncChipActive();
}

const onChange = debounce(() => {
  readControls();
  render();
}, 80);

for (const node of [
  el.q,
  el.type,
  el.sort,
  el.minReward,
  el.minTrust,
  el.maxScam,
]) {
  node.addEventListener("input", onChange);
  node.addEventListener("change", onChange);
}
for (const node of [el.urgentOnly, el.hideSaturated, el.hideScammy]) {
  node.addEventListener("change", onChange);
}
el.reset.addEventListener("click", () => {
  el.q.value = "";
  el.type.value = "";
  el.sort.value = "latest_seen_ts";
  el.minReward.value = 0;
  el.minTrust.value = 0;
  el.maxScam.value = 100;
  el.urgentOnly.checked = false;
  el.hideSaturated.checked = false;
  el.hideScammy.checked = true;
  onChange();
});

el.repoLink.href = repoLinkFromLocation();

// initial + interval
el.grid.innerHTML = '<div class="empty"><div class="spinner"></div>Loading offers…</div>';
loadData();
setInterval(loadData, REFRESH_MS);

// tick the "updated X min ago" label every 10s without reloading
setInterval(() => {
  if (state.data) {
    el.updated.textContent = relTime(state.data.generated_at_ts || state.data.generated_at);
  }
}, 10_000);
