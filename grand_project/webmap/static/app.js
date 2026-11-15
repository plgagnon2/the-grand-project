// The atlas web map: MapLibre on the exported tiles, plus search, icon highlight and directions.
// atlas.json (written by grand_project.webmap) holds the zoom range, bounds and the map nodes / paths / landmarks /
// bookmarks for search and routing; the map itself draws from the raster and vector tiles.
"use strict";

const BASE = location.href.replace(/[?#].*$/, "").replace(/[^/]*$/, ""); // tile URLs must be absolute
const EMPTY = { type: "FeatureCollection", features: [] };
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

const S = { info: null, map: null, adj: [], edgeLine: new Map(), player: null, marker: null, picking: false, popup: null };

// localStorage can be missing or throw (private windows, some file setups): only a convenience here
const store = {
  get(k) { try { return JSON.parse(localStorage.getItem(k)); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* not kept */ } },
};

fetch("atlas.json")
  .then((r) => r.json())
  .then(init)
  .catch((e) => { document.body.innerHTML = `<p style="padding:20px">Could not load the atlas: ${esc(e)}</p>`; });

function init(info) {
  S.info = info;
  document.title = `${info.title} — atlas web map`;
  $("title").textContent = info.title;
  $("stats").textContent = `${info.nodes.length} maps · ${info.edges.length} paths · ${info.landmarks.length} landmarks · v${info.version}`;
  buildGraph();

  const [[w, s], [e, n]] = info.bounds;
  const padX = (e - w) * 0.25, padY = (n - s) * 0.25;
  S.map = new maplibregl.Map({
    container: "map",
    style: mapStyle(info),
    bounds: info.bounds,
    fitBoundsOptions: { padding: 20 },
    maxBounds: [[w - padX, s - padY], [e + padX, n + padY]],
    maxZoom: info.maxzoom,
    renderWorldCopies: false,
    attributionControl: false,
    dragRotate: false,
    pitchWithRotate: false,
  });
  S.map.touchZoomRotate.disableRotation();
  S.map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
  S.map.addControl(new FitControl(), "top-right");
  S.map.addControl(new maplibregl.FullscreenControl(), "top-right");

  S.map.on("load", () => {
    setupUi();
    const saved = store.get(storeKey("player"));
    if (saved != null && info.nodes[saved]) setPlayer(saved, false);
  });
  for (const layer of ["maps", "landmarks", "bookmarks"]) {
    S.map.on("mouseenter", layer, () => { if (!S.picking) S.map.getCanvas().style.cursor = "pointer"; });
    S.map.on("mouseleave", layer, () => { if (!S.picking) S.map.getCanvas().style.cursor = ""; });
  }
  S.map.on("click", onMapClick);
}

function storeKey(k) { return `grand-webmap:${S.info.title}:${k}`; }

function mapStyle(info) {
  const lineWidth = ["interpolate", ["linear"], ["zoom"], info.zmax - 5, 1, info.zmax, 3, info.maxzoom, 6];
  const nodeRadius = ["interpolate", ["linear"], ["zoom"], info.zmax - 5, 2.5, info.zmax, 7, info.maxzoom, 14];
  const ring = (extra) => ["interpolate", ["linear"], ["zoom"], info.zmax - 5, 4 + extra, info.zmax, 11 + extra, info.maxzoom, 20 + extra];
  const tiles = (path) => [BASE + path];
  return {
    version: 8,
    sources: {
      terrain: { type: "raster", tiles: tiles("terrain/{z}/{x}/{y}.jpg"), tileSize: 256, minzoom: 0, maxzoom: info.zmax, bounds: info.bounds.flat() },
      atlas: { type: "vector", tiles: tiles("vector/{z}/{x}/{y}.pbf"), minzoom: 0, maxzoom: info.zmax, bounds: info.bounds.flat() },
      route: { type: "geojson", data: EMPTY },
      routeNodes: { type: "geojson", data: EMPTY },
    },
    layers: [
      { id: "background", type: "background", paint: { "background-color": "#000000" } },
      { id: "terrain", type: "raster", source: "terrain", paint: { "raster-fade-duration": 100 } },
      {
        id: "paths", type: "line", source: "atlas", "source-layer": "paths",
        layout: { "line-cap": "round", "line-join": "round" },
        paint: {
          "line-color": ["case", ["get", "abyss"], "#ff50e6", ["get", "strong"], "#28dcff", "#ffb900"],
          "line-width": lineWidth, "line-opacity": 0.85,
        },
      },
      { id: "route-casing", type: "line", source: "route", layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-color": "#000000", "line-width": ["*", 2.2, lineWidth], "line-opacity": 0.7 } },
      { id: "route", type: "line", source: "route", layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-color": "#7cff6b", "line-width": ["*", 1.4, lineWidth] } },
      { id: "landmarks", type: "circle", source: "atlas", "source-layer": "landmarks",
        paint: { "circle-radius": ring(6), "circle-color": "rgba(0,0,0,0)", "circle-stroke-color": "#46f064",
          "circle-stroke-width": 2.5 } },
      { id: "maps", type: "circle", source: "atlas", "source-layer": "maps",
        paint: { "circle-radius": nodeRadius, "circle-color": ["get", "fill"], "circle-stroke-color": ["get", "ring"],
          "circle-stroke-width": ["interpolate", ["linear"], ["zoom"], info.zmax - 5, 1, info.zmax, 2.5] } },
      { id: "route-nodes", type: "circle", source: "routeNodes",
        paint: { "circle-radius": ring(-2), "circle-color": "rgba(0,0,0,0)", "circle-stroke-color": "#7cff6b",
          "circle-stroke-width": 3 } },
      { id: "highlight", type: "circle", source: "atlas", "source-layer": "maps", filter: ["==", 1, 0],
        paint: { "circle-radius": ring(2), "circle-color": "rgba(0,0,0,0)", "circle-stroke-color": "#fff200",
          "circle-stroke-width": 3 } },
      { id: "selected", type: "circle", source: "atlas", "source-layer": "maps", filter: ["==", ["get", "id"], -1],
        paint: { "circle-radius": ring(5), "circle-color": "rgba(255,255,255,0.12)", "circle-stroke-color": "#ffffff",
          "circle-stroke-width": 3 } },
      { id: "bookmarks", type: "circle", source: "atlas", "source-layer": "bookmarks",
        paint: { "circle-radius": ["interpolate", ["linear"], ["zoom"], info.zmax - 5, 3, info.maxzoom, 9],
          "circle-color": "#ffd54a", "circle-stroke-color": "#000000", "circle-stroke-width": 1.5 } },
    ],
  };
}

class FitControl {
  onAdd(map) {
    this.el = document.createElement("div");
    this.el.className = "maplibregl-ctrl maplibregl-ctrl-group";
    const b = document.createElement("button");
    b.type = "button";
    b.title = "Fit the whole atlas";
    b.textContent = "⤢";
    b.style.fontSize = "16px";
    b.onclick = () => map.fitBounds(S.info.bounds, { padding: 20 });
    this.el.appendChild(b);
    return this.el;
  }
  onRemove() { this.el.remove(); }
}

// ------------------------------------------------------------------ graph (map nodes linked by paths)
function buildGraph() {
  const { nodes, edges } = S.info;
  S.adj = nodes.map(() => []);
  for (const e of edges) {
    const [a, b] = [e.a, e.b];
    if (!S.adj[a] || !S.adj[b] || a === b) continue;
    S.adj[a].push(b);
    S.adj[b].push(a);
    if (e.l) S.edgeLine.set(`${a}-${b}`, e.l);
  }
}

function dist(a, b) {
  const [p, q] = [S.info.nodes[a].c, S.info.nodes[b].c];
  return Math.hypot(p[0] - q[0], p[1] - q[1]);
}

// Dijkstra; every map run costs 1 (the route with fewest maps), on-screen length only breaks ties.
// done(id) ends the search at the first node it accepts (a destination, or the nearest with an icon).
function shortest(from, done) {
  const n = S.info.nodes.length;
  const cost = new Float64Array(n).fill(Infinity);
  const prev = new Int32Array(n).fill(-1);
  const heap = [[0, from]];
  cost[from] = 0;
  while (heap.length) {
    let bi = 0;
    for (let i = 1; i < heap.length; i++) if (heap[i][0] < heap[bi][0]) bi = i; // small graphs: a list is enough
    const [c, u] = heap.splice(bi, 1)[0];
    if (c > cost[u]) continue;
    if (u !== from && done(u)) {
      const path = [];
      for (let v = u; v !== -1; v = prev[v]) path.push(v);
      return path.reverse();
    }
    for (const v of S.adj[u]) {
      const nc = c + 1 + 1e-6 * dist(u, v);
      if (nc < cost[v]) { cost[v] = nc; prev[v] = u; heap.push([nc, v]); }
    }
  }
  return null;
}

// ------------------------------------------------------------------ panel
function setupUi() {
  const { info } = S;
  const names = Object.keys(info.icons).sort((a, b) => info.icons[a].label.localeCompare(info.icons[b].label));
  for (const sel of [$("highlight"), $("nearest")]) {
    for (const name of names) {
      const o = document.createElement("option");
      o.value = name;
      o.textContent = info.icons[name].label;
      sel.appendChild(o);
    }
  }
  $("highlight").onchange = (ev) => highlight(ev.target.value);
  $("nearest").onchange = (ev) => { if (ev.target.value) routeToNearest(ev.target.value); };
  $("search").oninput = (ev) => search(ev.target.value);
  $("set-player").onclick = () => startPicking();
  $("clear-route").onclick = () => clearRoute();
  document.addEventListener("keydown", (ev) => {
    if (ev.key === "/" && document.activeElement !== $("search")) { ev.preventDefault(); $("search").focus(); }
    if (ev.key === "Escape") { stopPicking(); if (S.popup) S.popup.remove(); }
  });

  const layers = { Terrain: ["terrain"], Paths: ["paths"], Maps: ["maps", "selected", "highlight"],
    Landmarks: ["landmarks"], Bookmarks: ["bookmarks"], Route: ["route", "route-casing", "route-nodes"] };
  for (const [label, ids] of Object.entries(layers)) {
    const l = document.createElement("label");
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = true;
    cb.onchange = () => ids.forEach((id) => S.map.setLayoutProperty(id, "visibility", cb.checked ? "visible" : "none"));
    l.append(cb, label);
    $("layers").appendChild(l);
  }
}

function iconChips(icons) {
  return icons.map((n) => {
    const ic = S.info.icons[n] || { label: n, colour: "#fff" };
    return `<span class="chip" style="background:${ic.colour}">${esc(ic.label)}</span>`;
  }).join("");
}

function nodeTitle(id) {
  const nd = S.info.nodes[id];
  const lm = landmarkAt(id);
  return lm ? `${lm} (map #${id})` : nd.tower ? `Tower (map #${id})` : `Map #${id}`;
}

// a landmark (city, hall, tower...) stands next to its map: the closest map node within a short reach
function landmarkAt(id) {
  const c = S.info.nodes[id].c;
  let best = null, bd = Infinity;
  for (const lm of S.info.landmarks) {
    const d = Math.hypot(lm.c[0] - c[0], lm.c[1] - c[1]);
    if (d < bd) { bd = d; best = lm; }
  }
  if (!best || nearestNode(best.c) !== id) return null;
  return best.kind;
}

function nearestNode(c) {
  let best = -1, bd = Infinity;
  S.info.nodes.forEach((nd, i) => {
    const d = Math.hypot(nd.c[0] - c[0], nd.c[1] - c[1]);
    if (d < bd) { bd = d; best = i; }
  });
  return best;
}

function search(text) {
  const ul = $("results");
  ul.innerHTML = "";
  const q = text.trim().toLowerCase();
  if (!q) return;
  const { info } = S;
  const hits = [];
  const num = q.match(/^#?(\d+)$/);
  if (num && info.nodes[+num[1]]) hits.push({ text: nodeTitle(+num[1]), c: info.nodes[+num[1]].c, node: +num[1] });
  for (const bm of info.bookmarks) {
    if (`${bm.name} ${bm.group} ${bm.note}`.toLowerCase().includes(q)) hits.push({ text: `★ ${bm.name}`, c: bm.c, node: nearestNode(bm.c) });
  }
  for (const lm of info.landmarks) {
    if (lm.kind.toLowerCase().includes(q)) hits.push({ text: lm.kind, c: lm.c, node: nearestNode(lm.c) });
  }
  const iconHit = Object.entries(info.icons).filter(([n, ic]) => n.toLowerCase().includes(q) || ic.label.toLowerCase().includes(q)).map(([n]) => n);
  if (iconHit.length) {
    info.nodes.forEach((nd, i) => {
      const found = nd.icons.filter((n) => iconHit.includes(n));
      if (found.length) hits.push({ text: `${nodeTitle(i)} · ${found.map((n) => info.icons[n].label).join(", ")}`, c: nd.c, node: i });
    });
  }
  if (!hits.length) { ul.innerHTML = '<li class="muted">Nothing found</li>'; return; }
  for (const h of hits.slice(0, 200)) {
    const li = document.createElement("li");
    li.textContent = h.text;
    li.onclick = () => { flyTo(h.c); if (h.node >= 0) select(h.node, true); };
    ul.appendChild(li);
  }
  if (hits.length > 200) ul.insertAdjacentHTML("beforeend", `<li class="muted">${hits.length - 200} more: narrow the search</li>`);
}

function highlight(name) {
  const f = name ? ["in", `|${name}|`, ["get", "icons"]] : ["==", 1, 0];
  S.map.setFilter("highlight", f);
  const n = name ? S.info.nodes.filter((nd) => nd.icons.includes(name)).length : 0;
  $("highlight-count").textContent = name ? `${n} map${n === 1 ? "" : "s"}` : "";
}

function flyTo(c, zoom) {
  S.map.flyTo({ center: c, zoom: Math.max(S.map.getZoom(), zoom ?? S.info.zmax - 1), speed: 1.6 });
}

// ------------------------------------------------------------------ selection and popups
function onMapClick(ev) {
  const hit = S.map.queryRenderedFeatures(ev.point, { layers: ["maps", "bookmarks", "landmarks"] });
  if (S.picking) {
    const m = hit.find((f) => f.layer.id === "maps");
    setPlayer(m ? m.properties.id : nearestNode([ev.lngLat.lng, ev.lngLat.lat]), true);
    stopPicking();
    return;
  }
  const bm = hit.find((f) => f.layer.id === "bookmarks");
  const m = hit.find((f) => f.layer.id === "maps");
  const lm = hit.find((f) => f.layer.id === "landmarks");
  if (m) select(m.properties.id, false);
  else if (bm) popupAt(ev.lngLat, `<div class="popup"><h3>★ ${esc(bm.properties.name)}</h3></div>`);
  else if (lm) select(nearestNode([ev.lngLat.lng, ev.lngLat.lat]), false);
  else { S.map.setFilter("selected", ["==", ["get", "id"], -1]); if (S.popup) S.popup.remove(); }
}

function select(id, fromList) {
  const nd = S.info.nodes[id];
  S.map.setFilter("selected", ["==", ["get", "id"], id]);
  const seen = nd.seen ? `seen in ${nd.seen} screenshot${nd.seen === 1 ? "" : "s"} · ` : "";
  const html = `<div class="popup"><h3>${esc(nodeTitle(id))}</h3>
    <div>${iconChips(nd.icons) || '<span class="muted">no icon</span>'}</div>
    <div class="muted">${seen}${esc(nd.status)}</div>
    <div class="row"><button data-act="here">I'm here</button><button data-act="route">Route here</button></div></div>`;
  const pop = popupAt(nd.c, html);
  pop.getElement().querySelector('[data-act="here"]').onclick = () => { setPlayer(id, true); pop.remove(); };
  pop.getElement().querySelector('[data-act="route"]').onclick = () => { routeTo(id); pop.remove(); };
  if (fromList) flyTo(nd.c);
}

function popupAt(c, html) {
  if (S.popup) S.popup.remove();
  S.popup = new maplibregl.Popup({ maxWidth: "300px", offset: 14 }).setLngLat(c).setHTML(html).addTo(S.map);
  return S.popup;
}

// ------------------------------------------------------------------ directions
function startPicking() {
  S.picking = true;
  $("set-player").classList.add("active");
  $("pick-hint").hidden = false;
  S.map.getCanvas().style.cursor = "crosshair";
}

function stopPicking() {
  S.picking = false;
  $("set-player").classList.remove("active");
  $("pick-hint").hidden = true;
  S.map.getCanvas().style.cursor = "";
}

function setPlayer(id, save) {
  S.player = id;
  if (!S.marker) {
    const el = document.createElement("div");
    el.className = "player-marker";
    el.title = "You are here";
    S.marker = new maplibregl.Marker({ element: el });
  }
  S.marker.setLngLat(S.info.nodes[id].c).addTo(S.map);
  $("player").innerHTML = `You are at <b>${esc(nodeTitle(id))}</b>`;
  if (save) store.set(storeKey("player"), id);
}

function needPlayer() {
  if (S.player != null) return true;
  $("route-info").textContent = "Set your position first.";
  startPicking();
  return false;
}

function routeTo(id) {
  if (!needPlayer()) return;
  if (id === S.player) { showRoute([id], "You are already there."); return; }
  const path = shortest(S.player, (u) => u === id);
  showRoute(path, path ? null : `No path from your map to ${nodeTitle(id)} in this atlas.`);
}

function routeToNearest(icon) {
  if (!needPlayer()) return;
  const label = S.info.icons[icon].label;
  const path = shortest(S.player, (u) => S.info.nodes[u].icons.includes(icon));
  showRoute(path, path ? null : `No reachable map with ${label}.`);
}

function showRoute(path, message) {
  const info = $("route-info"), ol = $("route-steps");
  ol.innerHTML = "";
  if (!path) { info.textContent = message; S.map.getSource("route").setData(EMPTY); S.map.getSource("routeNodes").setData(EMPTY); return; }
  const coords = [];
  for (let i = 0; i + 1 < path.length; i++) {
    const [a, b] = [path[i], path[i + 1]];
    const fwd = S.edgeLine.get(`${a}-${b}`), back = S.edgeLine.get(`${b}-${a}`);
    const seg = fwd || (back ? [...back].reverse() : [S.info.nodes[a].c, S.info.nodes[b].c]);
    coords.push(...(coords.length ? seg.slice(1) : seg));
  }
  S.map.getSource("route").setData(coords.length > 1
    ? { type: "Feature", geometry: { type: "LineString", coordinates: coords }, properties: {} } : EMPTY);
  S.map.getSource("routeNodes").setData({ type: "FeatureCollection", features: path.slice(1).map((id) => (
    { type: "Feature", geometry: { type: "Point", coordinates: S.info.nodes[id].c }, properties: { id } })) });
  const runs = path.length - 1;
  info.textContent = message || `${runs} map${runs === 1 ? "" : "s"} to run`;
  path.slice(1).forEach((id) => {
    const li = document.createElement("li");
    li.innerHTML = `${esc(nodeTitle(id))} ${iconChips(S.info.nodes[id].icons)}`;
    li.onclick = () => select(id, true);
    ol.appendChild(li);
  });
  if (coords.length > 1) {
    const b = coords.reduce((bb, c) => bb.extend(c), new maplibregl.LngLatBounds(coords[0], coords[0]));
    S.map.fitBounds(b, { padding: 80, maxZoom: S.info.zmax - 1 });
  }
}

function clearRoute() {
  S.map.getSource("route").setData(EMPTY);
  S.map.getSource("routeNodes").setData(EMPTY);
  $("route-info").textContent = "";
  $("route-steps").innerHTML = "";
  $("nearest").value = "";
}
