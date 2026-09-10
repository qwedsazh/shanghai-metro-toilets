'use strict';

const REPO_URL = 'https://github.com/qwedsazh/shanghai-metro-toilets';

const LINE_COLORS = {
  '1': '#e3002b', '2': '#8cc220', '3': '#fcd600', '4': '#461d84',
  '5': '#944d9a', '6': '#d40068', '7': '#ed6f00', '8': '#0094d8',
  '9': '#87caed', '10': '#c6afd4', '11': '#871c2b', '12': '#007a60',
  '13': '#e999c0', '14': '#616020', '15': '#c8b38e', '16': '#98d1c0',
  '17': '#bb796f', '18': '#c09453', '41': '#b5b6b6', '51': '#9e9e9e'
};
// 浅色底线路用深色文字，其余白字
const LIGHT_BG_LINES = new Set(['3', '9', '13', '15', '16', '41', '51']);

const ZONE_LABELS = {
  inside: '费区内',
  outside: '费区外',
  station_outside: '车站外',
  both: '费区内外',
  unknown: '未注明'
};

const NEARBY_LIMIT = 15;
const POS_CACHE_KEY = 'smt_last_pos';

const $ = (sel) => document.querySelector(sel);

const state = {
  data: null,
  stations: [],
  byName: new Map(),
  pos: null,          // { lat, lng } WGS84
  filter: 'all',      // all | outside | inside
  query: '',
  searchScope: 'auto', // auto | line | all（线路 tab 搜索范围，auto=线路内优先、无则全局）
  tab: 'nearby',      // nearby | lines | map
  line: null,         // 线路浏览当前选中的线路
  map: null,
  userMarker: null,
  leafletPromise: null
};

/* ---------------- 工具 ---------------- */

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]));
}

// haversine 距离（米），经纬度均为 WGS84
function haversine(lat1, lng1, lat2, lng2) {
  const R = 6371000;
  const rad = (d) => d * Math.PI / 180;
  const dLat = rad(lat2 - lat1);
  const dLng = rad(lng2 - lng1);
  const a = Math.sin(dLat / 2) ** 2 +
    Math.cos(rad(lat1)) * Math.cos(rad(lat2)) * Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(a));
}

function formatDistance(m) {
  if (m == null) return '';
  return m < 1000 ? `${Math.round(m)} m` : `${(m / 1000).toFixed(1)} km`;
}

function lineName(id) {
  const alias = (state.data && state.data.meta && state.data.meta.line_alias) || {};
  return alias[id] || `${id}号线`;
}

function lineBadgeHtml(id) {
  const bg = LINE_COLORS[id] || '#666666';
  const fg = LIGHT_BG_LINES.has(id) ? '#222222' : '#ffffff';
  return `<span class="line-badge" style="background:${bg};color:${fg}">${escapeHtml(lineName(id))}</span>`;
}

function toiletMatchesFilter(t) {
  if (state.filter === 'outside') return ['outside', 'station_outside', 'both'].includes(t.zone);
  if (state.filter === 'inside') return ['inside', 'both'].includes(t.zone);
  return true;
}

// 今天处于 [plan_close_date, plan_open_date] 封闭区间 → 改造中
function isRenovating(t) {
  if (!t.plan_close_date || !t.plan_open_date) return false;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const close = new Date(`${t.plan_close_date}T00:00:00`);
  const open = new Date(`${t.plan_open_date}T00:00:00`);
  return close <= today && today <= open;
}

function toiletItemHtml(t) {
  const zone = Object.prototype.hasOwnProperty.call(ZONE_LABELS, t.zone) ? t.zone : 'unknown';
  const lineBg = LINE_COLORS[t.line] || '#999999';
  const lineFg = LIGHT_BG_LINES.has(t.line) ? '#222222' : '#ffffff';
  return `<li class="toilet-item">
    <span class="zone-badge zone-${zone}">${ZONE_LABELS[zone]}</span>
    <span class="toilet-line" style="background:${lineBg};color:${lineFg}">${escapeHtml(lineName(t.line))}</span>
    ${t.accessible ? '<span class="accessible" title="无障碍厕所">♿</span>' : ''}
    <span class="toilet-loc">${escapeHtml(t.location || '')}</span>
    ${isRenovating(t) ? '<span class="renovating">改造中</span>' : ''}
    ${t.zone_conflict ? '<span class="warn" title="官方图标与描述不一致，以描述为准">⚠️</span>' : ''}
  </li>`;
}

function stationMatchesQuery(s) {
  if (!state.query) return true;
  const q = state.query.toLowerCase();
  return s.name.includes(state.query) ||
    (s.pinyin || '').toLowerCase().includes(q) ||
    (s.name_en || '').toLowerCase().includes(q);
}

function stationDistance(s) {
  if (!state.pos) return null;
  const [lng, lat] = s.coords.wgs84;
  return haversine(state.pos.lat, state.pos.lng, lat, lng);
}

function stationCardHtml(s, distM) {
  const toilets = s.toilets.filter(toiletMatchesFilter);
  return `<article class="station-card" data-name="${escapeHtml(s.name)}">
    <div class="station-head">
      <h3>${escapeHtml(s.name)}</h3>
      ${distM != null ? `<span class="distance">${formatDistance(distM)}</span>` : ''}
    </div>
    <div class="line-badges">${s.lines.map(lineBadgeHtml).join('')}</div>
    <ul class="toilet-list">${toilets.map(toiletItemHtml).join('')}</ul>
  </article>`;
}

function findStation(name) {
  return state.byName.get(name);
}

/* ---------------- 附近模式 ---------------- */

function setLocatePanel(mode, msg) {
  const panel = $('#locate-panel');
  if (mode === 'idle') {
    panel.innerHTML = `<button id="btn-locate" class="btn btn-big">📍 定位找最近</button>
      <p class="locate-hint">授权定位后，按距离列出附近车站的厕所</p>`;
  } else if (mode === 'loading') {
    panel.innerHTML = `<button class="btn btn-big" disabled>📍 定位中…</button>`;
  } else if (mode === 'error') {
    panel.innerHTML = `<p class="locate-error">${escapeHtml(msg)}</p>
      <button id="btn-locate" class="btn btn-big">重试</button>`;
  } else if (mode === 'done') {
    panel.innerHTML = `<div class="locate-done">
      <span>📍 已定位，显示最近 ${NEARBY_LIMIT} 站</span>
      <button id="btn-locate" class="btn btn-small">重新定位</button>
    </div>`;
  }
  const btn = $('#btn-locate');
  if (btn) btn.addEventListener('click', requestLocation);
}

function requestLocation() {
  if (!navigator.geolocation) {
    setLocatePanel('error', '当前浏览器不支持定位，可改用搜索或线路浏览');
    return;
  }
  setLocatePanel('loading');
  navigator.geolocation.getCurrentPosition(
    (p) => {
      state.pos = { lat: p.coords.latitude, lng: p.coords.longitude };
      try {
        localStorage.setItem(POS_CACHE_KEY, JSON.stringify({ ...state.pos, ts: Date.now() }));
      } catch (e) { /* 隐私模式等场景下忽略 */ }
      setLocatePanel('done');
      renderNearby();
      updateUserMarker();
    },
    (err) => {
      const msg = err.code === 1
        ? '定位未授权：请在浏览器/系统设置中允许定位后重试'
        : '定位失败，请检查网络或稍候重试';
      setLocatePanel('error', msg);
    },
    { enableHighAccuracy: false, timeout: 10000, maximumAge: 300000 }
  );
}

function renderNearby() {
  const list = $('#station-list');
  const panel = $('#locate-panel');

  // 搜索模式：不依赖定位，全站过滤
  if (state.query) {
    panel.style.display = 'none';
    let matches = state.stations.filter(
      (s) => stationMatchesQuery(s) && s.toilets.some(toiletMatchesFilter)
    );
    if (state.pos) {
      matches = matches
        .map((s) => [s, stationDistance(s)])
        .sort((a, b) => a[1] - b[1]);
    } else {
      matches = matches.map((s) => [s, null]);
    }
    list.innerHTML = matches.length
      ? matches.map(([s, d]) => stationCardHtml(s, d)).join('')
      : '<p class="empty-msg">未找到匹配的车站</p>';
    return;
  }

  panel.style.display = '';
  if (!state.pos) {
    list.innerHTML = '<p class="empty-msg">点击上方按钮定位，或直接用搜索 / 线路标签页浏览</p>';
    return;
  }

  const nearest = state.stations
    .filter((s) => s.toilets.some(toiletMatchesFilter))
    .map((s) => [s, stationDistance(s)])
    .sort((a, b) => a[1] - b[1])
    .slice(0, NEARBY_LIMIT);

  list.innerHTML = nearest.length
    ? nearest.map(([s, d]) => stationCardHtml(s, d)).join('')
    : '<p class="empty-msg">当前筛选条件下没有附近车站</p>';
}

/* ---------------- 线路浏览 ---------------- */

function renderLineChips() {
  const set = new Set();
  state.stations.forEach((s) => s.lines.forEach((l) => set.add(l)));
  const lines = [...set].sort((a, b) => parseInt(a, 10) - parseInt(b, 10));
  if (!state.line || !set.has(state.line)) state.line = lines[0];
  $('#line-chips').innerHTML = lines.map((l) => {
    const bg = LINE_COLORS[l] || '#666666';
    const active = l === state.line;
    const style = active
      ? `background:${bg};border-color:${bg};color:${LIGHT_BG_LINES.has(l) ? '#222222' : '#ffffff'}`
      : `color:${bg};border-color:${bg}`;
    return `<button class="chip line-chip${active ? ' active' : ''}" data-line="${l}" style="${style}">${escapeHtml(lineName(l))}</button>`;
  }).join('');
  updateChipFades();
}

function updateChipFades() {
  const el = $('#line-chips');
  if (!el) return;
  el.classList.toggle('can-scroll-left', el.scrollLeft > 1);
  el.classList.toggle('can-scroll-right', el.scrollLeft < el.scrollWidth - el.clientWidth - 1);
}

function lineStationOrder(s, line) {
  const prefix = line.padStart(2, '0');
  const sid = (s.stat_ids || []).find((id) => id.slice(0, 2) === prefix);
  const n = sid ? parseInt(sid, 10) : NaN;
  return Number.isNaN(n) ? 9999 : n;
}

function renderLineStations() {
  const matches = (s) => stationMatchesQuery(s) && s.toilets.some(toiletMatchesFilter);
  const inLine = state.stations
    .filter((s) => s.lines.includes(state.line) && matches(s))
    .sort((a, b) => lineStationOrder(a, state.line) - lineStationOrder(b, state.line));
  const hintEl = $('#line-search-hint');
  const listEl = $('#line-station-list');

  // 无搜索词：常规线路浏览
  if (!state.query) {
    hintEl.innerHTML = '';
    listEl.innerHTML = inLine.length
      ? inLine.map((s) => stationCardHtml(s, stationDistance(s))).join('')
      : '<p class="empty-msg">该线路在当前筛选条件下没有匹配车站</p>';
    return;
  }

  // 有搜索词：线路内优先；线路内无匹配则自动扩到全部线路，提示栏明示当前范围
  const all = state.stations.filter(matches);
  let scope = state.searchScope;
  if (scope === 'auto') scope = inLine.length ? 'line' : 'all';

  const lname = lineName(state.line);
  let hint = '';
  if (scope === 'line') {
    if (all.length > inLine.length) {
      hint = `<span>仅显示${lname}内匹配（${inLine.length} 个）</span>
        <button type="button" data-scope="all">搜索全部线路（${all.length} 个）→</button>`;
    }
  } else if (inLine.length) {
    hint = `<span>全部线路匹配（${all.length} 个）</span>
      <button type="button" data-scope="line">仅看${lname}（${inLine.length} 个）</button>`;
  } else {
    hint = `<span>${lname}内无匹配，已搜索全部线路</span>
      <button type="button" data-scope="line">仅看${lname}</button>`;
  }
  hintEl.innerHTML = hint;

  const list = scope === 'line' ? inLine : all;
  const q = escapeHtml(state.query);
  listEl.innerHTML = list.length
    ? list.map((s) => stationCardHtml(s, stationDistance(s))).join('')
    : `<p class="empty-msg">${scope === 'line' ? `${lname}内` : '全部线路中'}没有匹配「${q}」的车站</p>`;
}

/* ---------------- 车站详情 ---------------- */

function openStationModal(s) {
  const [gcjLng, gcjLat] = s.coords.gcj02;
  const navUrl = `https://uri.amap.com/marker?position=${gcjLng},${gcjLat}&name=${encodeURIComponent(s.name + '地铁站厕所')}`;
  const reportUrl = `${REPO_URL}/issues/new?template=toilet-report.yml`;
  const dist = stationDistance(s);
  $('#modal-content').innerHTML = `
    <div class="modal-head">
      <h2 id="modal-title">${escapeHtml(s.name)}</h2>
      <button class="modal-close" id="modal-close" aria-label="关闭">✕</button>
    </div>
    <div class="line-badges">
      ${s.lines.map(lineBadgeHtml).join('')}
      ${dist != null ? `<span class="distance">${formatDistance(dist)}</span>` : ''}
    </div>
    <ul class="toilet-list">${s.toilets.map(toiletItemHtml).join('')}</ul>
    <div class="modal-actions">
      <a class="btn" href="${navUrl}" target="_blank" rel="noopener">🧭 导航前往</a>
      <a class="btn btn-ghost" href="${reportUrl}" target="_blank" rel="noopener">数据有误？上报</a>
    </div>`;
  $('#modal-close').addEventListener('click', closeModal);
  $('#station-modal').hidden = false;
  document.body.classList.add('modal-open');
}

function closeModal() {
  $('#station-modal').hidden = true;
  document.body.classList.remove('modal-open');
}

/* ---------------- 地图（Leaflet 懒加载） ---------------- */

function loadLeaflet() {
  if (window.L) return Promise.resolve();
  if (state.leafletPromise) return state.leafletPromise;
  state.leafletPromise = new Promise((resolve, reject) => {
    const css = document.createElement('link');
    css.rel = 'stylesheet';
    css.href = 'https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.css';
    document.head.appendChild(css);
    const js = document.createElement('script');
    js.src = 'https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.js';
    js.onload = () => resolve();
    js.onerror = () => reject(new Error('leaflet load failed'));
    document.head.appendChild(js);
  });
  return state.leafletPromise;
}

function stationHasInside(s) {
  return s.toilets.some((t) => t.zone === 'inside' || t.zone === 'both');
}

function initMap() {
  const map = L.map('map');
  state.map = map;
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> 贡献者'
  }).addTo(map);

  const bounds = L.latLngBounds([]);
  state.stations.forEach((s) => {
    const [lng, lat] = s.coords.wgs84;
    const ll = [lat, lng];
    bounds.extend(ll);
    const marker = L.circleMarker(ll, {
      radius: 7,
      color: '#ffffff',
      weight: 1.5,
      fillColor: stationHasInside(s) ? '#1e9e50' : '#ef6c00',
      fillOpacity: 0.95
    }).addTo(map);
    marker.bindTooltip(s.name, { direction: 'top', offset: [0, -8] });
    marker.on('click', () => openStationModal(s));
  });
  if (bounds.isValid()) map.fitBounds(bounds.pad(0.05));

  updateUserMarker();
}

function updateUserMarker() {
  if (!state.map || !state.pos) return;
  const ll = [state.pos.lat, state.pos.lng];
  if (state.userMarker) {
    state.userMarker.setLatLng(ll);
  } else {
    state.userMarker = L.circleMarker(ll, {
      radius: 8,
      color: '#ffffff',
      weight: 2,
      fillColor: '#0a5bd6',
      fillOpacity: 1
    }).addTo(state.map);
    state.userMarker.bindTooltip('我的位置', { direction: 'top', offset: [0, -10] });
  }
}

async function ensureMap() {
  if (state.map) {
    setTimeout(() => state.map.invalidateSize(), 60);
    return;
  }
  try {
    await loadLeaflet();
    initMap();
    setTimeout(() => state.map.invalidateSize(), 60);
  } catch (e) {
    $('#map').innerHTML = '<p class="map-error">地图资源加载失败，请检查网络后切换标签页重试</p>';
    state.leafletPromise = null;
  }
}

/* ---------------- 标签页 / 事件绑定 ---------------- */

function switchTab(tab) {
  state.tab = tab;
  document.querySelectorAll('.tab').forEach((b) => b.classList.toggle('active', b.dataset.tab === tab));
  document.querySelectorAll('.view').forEach((v) => v.classList.remove('active'));
  $(`#view-${tab}`).classList.add('active');
  if (tab === 'map') ensureMap();
  if (tab === 'lines') setTimeout(updateChipFades, 50);
}

function bindEvents() {
  document.querySelectorAll('.tab').forEach((b) =>
    b.addEventListener('click', () => switchTab(b.dataset.tab))
  );

  $('#filter-chips').addEventListener('click', (e) => {
    const chip = e.target.closest('.chip');
    if (!chip) return;
    state.filter = chip.dataset.filter;
    document.querySelectorAll('#filter-chips .chip').forEach((c) =>
      c.classList.toggle('active', c === chip)
    );
    renderNearby();
    renderLineStations();
  });

  let searchTimer = null;
  $('#search-input').addEventListener('input', (e) => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      state.query = e.target.value.trim();
      state.searchScope = 'auto';
      renderNearby();
      renderLineStations();
    }, 150);
  });

  $('#line-search-hint').addEventListener('click', (e) => {
    const btn = e.target.closest('button[data-scope]');
    if (!btn) return;
    state.searchScope = btn.dataset.scope;
    renderLineStations();
  });

  $('#line-chips').addEventListener('click', (e) => {
    const chip = e.target.closest('.line-chip');
    if (!chip) return;
    state.line = chip.dataset.line;
    state.searchScope = 'auto';
    renderLineChips();
    renderLineStations();
  });

  $('#line-chips').addEventListener('scroll', updateChipFades, { passive: true });
  window.addEventListener('resize', updateChipFades);

  // 桌面端：纵向滚轮转横向滚动
  $('#line-chips').addEventListener('wheel', (e) => {
    if (Math.abs(e.deltaY) <= Math.abs(e.deltaX)) return;
    e.preventDefault();
    e.currentTarget.scrollLeft += e.deltaY;
  }, { passive: false });

  // 卡片点击 → 车站详情（事件委托覆盖两个列表）
  document.querySelectorAll('.station-list').forEach((el) =>
    el.addEventListener('click', (e) => {
      const card = e.target.closest('.station-card');
      if (!card) return;
      const s = findStation(card.dataset.name);
      if (s) openStationModal(s);
    })
  );

  $('#modal-backdrop').addEventListener('click', closeModal);
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !$('#station-modal').hidden) closeModal();
  });
}

/* ---------------- 初始化 ---------------- */

async function init() {
  bindEvents();

  let res;
  try {
    res = await fetch('data/stations.json');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    state.data = await res.json();
  } catch (e) {
    $('#data-version').textContent = '数据加载失败，请刷新重试';
    $('#locate-panel').innerHTML = '<p class="locate-error">车站数据加载失败，请检查网络后刷新</p>';
    return;
  }

  state.stations = state.data.stations || [];
  state.byName = new Map(state.stations.map((s) => [s.name, s]));

  const meta = state.data.meta || {};
  $('#data-version').textContent =
    `数据更新于 ${meta.fetched_at} · ${meta.station_count}站/${meta.toilet_count}厕所`;
  $('#disclaimer').textContent = meta.disclaimer || '';
  const repoLink = $('#repo-link');
  repoLink.href = REPO_URL;

  // 有缓存位置则直接用它渲染
  let restored = false;
  try {
    const cached = JSON.parse(localStorage.getItem(POS_CACHE_KEY) || 'null');
    if (cached && typeof cached.lat === 'number' && typeof cached.lng === 'number') {
      state.pos = { lat: cached.lat, lng: cached.lng };
      restored = true;
    }
  } catch (e) { /* 损坏缓存忽略 */ }
  setLocatePanel(restored ? 'done' : 'idle');

  renderNearby();
  renderLineChips();
  renderLineStations();
}

init();

if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('sw.js').catch(() => { /* 注册失败不影响使用 */ });
  });
}
