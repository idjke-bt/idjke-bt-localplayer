/*
 * app.js — LocalPlayer 前端逻辑
 * 海报墙渲染、电影详情、电视剧详情、设置页、API 调用与交互处理
 */

// ============================================================================
// 配置
// ============================================================================

const API_BASE = "/api";

// ============================================================================
// 全局状态
// ============================================================================

let currentMovieId = null;
let currentShowId = null;
let currentFilter = "all";        // all | movie | tvshow | favorite
let currentTVSeason = null;
let currentTVScrollLeft = 0;
let favoritesOnly = false;
let currentWatched = "";         // "" = all, "true" = watched, "false" = unwatched
let currentEpisodes = [];        // 当前电视剧的单集数据（用于季切换）
let searchQuery = "";
let _searchTimer = null;

// ============================================================================
// 工具函数
// ============================================================================

function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
}

// SVG 图标
function iconWatched(isWatched) {
    if (isWatched) {
        return '<svg width="22" height="22" viewBox="0 0 24 24"><circle cx="12" cy="12" r="11" fill="#4caf50" stroke="#43a047" stroke-width="1"/><path d="M7 12l3 3 6-6" stroke="#fff" stroke-width="2.5" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>';
    }
    return '<svg width="22" height="22" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10" fill="none" stroke="#777" stroke-width="2"/></svg>';
}

function iconFavorite(isFavorited) {
    var color = isFavorited ? "#e94560" : "#777";
    var fill = isFavorited ? "#e94560" : "none";
    return '<svg width="20" height="20" viewBox="0 0 24 24"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z" fill="' + fill + '" stroke="' + color + '" stroke-width="2"/></svg>';
}

function iconDelete() {
    return '<svg width="18" height="18" viewBox="0 0 24 24"><path d="M3 6h18M8 6V4a2 2 0 012-2h4a2 2 0 012 2v2m3 0v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6h14" stroke="#999" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>';
}

async function apiGet(url) {
    const res = await fetch(url);
    if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.error || `HTTP ${res.status}`);
    }
    return res.json();
}

async function apiPost(url, body = {}) {
    const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
    });
    if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.error || `HTTP ${res.status}`);
    }
    return res.json();
}

// ============================================================================
// 视图切换
// ============================================================================

function switchView(viewName) {
    document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
    const target = document.getElementById(`view-${viewName}`);
    if (target) target.classList.add("active");

    document.querySelectorAll(".nav-tab").forEach((tab) => {
        tab.classList.toggle("active", tab.dataset.view === viewName);
    });

    if (viewName === "home") {
        clearWallFanart();
    }
}

// ============================================================================
// 侧边栏筛选
// ============================================================================

function setSidebarFilter(filter) {
    currentFilter = filter;
    favoritesOnly = (filter === "favorite");

    // 更新侧边栏按钮状态
    document.querySelectorAll(".sidebar-btn").forEach((btn) => {
        btn.classList.toggle("active", btn.dataset.filter === filter);
    });

    // 更新顶部收藏按钮
    const favBtn = document.getElementById("btn-nav-fav");
    if (favoritesOnly) {
        favBtn.innerHTML = "&#9829;";
        favBtn.dataset.active = "true";
        favBtn.classList.add("active");
    } else {
        favBtn.innerHTML = "&#9825;";
        favBtn.dataset.active = "false";
        favBtn.classList.remove("active");
    }

    switchView("home");
    loadPosterWall();
}

// ============================================================================
// 海报墙
// ============================================================================

async function loadPosterWall() {
    const sortBy = document.getElementById("sort-select").value;
    const genre = document.getElementById("genre-select").value;
    const search = searchQuery.trim();

    // 根据侧边栏筛选决定 API 调用
    let url;
    if (currentFilter === "all" && !favoritesOnly) {
        url = `${API_BASE}/all_media?sort=${sortBy}&genre=${encodeURIComponent(genre)}`;
    } else if (currentFilter === "movie") {
        url = `${API_BASE}/movies?sort=${sortBy}&genre=${encodeURIComponent(genre)}`;
        if (favoritesOnly) url += "&favorite=true";
    } else if (currentFilter === "tvshow") {
        url = `${API_BASE}/shows?sort=${sortBy}&genre=${encodeURIComponent(genre)}`;
        if (favoritesOnly) url += "&favorite=true";
    } else if (currentFilter === "favorite") {
        url = `${API_BASE}/all_media?sort=${sortBy}&genre=${encodeURIComponent(genre)}&favorite=true`;
    } else {
        url = `${API_BASE}/all_media?sort=${sortBy}&genre=${encodeURIComponent(genre)}`;
    }
    if (currentWatched) url += `&watched=${currentWatched}`;
    if (search) url += `&search=${encodeURIComponent(search)}`;

    try {
        const data = await apiGet(url);
        // 统一数据格式
        let items;
        if (data.media) {
            items = data.media;
        } else if (data.movies) {
            items = data.movies;
        } else if (data.shows) {
            items = data.shows;
        } else {
            items = [];
        }
        renderPosterGrid(items);
        const label = favoritesOnly ? "收藏" : "共";
        document.getElementById("media-count").textContent = `${label} ${data.count} 部`;
    } catch (err) {
        console.error("加载媒体列表失败:", err);
        document.getElementById("poster-grid").innerHTML =
            '<p style="padding:24px;color:var(--text-secondary)">加载失败，请检查后端是否正常运行。</p>';
    }
}

async function renderPosterGrid(items) {
    const grid = document.getElementById("poster-grid");
    if (!items.length) {
        if (favoritesOnly) {
            grid.innerHTML = `
                <div class="welcome-card">
                    <div class="welcome-icon">&#9825;</div>
                    <h2>暂无收藏</h2>
                    <p>你还没有收藏任何媒体。</p>
                    <p class="welcome-hint">点击详情页的心形按钮即可收藏。</p>
                    <button class="welcome-btn" onclick="setSidebarFilter('all')">查看全部</button>
                </div>`;
            return;
        }

        let hasRoots = false;
        try {
            const data = await apiGet(`${API_BASE}/settings`);
            hasRoots = (data.settings.media_roots || []).length > 0;
        } catch (_) {}

        if (hasRoots) {
            grid.innerHTML = `
                <div class="welcome-card">
                    <div class="welcome-icon">🎬</div>
                    <h2>媒体库为空</h2>
                    <p>已配置媒体根目录，但尚未扫描到任何媒体。</p>
                    <p class="welcome-hint">请确认目录中包含视频文件 (mkv/mp4/avi)，然后执行扫描。</p>
                    <button class="welcome-btn" onclick="triggerScanFromWall()">立即扫描</button>
                </div>`;
        } else {
            grid.innerHTML = `
                <div class="welcome-card">
                    <div class="welcome-icon">📂</div>
                    <h2>欢迎使用 LocalPlayer</h2>
                    <p>开始使用前，请先配置媒体库根目录。</p>
                    <p class="welcome-hint">将你存放电影/电视剧的文件夹路径添加到设置中，然后执行扫描即可建立媒体库。</p>
                    <button class="welcome-btn" onclick="switchView('settings');loadSettings();">前往设置</button>
                </div>`;
        }
        return;
    }

    grid.innerHTML = items.map((m) => {
        const urlPrefix = m.media_type === "movie" ? "movie" : "show";
        const posterUrl = `/api/${urlPrefix}/${m.id}/poster`;

        const imgHtml = posterUrl
            ? `<div class="card-img-container"><img class="card-img" src="${posterUrl}" alt="${escapeHtml(m.title)}" loading="lazy" onerror="this.outerHTML='<div class=\\'card-img-placeholder\\'>&#127916;</div>'"></div>`
            : `<div class="card-img-placeholder">&#127916;</div>`;

        let badges = "";
        const isMovie = m.media_type === "movie";
        if (m.is_watched !== undefined && !m.is_watched)
            badges += '<span class="badge badge-new">NEW</span>';
        if (m.is_watched) badges += '<span class="badge badge-watched-circle"></span>';
        if (m.is_favorite) badges += '<span class="badge badge-favorite">&#9829;</span>';

        const fanartType = m.media_type === "movie" ? "movie" : "show";
        const fanartAttr = m.fanart_path ? ` data-fanart="${m.id}" data-fanart-type="${fanartType}"` : "";

        const onClick = isMovie
            ? `event.stopPropagation(); openDetail(${m.id});`
            : `event.stopPropagation(); openTVShowDetail(${m.id});`;

        return `
        <div class="poster-card" data-id="${m.id}" data-type="${m.media_type}"${fanartAttr} onclick="${onClick}" title="${escapeHtml(m.title)}">
            <div class="card-img-wrapper">
                ${imgHtml}
                ${badges}
            </div>
            <div class="card-info">
                <div class="card-title">${escapeHtml(m.title)}</div>
                <div class="card-year">${m.year || "—"}</div>
            </div>
        </div>`;
    }).join("");

}

// ============================================================================
// 电影详情页
// ============================================================================

async function openDetail(movieId) {
    currentMovieId = movieId;
    currentShowId = null;
    switchView("detail");
    document.getElementById("detail-container").innerHTML =
        '<p style="text-align:center;padding:60px;color:var(--text-secondary);">加载中...</p>';

    try {
        const movie = await apiGet(`${API_BASE}/movies/${movieId}`);
        renderDetail(movie);
    } catch (err) {
        console.error("加载电影详情失败:", err);
        document.getElementById("detail-container").innerHTML =
            `<p style="text-align:center;padding:60px;color:var(--accent);">加载失败: ${escapeHtml(err.message)}</p>`;
    }
}

function renderChipTags(items, label) {
    if (!items || (Array.isArray(items) && items.length === 0)) return "";
    const arr = Array.isArray(items) ? items : [items];
    const tagHtml = arr.map((item) => {
        const text = typeof item === "string" ? item : (item.name || "");
        const role = (item.role) ? ` <span class="chip-role">${escapeHtml(item.role)}</span>` : "";
        return `<span class="chip-tag">${escapeHtml(text)}${role}</span>`;
    }).join("");
    return `<div class="detail-meta-line chip-line"><span class="meta-label">${label}</span><span class="chip-tag-container">${tagHtml}</span></div>`;
}

function renderVideoSpecTags(specsJson) {
    if (!specsJson) return "";
    let specs;
    try {
        specs = typeof specsJson === "string" ? JSON.parse(specsJson) : specsJson;
    } catch (_) { return ""; }
    const keys = Object.keys(specs);
    if (keys.length === 0) return "";
    const order = ["resolution", "video_codec", "hdr", "audio", "source"];
    const labels = {
        resolution: "分辨率", video_codec: "编码", hdr: "HDR",
        audio: "音频", source: "来源"
    };
    return `<div class="detail-tags">${order
        .filter((k) => specs[k])
        .map((k) => `<span class="detail-tag tag-${k}">${labels[k]}: ${specs[k]}</span>`)
        .join("")}</div>`;
}

function renderTechCards(mediaInfo, videoPath) {
    if (!mediaInfo) {
        return "";
    }

    var info;
    try {
        info = typeof mediaInfo === "string" ? JSON.parse(mediaInfo) : mediaInfo;
    } catch (_) { return ""; }
    if (!info || Object.keys(info).length === 0) return "";

    var cards = "";

    // 视频卡片
    if (info.video) {
        var v = info.video;
        cards += '<div class="tech-card"><h4>视频</h4><table>';
        if (v.title) cards += '<tr><td class="tech-label">标题</td><td class="tech-value">' + escapeHtml(v.title) + '</td></tr>';
        if (v.codec) cards += '<tr><td class="tech-label">编解码器</td><td class="tech-value">' + escapeHtml(v.codec) + '</td></tr>';
        if (v.profile) cards += '<tr><td class="tech-label">配置</td><td class="tech-value">' + escapeHtml(v.profile) + '</td></tr>';
        if (v.level) cards += '<tr><td class="tech-label">等级</td><td class="tech-value">' + escapeHtml(String(v.level)) + '</td></tr>';
        if (v.width && v.height) {
            var res = v.width + "x" + v.height;
            if (v.aspect) res += ' (' + escapeHtml(String(v.aspect)) + ')';
            cards += '<tr><td class="tech-label">分辨率</td><td class="tech-value">' + res + '</td></tr>';
        } else if (v.aspect) {
            cards += '<tr><td class="tech-label">宽高比</td><td class="tech-value">' + escapeHtml(String(v.aspect)) + '</td></tr>';
        }
        if (v.interlaced !== undefined) cards += '<tr><td class="tech-label">隔行扫描</td><td class="tech-value">' + (v.interlaced ? '是' : '否') + '</td></tr>';
        if (v.framerate) cards += '<tr><td class="tech-label">帧率</td><td class="tech-value">' + escapeHtml(String(v.framerate)) + ' fps</td></tr>';
        if (v.bitrate) {
            var br = v.bitrate;
            if (br >= 1000000) br = (br / 1000000).toFixed(1) + " Mbps";
            else if (br >= 1000) br = (br / 1000).toFixed(0) + " Kbps";
            cards += '<tr><td class="tech-label">比特率</td><td class="tech-value">' + br + '</td></tr>';
        }
        if (v.colorspace) cards += '<tr><td class="tech-label">色域</td><td class="tech-value">' + escapeHtml(String(v.colorspace)) + '</td></tr>';
        if (v.color_transfer) cards += '<tr><td class="tech-label">色彩转换</td><td class="tech-value">' + escapeHtml(String(v.color_transfer)) + '</td></tr>';
        if (v.bit_depth) cards += '<tr><td class="tech-label">位深度</td><td class="tech-value">' + escapeHtml(String(v.bit_depth)) + ' bit</td></tr>';
        if (v.pixel_format) cards += '<tr><td class="tech-label">像素格式</td><td class="tech-value">' + escapeHtml(String(v.pixel_format)) + '</td></tr>';
        cards += '</table></div>';
    }

    // 音频卡片
    var audioStreams = info.audio;
    if (audioStreams && audioStreams.length > 0) {
        cards += '<div class="tech-card"><h4>音频</h4>';
        audioStreams.forEach(function(a, idx) {
            if (idx > 0) cards += '<hr style="border-color:rgba(255,255,255,0.06);margin:8px 0;">';
            cards += '<table>';
            if (a.title) cards += '<tr><td class="tech-label">标题</td><td class="tech-value">' + escapeHtml(a.title) + '</td></tr>';
            if (a.language) cards += '<tr><td class="tech-label">语言</td><td class="tech-value">' + escapeHtml(a.language) + '</td></tr>';
            if (a.codec) cards += '<tr><td class="tech-label">编解码器</td><td class="tech-value">' + escapeHtml(a.codec) + '</td></tr>';
            if (a.channel_layout) cards += '<tr><td class="tech-label">声道布局</td><td class="tech-value">' + escapeHtml(a.channel_layout) + '</td></tr>';
            if (a.channels) cards += '<tr><td class="tech-label">声道数</td><td class="tech-value">' + escapeHtml(String(a.channels)) + '</td></tr>';
            if (a.sample_rate) {
                var sr = a.sample_rate;
                if (sr >= 1000) sr = (sr / 1000).toFixed(1) + " kHz";
                else sr = sr + " Hz";
                cards += '<tr><td class="tech-label">采样率</td><td class="tech-value">' + sr + '</td></tr>';
            }
            if (a.bit_depth) cards += '<tr><td class="tech-label">位深度</td><td class="tech-value">' + escapeHtml(String(a.bit_depth)) + ' bit</td></tr>';
            if (a.default !== undefined) cards += '<tr><td class="tech-label">默认</td><td class="tech-value">' + (a.default ? '是' : '否') + '</td></tr>';
            cards += '</table>';
        });
        cards += '</div>';
    }

    // 字幕卡片
    var subStreams = info.subtitles;
    if (subStreams && subStreams.length > 0) {
        cards += '<div class="tech-card"><h4>字幕</h4>';
        subStreams.forEach(function(s, idx) {
            if (idx > 0) cards += '<hr style="border-color:rgba(255,255,255,0.06);margin:8px 0;">';
            cards += '<table>';
            if (s.title) cards += '<tr><td class="tech-label">标题</td><td class="tech-value">' + escapeHtml(s.title) + '</td></tr>';
            if (s.language) cards += '<tr><td class="tech-label">语言</td><td class="tech-value">' + escapeHtml(s.language) + '</td></tr>';
            if (s.format) cards += '<tr><td class="tech-label">格式</td><td class="tech-value">' + escapeHtml(s.format) + '</td></tr>';
            if (s.default !== undefined) cards += '<tr><td class="tech-label">默认</td><td class="tech-value">' + (s.default ? '是' : '否') + '</td></tr>';
            if (s.forced !== undefined) cards += '<tr><td class="tech-label">强制</td><td class="tech-value">' + (s.forced ? '是' : '否') + '</td></tr>';
            cards += '</table>';
        });
        cards += '</div>';
    }

    if (!cards) return "";
    return '<div class="detail-tech-grid">' + cards + '</div>';
}

function renderFileInfo(mediaInfo, videoPath) {
    var lines = [];
    if (videoPath) {
        lines.push('<p><strong>文件位置：</strong>' + escapeHtml(videoPath) + '</p>');
    }
    if (mediaInfo) {
        var info;
        try {
            info = typeof mediaInfo === "string" ? JSON.parse(mediaInfo) : mediaInfo;
        } catch (_) { info = null; }
        if (info && info.file_size) {
            var size = info.file_size;
            var sizeStr;
            if (size >= 1073741824) sizeStr = (size / 1073741824).toFixed(2) + " GB";
            else if (size >= 1048576) sizeStr = (size / 1048576).toFixed(1) + " MB";
            else sizeStr = (size / 1024).toFixed(0) + " KB";
            lines.push('<p><strong>文件大小：</strong>' + sizeStr + '</p>');
        }
    }
    if (!lines.length) return "";
    return '<div class="detail-file-info">' + lines.join("") + '</div>';
}

function renderDetail(movie) {
    var container = document.getElementById("detail-container");
    var posterUrl = "/api/movie/" + movie.id + "/poster";

    var runtimeStr = "";
    if (movie.runtime) {
        var mins = parseInt(movie.runtime, 10);
        if (!isNaN(mins)) {
            var h = Math.floor(mins / 60);
            var m = mins % 60;
            runtimeStr = h > 0 ? h + " 小时 " + m + " 分钟" : m + " 分钟";
        } else {
            runtimeStr = movie.runtime;
        }
    }

    // 年份-评分-时长 横向行
    var yearRatingParts = [];
    if (movie.year) yearRatingParts.push(escapeHtml(movie.year));
    if (movie.rating) yearRatingParts.push('★ ' + escapeHtml(movie.rating));
    if (runtimeStr) yearRatingParts.push(runtimeStr);
    var yearRatingHtml = yearRatingParts.length > 0
        ? '<div class="detail-year-rating">' + yearRatingParts.join(' <span class="sep">·</span> ') + '</div>'
        : "";

    var metaLines = [];
    metaLines.push(renderChipTags(movie.director, "导演"));
    metaLines.push(renderChipTags(movie.writer, "编剧"));
    metaLines.push(renderChipTags(movie.actors, "主演"));
    metaLines.push(renderChipTags(movie.genre, "类型"));

    container.innerHTML = `
        <div class="detail-header">
            ${posterUrl
                ? '<img class="detail-poster" src="' + posterUrl + '" alt="' + escapeHtml(movie.title) + '" onerror="this.style.display=\'none\'">'
                : ""}
            <div class="detail-meta">
                <div class="detail-top">
                    <h2 class="detail-title">${escapeHtml(movie.title)}</h2>
                    ${movie.original_title ? '<p class="detail-original-title">' + escapeHtml(movie.original_title) + '</p>' : ""}
                    ${yearRatingHtml}
                    ${metaLines.length ? '<div class="detail-meta-lines">' + metaLines.join("") + '</div>' : ""}
                    ${renderVideoSpecTags(movie.video_specs)}
                    <div class="detail-actions">
                        <button class="btn-play" onclick="playMovie(${movie.id})">▶ 播放</button>
                        <button class="btn-icon-action ${movie.is_watched ? 'active' : ''}" onclick="toggleWatched(${movie.id})" title="${movie.is_watched ? '标记未看' : '标记已看'}">
                            ${iconWatched(movie.is_watched)}
                        </button>
                        <button class="btn-icon-action ${movie.is_favorite ? 'favorited' : ''}" onclick="toggleFavorite(${movie.id})" title="收藏">
                            ${iconFavorite(movie.is_favorite)}
                        </button>
                        <button class="btn-icon-action btn-delete" onclick="deleteMovie(${movie.id})" title="删除此条目">
                            ${iconDelete()}
                        </button>
                    </div>
                </div>
            </div>
        </div>

        <div class="detail-plot-section">
            <h3>剧情简介</h3>
            <div class="detail-plot-text" id="detail-plot-text">${escapeHtml(movie.plot || "暂无简介")}</div>
            <button class="btn-plot-expand" id="btn-plot-expand" style="display:none;" onclick="togglePlotExpand()">展开更多 ▼</button>
        </div>

        ${renderTechCards(movie.media_info, movie.video_path)}
        ${renderFileInfo(movie.media_info, movie.video_path)}
        ${movie.last_played_time ? '<p style="color:var(--text-secondary);font-size:13px;margin-top:12px;">上次播放: ' + new Date(movie.last_played_time).toLocaleString("zh-CN") + '</p>' : ""}
    `;

    // 检查简介是否需要展开按钮
    var plotText = document.getElementById("detail-plot-text");
    if (plotText && plotText.scrollHeight > plotText.clientHeight + 2) {
        var btn = document.getElementById("btn-plot-expand");
        if (btn) btn.style.display = "inline-block";
    }

    setFanartBackground(movie);
}

function togglePlotExpand() {
    var text = document.getElementById("detail-plot-text");
    var btn = document.getElementById("btn-plot-expand");
    if (!text || !btn) return;
    var expanded = text.classList.toggle("expanded");
    btn.textContent = expanded ? "收起 ▲" : "展开更多 ▼";
}

async function playMovie(movieId) {
    const btn = document.querySelector(".btn-play");
    if (btn) { btn.disabled = true; btn.textContent = "启动中..."; }

    try {
        const result = await apiPost(`${API_BASE}/movies/${movieId}/play`);
        if (result.status === "ok") {
            showToast(result.message, "success");
            const movie = await apiGet(`${API_BASE}/movies/${movieId}`);
            renderDetail(movie);
        }
    } catch (err) {
        console.error("播放失败:", err);
        alert(`播放失败\n\n${err.message}\n\n请检查：\n1. 设置中的播放器路径是否正确\n2. 播放器是否已安装`);
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = "▶ 播放"; }
    }
}

async function toggleWatched(movieId) {
    try {
        await apiPost(`${API_BASE}/movies/${movieId}/watched`);
        const movie = await apiGet(`${API_BASE}/movies/${movieId}`);
        renderDetail(movie);
    } catch (err) {
        console.error("切换已看状态失败:", err);
    }
}

async function toggleFavorite(movieId) {
    try {
        await apiPost(`${API_BASE}/movies/${movieId}/favorite`);
        const movie = await apiGet(`${API_BASE}/movies/${movieId}`);
        renderDetail(movie);
    } catch (err) {
        console.error("切换收藏状态失败:", err);
    }
}

async function deleteMovie(movieId) {
    if (!confirm("确定要从媒体库中删除此条目吗？\n\n（不会删除实际文件，仅移除数据库记录）")) return;

    try {
        await fetch(`${API_BASE}/movies/${movieId}`, { method: "DELETE" });
        showToast("已删除", "success");
        switchView("home");
        await loadPosterWall();
    } catch (err) {
        console.error("删除失败:", err);
        alert(`删除失败: ${err.message}`);
    }
}

// ============================================================================
// 电视剧详情页
// ============================================================================

async function openTVShowDetail(showId) {
    currentShowId = showId;
    currentMovieId = null;
    currentTVSeason = null;
    currentTVScrollLeft = 0;
    switchView("tvshow");
    document.getElementById("tvshow-container").innerHTML =
        '<p style="text-align:center;padding:60px;color:var(--text-secondary);">加载中...</p>';

    try {
        const show = await apiGet(`${API_BASE}/shows/${showId}`);
        const epData = await apiGet(`${API_BASE}/shows/${showId}/episodes`);
        renderTVShow(show, epData.episodes, epData.seasons);
    } catch (err) {
        console.error("加载电视剧详情失败:", err);
        document.getElementById("tvshow-container").innerHTML =
            `<p style="text-align:center;padding:60px;color:var(--accent);">加载失败: ${escapeHtml(err.message)}</p>`;
    }
}

function renderTVShow(show, episodes, seasons, targetSeason) {
    currentEpisodes = episodes;
    const container = document.getElementById("tvshow-container");
    const posterUrl = `/api/show/${show.id}/poster`;

    // 年份-评分-季数 横向行
    var yearRatingParts = [];
    if (show.year) yearRatingParts.push(escapeHtml(show.year));
    if (show.rating) yearRatingParts.push('★ ' + escapeHtml(show.rating));
    if (show.season_count) yearRatingParts.push(show.season_count + ' 季');
    var yearRatingHtml = yearRatingParts.length > 0
        ? '<div class="detail-year-rating">' + yearRatingParts.join(' <span class="sep">·</span> ') + '</div>'
        : "";

    const metaLines = [];
    metaLines.push(renderChipTags(show.director, "导演"));
    metaLines.push(renderChipTags(show.writer, "编剧"));
    metaLines.push(renderChipTags(show.actors, "主演"));
    metaLines.push(renderChipTags(show.genre, "类型"));

    // 计算整剧/每季已看状态
    const allWatched = episodes.length > 0 && episodes.every((ep) => ep.is_watched);

    // 构建季标签（含批量已看按钮）
    const seasonTabs = seasons.map((s) => {
        const seasonEps = episodes.filter((ep) => ep.season === s);
        const seasonAllWatched = seasonEps.length > 0 && seasonEps.every((ep) => ep.is_watched);
        return `
            <div class="season-tab-group">
                <button class="season-tab" data-season="${s}">第 ${s} 季</button>
                <button class="season-watched-btn ${seasonAllWatched ? 'all-watched' : ''}"
                    onclick="event.stopPropagation(); toggleSeasonWatched(${show.id}, ${s})"
                    title="${seasonAllWatched ? '标记整季未看' : '标记整季已看'}">
                    ✓
                </button>
            </div>`;
    }).join("");

    // 确定默认展示的季
    let activeSeason = seasons.length > 0 ? seasons[0] : 0;
    if (targetSeason != null && seasons.includes(targetSeason)) {
        activeSeason = targetSeason;
    }
    const seasonEpisodesHtml = buildEpisodeList(episodes, activeSeason);

    container.innerHTML = `
        <div class="detail-header">
            ${posterUrl
                ? `<img class="detail-poster" src="${posterUrl}" alt="${escapeHtml(show.title)}" onerror="this.style.display='none'">`
                : ""}
            <div class="detail-meta">
                <div class="detail-top">
                    <h2 class="detail-title">${escapeHtml(show.title)}</h2>
                    ${show.original_title ? `<p class="detail-original-title">${escapeHtml(show.original_title)}</p>` : ""}
                    ${yearRatingHtml}
                    ${metaLines.length ? `<div class="detail-meta-lines">${metaLines.join("")}</div>` : ""}
                    ${renderVideoSpecTags(show.video_specs)}
                    <div class="detail-actions">
                        <button class="btn-icon-action ${allWatched ? 'active' : ''}" onclick="toggleShowWatched(${show.id})" title="${allWatched ? '整剧标记未看' : '整剧标记已看'}">
                            ${iconWatched(allWatched)}
                        </button>
                        <button class="btn-icon-action ${show.is_favorite ? 'favorited' : ''}" onclick="toggleShowFavorite(${show.id})" title="收藏">
                            ${iconFavorite(show.is_favorite)}
                        </button>
                        <button class="btn-icon-action btn-delete" onclick="deleteShow(${show.id})" title="删除此条目">
                            ${iconDelete()}
                        </button>
                    </div>
                </div>
            </div>
        </div>

        <div class="detail-plot-section">
            <h3>剧情简介</h3>
            <div class="detail-plot-text" id="detail-plot-text">${escapeHtml(show.plot || "暂无简介")}</div>
            <button class="btn-plot-expand" id="btn-plot-expand" style="display:none;" onclick="togglePlotExpand()">展开更多 ▼</button>
        </div>

        <div class="tv-seasons">
            <div class="season-tabs">
                ${seasonTabs}
            </div>
            <div class="episode-list" id="episode-list">
                ${seasonEpisodesHtml}
            </div>
        </div>
    `;

    // 检查简介是否需要展开按钮
    var plotText = document.getElementById("detail-plot-text");
    if (plotText && plotText.scrollHeight > plotText.clientHeight + 2) {
        var btn = document.getElementById("btn-plot-expand");
        if (btn) btn.style.display = "inline-block";
    }

    // 绑定季标签切换
    container.querySelectorAll(".season-tab").forEach((tab) => {
        tab.classList.toggle("active", parseInt(tab.dataset.season) === activeSeason);
        tab.addEventListener("click", () => {
            container.querySelectorAll(".season-tab").forEach((t) => t.classList.remove("active"));
            tab.classList.add("active");
            const season = parseInt(tab.dataset.season);
            currentTVSeason = season;
            currentTVScrollLeft = 0;
            document.getElementById("episode-list").innerHTML = buildEpisodeList(currentEpisodes, season);
            bindEpisodeActions();
        });
    });

    bindEpisodeActions();

    // 恢复滚动位置
    const epScroll = document.getElementById("ep-scroll");
    if (epScroll && currentTVScrollLeft > 0) {
        epScroll.scrollLeft = currentTVScrollLeft;
    }

    // 更新当前季状态
    currentTVSeason = activeSeason;

    // 设置 fanart 背景
    setTVShowFanartBackground(show);
}

function buildEpisodeList(episodes, season) {
    const seasonEps = episodes.filter((ep) => ep.season === season);
    if (!seasonEps.length) {
        return '<p style="color:var(--text-secondary);padding:20px;text-align:center;">该季暂无单集</p>';
    }

    return `
        <div class="ep-scroll" id="ep-scroll">
            ${seasonEps.map((ep) => {
                const thumbUrl = `/api/thumb/${ep.id}`;

                const thumbHtml = thumbUrl
                    ? `<img class="ep-card-thumb" src="${thumbUrl}" alt="" loading="lazy" onerror="this.outerHTML='<div class=\\'ep-card-thumb-placeholder\\'>&#127916;</div>'">`
                    : `<div class="ep-card-thumb-placeholder">&#127916;</div>`;

                const epId = `S${String(ep.season).padStart(2, "0")}E${String(ep.episode).padStart(2, "0")}`;
                const shortTitle = ep.title || `第 ${ep.episode} 集`;

                return `
            <div class="ep-card ${ep.is_watched ? 'ep-watched' : ''}" data-ep-id="${ep.id}" data-season="${ep.season}">
                <div class="ep-card-thumb-wrap" title="播放 ${epId}">
                    ${thumbHtml}
                    <div class="ep-card-play-overlay">&#9654;</div>
                    <div class="ep-card-watched-badge ${ep.is_watched ? 'watched' : ''}" title="标记已看/未看"></div>
                </div>
                <div class="ep-card-body">
                    <span class="ep-card-id">${epId}</span>
                    <span class="ep-card-title" title="${escapeHtml(shortTitle)}">${escapeHtml(shortTitle)}</span>
                    ${ep.plot ? `<p class="ep-card-plot" title="${escapeHtml(ep.plot)}">${escapeHtml(ep.plot)}</p>` : ""}
                </div>
            </div>`;
            }).join("")}
        </div>`;
}

function bindEpisodeActions() {
    const scroll = document.getElementById("ep-scroll");
    if (!scroll) return;

    // 鼠标滚轮 → 横向滚动
    scroll.addEventListener("wheel", (e) => {
        if (Math.abs(e.deltaY) > Math.abs(e.deltaX)) {
            e.preventDefault();
            scroll.scrollLeft += e.deltaY;
        }
    }, { passive: false });

    // 事件委托：统一监听点击（播放按钮 + 已看标记）
    const epList = document.getElementById("episode-list");
    if (epList && !epList.dataset.bound) {
        epList.dataset.bound = "1";
        epList.addEventListener("click", (e) => {
            const card = e.target.closest(".ep-card");
            if (!card) return;
            const epId = parseInt(card.dataset.epId);
            if (!epId) return;

            if (e.target.closest(".ep-card-watched-badge")) {
                e.stopPropagation();
                toggleEpisodeWatched(epId);
                return;
            }
            if (e.target.closest(".ep-card-play-overlay")) {
                playEpisode(epId);
                return;
            }
        });

        // 双击播放
        epList.addEventListener("dblclick", (e) => {
            const card = e.target.closest(".ep-card");
            if (!card) return;
            if (e.target.closest(".ep-card-watched-badge")) return;
            const epId = parseInt(card.dataset.epId);
            if (epId) playEpisode(epId);
        });
    }
}

async function playEpisode(episodeId) {
    const epScroll = document.getElementById("ep-scroll");
    if (epScroll) currentTVScrollLeft = epScroll.scrollLeft;
    const targetSeason = currentTVSeason;

    try {
        const result = await apiPost(`${API_BASE}/episodes/${episodeId}/play`);
        if (result.status === "ok") {
            showToast(result.message, "success");
            if (currentShowId) {
                const show = await apiGet(`${API_BASE}/shows/${currentShowId}`);
                const epData = await apiGet(`${API_BASE}/shows/${currentShowId}/episodes`);
                renderTVShow(show, epData.episodes, epData.seasons, targetSeason);
            }
        }
    } catch (err) {
        console.error("播放失败:", err);
        alert(`播放失败\n\n${err.message}`);
    }
}

async function toggleEpisodeWatched(episodeId) {
    // 保存当前滚动位置
    const epScroll = document.getElementById("ep-scroll");
    if (epScroll) currentTVScrollLeft = epScroll.scrollLeft;

    // 通过 data-ep-id 查找 DOM 元素（而非 getElementById）
    const card = document.querySelector(`.ep-card[data-ep-id="${episodeId}"]`);
    const badge = card ? card.querySelector(".ep-card-watched-badge") : null;

    // 乐观更新
    if (card && badge) {
        card.classList.toggle("ep-watched");
        badge.classList.toggle("watched");
    }

    try {
        const result = await apiPost(`${API_BASE}/episodes/${episodeId}/watched`);
        // 同步服务器状态到 DOM
        if (card && badge) {
            const serverWatched = result.is_watched;
            const domWatched = badge.classList.contains("watched");
            if (serverWatched !== domWatched) {
                card.classList.toggle("ep-watched");
                badge.classList.toggle("watched");
            }
        }
        // 同步 currentEpisodes 数据，确保季切换后状态正确
        const ep = currentEpisodes.find(function(e) { return e.id === episodeId; });
        if (ep) ep.is_watched = result.is_watched;
        syncWatchedButtons(result);
    } catch (err) {
        console.error("切换单集已看状态失败:", err);
        if (card && badge) {
            card.classList.toggle("ep-watched");
            badge.classList.toggle("watched");
        }
    }
}

function syncWatchedButtons(result, isNowWatched) {
    if (!currentShowId) return;
    // 更新当前季按钮
    if (currentTVSeason) {
        const seasonBtns = document.querySelectorAll(".season-watched-btn");
        seasonBtns.forEach((btn) => {
            const seasonGroup = btn.closest(".season-tab-group");
            if (!seasonGroup) return;
            const tab = seasonGroup.querySelector(".season-tab");
            if (!tab || parseInt(tab.dataset.season) !== currentTVSeason) return;
            const cards = document.querySelectorAll(`.ep-card[data-season="${currentTVSeason}"]`);
            let allSeasonWatched = cards.length > 0;
            cards.forEach((c) => {
                if (!c.classList.contains("ep-watched")) allSeasonWatched = false;
            });
            if (allSeasonWatched) {
                btn.classList.add("all-watched");
                btn.title = "标记整季未看";
            } else {
                btn.classList.remove("all-watched");
                btn.title = "标记整季已看";
            }
        });
    }

    // 更新整剧已看按钮
    const allCards = document.querySelectorAll(".ep-card");
    let allShowWatched = allCards.length > 0;
    allCards.forEach((c) => {
        if (!c.classList.contains("ep-watched")) allShowWatched = false;
    });
    const showWatchedBtn = document.querySelector("#tvshow-container .btn-icon-action");
    if (showWatchedBtn) {
        if (allShowWatched) {
            showWatchedBtn.classList.add("active");
            showWatchedBtn.title = "整剧标记未看";
        } else {
            showWatchedBtn.classList.remove("active");
            showWatchedBtn.title = "整剧标记已看";
        }
        // 更新图标
        showWatchedBtn.innerHTML = iconWatched(allShowWatched);
    }
}

async function toggleShowFavorite(showId) {
    const epScroll = document.getElementById("ep-scroll");
    if (epScroll) currentTVScrollLeft = epScroll.scrollLeft;
    const targetSeason = currentTVSeason;

    try {
        await apiPost(`${API_BASE}/shows/${showId}/favorite`);
        const show = await apiGet(`${API_BASE}/shows/${showId}`);
        const epData = await apiGet(`${API_BASE}/shows/${showId}/episodes`);
        renderTVShow(show, epData.episodes, epData.seasons, targetSeason);
    } catch (err) {
        console.error("切换收藏状态失败:", err);
    }
}

async function deleteShow(showId) {
    if (!confirm("确定要从媒体库中删除该电视剧及其所有单集记录吗？\n\n（不会删除实际文件，仅移除数据库记录）")) return;

    try {
        await fetch(`${API_BASE}/shows/${showId}`, { method: "DELETE" });
        showToast("已删除", "success");
        switchView("home");
        await loadPosterWall();
    } catch (err) {
        console.error("删除失败:", err);
        alert(`删除失败: ${err.message}`);
    }
}

async function toggleShowWatched(showId) {
    // 保存当前季和滚动位置
    const epScroll = document.getElementById("ep-scroll");
    if (epScroll) currentTVScrollLeft = epScroll.scrollLeft;
    const targetSeason = currentTVSeason;

    try {
        const result = await apiPost(`${API_BASE}/shows/${showId}/watched`);
        showToast(result.all_watched ? "整剧已标记为已看" : "整剧已标记为未看", "success");
        const show = await apiGet(`${API_BASE}/shows/${showId}`);
        const epData = await apiGet(`${API_BASE}/shows/${showId}/episodes`);
        renderTVShow(show, epData.episodes, epData.seasons, targetSeason);
    } catch (err) {
        console.error("批量标记失败:", err);
    }
}

async function toggleSeasonWatched(showId, season) {
    // 保存滚动位置
    const epScroll = document.getElementById("ep-scroll");
    if (epScroll) currentTVScrollLeft = epScroll.scrollLeft;

    try {
        const result = await apiPost(`${API_BASE}/shows/${showId}/seasons/${season}/watched`);
        const label = result.all_watched ? "已看" : "未看";
        showToast(`第 ${season} 季已标记为${label}`, "success");
        const show = await apiGet(`${API_BASE}/shows/${showId}`);
        const epData = await apiGet(`${API_BASE}/shows/${showId}/episodes`);
        renderTVShow(show, epData.episodes, epData.seasons, season);
    } catch (err) {
        console.error("批量标记失败:", err);
    }
}

async function browseFolder() {
    const input = document.getElementById("input-media-root");
    const btn = document.getElementById("btn-browse-folder");
    btn.disabled = true;
    btn.textContent = "选择中...";
    try {
        const result = await apiPost(`${API_BASE}/browse-folder`);
        if (result.path) {
            input.value = result.path;
        }
    } catch (err) {
        console.error("浏览文件夹失败:", err);
        alert(`无法打开文件夹选择对话框: ${err.message}`);
    } finally {
        btn.disabled = false;
        btn.textContent = "浏览...";
    }
}

// ============================================================================
// 搜索
// ============================================================================

function handleSearchInput() {
    searchQuery = document.getElementById("search-input").value;
    const clearBtn = document.getElementById("btn-search-clear");
    clearBtn.style.display = searchQuery ? "inline-block" : "none";

    clearTimeout(_searchTimer);
    _searchTimer = setTimeout(() => {
        loadPosterWall();
    }, 300);
}

function clearSearch() {
    document.getElementById("search-input").value = "";
    searchQuery = "";
    document.getElementById("btn-search-clear").style.display = "none";
    loadPosterWall();
}

// ============================================================================
// 设置页
// ============================================================================

async function loadSettings() {
    try {
        const data = await apiGet(`${API_BASE}/settings`);
        renderSettings(data.settings);
    } catch (err) {
        console.error("加载设置失败:", err);
    }
}

function renderSettings(settings) {
    document.getElementById("input-player-path").value = settings.player_path || "";

    const rootsList = document.getElementById("media-roots-list");
    const roots = settings.media_roots || [];
    rootsList.innerHTML = roots.map((root) => `
        <li>
            <span title="${escapeHtml(root)}">${escapeHtml(root)}</span>
            <button class="btn-remove-root" onclick="removeMediaRoot('${escapeHtml(root)}')">删除</button>
        </li>
    `).join("");
}

async function addMediaRoot() {
    const input = document.getElementById("input-media-root");
    const path = input.value.trim();
    if (!path) return;

    try {
        const data = await apiGet(`${API_BASE}/settings`);
        const roots = data.settings.media_roots || [];
        if (!roots.includes(path)) {
            roots.push(path);
            await apiPost(`${API_BASE}/settings`, { media_roots: roots });
            input.value = "";
            await loadSettings();
            showToast(`已添加: ${path}`, "success");
        }
    } catch (err) {
        console.error("添加根目录失败:", err);
        alert(`添加失败: ${err.message}`);
    }
}

async function removeMediaRoot(path) {
    if (!confirm(`确定移除该目录？\n${path}\n\n（不会删除实际文件，仅移除扫描路径）`)) return;

    try {
        const data = await apiGet(`${API_BASE}/settings`);
        const roots = (data.settings.media_roots || []).filter((r) => r !== path);
        await apiPost(`${API_BASE}/settings`, { media_roots: roots });
        await loadSettings();
        showToast("已移除", "success");
    } catch (err) {
        console.error("移除根目录失败:", err);
    }
}

async function savePlayerPath() {
    const input = document.getElementById("input-player-path");
    const path = input.value.trim();
    if (!path) return;

    try {
        await apiPost(`${API_BASE}/settings`, { player_path: path });
        showToast("播放器路径已保存", "success");
    } catch (err) {
        console.error("保存播放器路径失败:", err);
        alert(`保存失败: ${err.message}`);
    }
}

// ============================================================================
// 扫描（SSE 进度推送）
// ============================================================================

let _scanEventSource = null;

function startScan({ onProgress, onDone, onError, mode }) {
    if (_scanEventSource) {
        _scanEventSource.close();
        _scanEventSource = null;
    }

    const scanUrl = mode === "incremental" ? `${API_BASE}/scan?mode=incremental` : `${API_BASE}/scan`;
    fetch(scanUrl, { method: "POST" })
        .then((res) => {
            if (res.status === 409) {
                onError("扫描正在进行中，请等待完成");
                return;
            }
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            _scanEventSource = new EventSource(`${API_BASE}/scan/progress`);
            _scanEventSource.onmessage = (e) => {
                try {
                    const evt = JSON.parse(e.data);
                    if (evt.event === "progress") {
                        onProgress(evt);
                    } else if (evt.event === "done") {
                        _scanEventSource.close();
                        _scanEventSource = null;
                        onDone(evt.stats);
                    } else if (evt.event === "error") {
                        _scanEventSource.close();
                        _scanEventSource = null;
                        onError(evt.detail);
                    }
                } catch (_) {}
            };
            _scanEventSource.onerror = () => {
                if (_scanEventSource) {
                    _scanEventSource.close();
                    _scanEventSource = null;
                }
            };
        })
        .catch((err) => onError(err.message));
}

function triggerScan() {
    const logDiv = document.getElementById("scan-log");
    const btn = document.getElementById("btn-scan");
    logDiv.textContent = "正在扫描...\n";
    btn.disabled = true;
    btn.textContent = "扫描中...";

    let lines = [];

    startScan({
        onProgress(evt) {
            if (evt.status === "scanning") {
                lines.push(`  ${evt.detail}`);
            } else if (evt.status === "found") {
                lines.push(`  ${evt.detail}`);
            } else if (evt.status === "cleanup") {
                lines.push(`  ${evt.detail}`);
            } else if (evt.status === "complete") {
                lines.push(evt.detail);
            }
            logDiv.textContent = lines.join("\n");
            logDiv.scrollTop = logDiv.scrollHeight;
        },
        onDone(stats) {
            const movies = stats.total_movies !== undefined ? stats.total_movies : (stats.total || 0);
            const shows = stats.total_shows || 0;
            const eps = stats.total_episodes || 0;
            logDiv.textContent =
                `扫描完成！\n` +
                `电影: ${movies} 部 | 电视剧: ${shows} 部 | 单集: ${eps} 集\n` +
                `新增: ${stats.added} | 更新: ${stats.updated} | 清理过期: ${stats.deleted || 0}\n` +
                `错误: ${stats.errors.length}\n`;
            if (stats.errors.length) {
                logDiv.textContent += `\n错误详情:\n${stats.errors.join("\n")}`;
            }
            btn.disabled = false;
            btn.textContent = "立即扫描";
            setTimeout(() => {
                switchView("home");
                loadGenres();
                loadPosterWall();
            }, 800);
        },
        onError(msg) {
            logDiv.textContent = `扫描失败: ${msg}`;
            btn.disabled = false;
            btn.textContent = "立即扫描";
        },
    });
}

function triggerScanIncremental() {
    const logDiv = document.getElementById("scan-log");
    const btnFull = document.getElementById("btn-scan");
    const btnIncr = document.getElementById("btn-scan-incr");
    logDiv.textContent = "正在增量扫描...\n";
    btnFull.disabled = true;
    btnIncr.disabled = true;
    btnIncr.textContent = "扫描中...";

    let lines = [];

    startScan({
        mode: "incremental",
        onProgress(evt) {
            if (evt.status === "info") {
                lines.push(`  ${evt.detail}`);
            } else if (evt.status === "scanning") {
                lines.push(`  ${evt.detail}`);
            } else if (evt.status === "found") {
                lines.push(`  ${evt.detail}`);
            } else if (evt.status === "complete") {
                lines.push(evt.detail);
            }
            logDiv.textContent = lines.join("\n");
            logDiv.scrollTop = logDiv.scrollHeight;
        },
        onDone(stats) {
            const movies = stats.total_movies !== undefined ? stats.total_movies : (stats.total || 0);
            const shows = stats.total_shows || 0;
            const eps = stats.total_episodes || 0;
            logDiv.textContent =
                `增量扫描完成！\n` +
                `电影: ${movies} 部 | 电视剧: ${shows} 部 | 单集: ${eps} 集\n` +
                `新增: ${stats.added} | 更新: ${stats.updated}\n` +
                `错误: ${stats.errors.length}\n`;
            if (stats.errors.length) {
                logDiv.textContent += `\n错误详情:\n${stats.errors.join("\n")}`;
            }
            btnFull.disabled = false;
            btnIncr.disabled = false;
            btnIncr.textContent = "扫描新增";
            setTimeout(() => {
                switchView("home");
                loadGenres();
                loadPosterWall();
            }, 800);
        },
        onError(msg) {
            logDiv.textContent = `扫描失败: ${msg}`;
            btnFull.disabled = false;
            btnIncr.disabled = false;
            btnIncr.textContent = "扫描新增";
        },
    });
}

function triggerScanFromWall() {
    const btn = document.getElementById("btn-rescan");
    const grid = document.getElementById("poster-grid");

    btn.disabled = true;
    btn.textContent = "⏳ 扫描中...";
    grid.classList.add("loading");
    showToast("正在扫描媒体库...", "info");

    startScan({
        onProgress(_evt) {
            btn.textContent = "⏳ 扫描中...";
        },
        onDone(stats) {
            const movies = stats.total_movies !== undefined ? stats.total_movies : (stats.total || 0);
            const shows = stats.total_shows || 0;
            const eps = stats.total_episodes || 0;
            const msg = `扫描完成！电影 ${movies} 部，电视剧 ${shows} 部，单集 ${eps} 集` +
                (stats.deleted ? `，清理 ${stats.deleted} 条` : "");
            showToast(msg, "success");
            btn.disabled = false;
            btn.textContent = "⟳ 重新扫描";
            grid.classList.remove("loading");
            loadGenres();
            loadPosterWall();
        },
        onError(msg) {
            showToast(`扫描失败: ${msg}`, "error");
            btn.disabled = false;
            btn.textContent = "⟳ 重新扫描";
            grid.classList.remove("loading");
        },
    });
}

function showToast(message, type = "info") {
    const toast = document.getElementById("scan-toast");
    toast.textContent = message;
    toast.className = `scan-toast toast-${type}`;
    clearTimeout(window._toastTimer);
    window._toastTimer = setTimeout(() => {
        toast.classList.add("hidden");
    }, 4000);
}

// ============================================================================
// 收藏筛选（顶部按钮）
// ============================================================================

function toggleFavoritesFilter() {
    favoritesOnly = !favoritesOnly;
    const filter = favoritesOnly ? "favorite" : "all";
    setSidebarFilter(filter);
}

// ============================================================================
// Fanart 背景
// ============================================================================

function setWallFanart(itemId, mediaType) {
    const bg = document.getElementById("bg-layer");
    if (itemId) {
        const type = mediaType === "movie" || mediaType === "tvshow" ? mediaType : "movie";
        const url = `/api/${type}/${itemId}/fanart`;
        bg.style.backgroundImage = `
            linear-gradient(to bottom,
                rgba(10,10,10,0.55) 0%,
                rgba(10,10,10,0.68) 40%,
                rgba(10,10,10,0.84) 75%,
                rgba(10,10,10,0.96) 100%
            ),
            url(${url})
        `.replace(/\s+/g, " ").trim();
        bg.style.backgroundColor = "transparent";
    } else {
        bg.style.backgroundImage = "";
        bg.style.backgroundColor = "";
    }
}

function setRandomWallFanart(items) {
    const withFanart = items.filter((m) => m.fanart_path);
    if (withFanart.length > 0) {
        const pick = withFanart[Math.floor(Math.random() * withFanart.length)];
        const type = pick.media_type === "movie" ? "movie" : "show";
        setWallFanart(pick.id, type);
    }
}

function clearWallFanart() {
    const bg = document.getElementById("bg-layer");
    bg.style.backgroundImage = "";
    bg.style.backgroundColor = "var(--bg-primary)";
}

function setFanartBackground(movie) {
    const bg = document.getElementById("bg-layer");
    if (movie.fanart_path) {
        const url = `/api/movie/${movie.id}/fanart`;
        bg.style.backgroundImage = `
            linear-gradient(to bottom,
                rgba(10,10,10,0.55) 0%,
                rgba(10,10,10,0.68) 40%,
                rgba(10,10,10,0.84) 75%,
                rgba(10,10,10,0.96) 100%
            ),
            url(${url})
        `.replace(/\s+/g, " ").trim();
        bg.style.backgroundColor = "transparent";
    } else {
        bg.style.backgroundImage = "";
        bg.style.backgroundColor = "var(--bg-primary)";
    }
}

function setTVShowFanartBackground(show) {
    const bg = document.getElementById("bg-layer");
    if (show.fanart_path) {
        const url = `/api/show/${show.id}/fanart`;
        bg.style.backgroundImage = `
            linear-gradient(to bottom,
                rgba(10,10,10,0.55) 0%,
                rgba(10,10,10,0.68) 40%,
                rgba(10,10,10,0.84) 75%,
                rgba(10,10,10,0.96) 100%
            ),
            url(${url})
        `.replace(/\s+/g, " ").trim();
        bg.style.backgroundColor = "transparent";
    } else {
        bg.style.backgroundImage = "";
        bg.style.backgroundColor = "var(--bg-primary)";
    }
}

// ============================================================================
// 侧边栏收起/展开
// ============================================================================

function toggleSidebar() {
    const sidebar = document.getElementById("sidebar");
    const toggle = document.getElementById("sidebar-toggle");
    sidebar.classList.toggle("collapsed");
    const collapsed = sidebar.classList.contains("collapsed");
    toggle.innerHTML = collapsed ? "&#9654;" : "&#9664;";
    toggle.title = collapsed ? "展开侧边栏" : "收起侧边栏";
    try { localStorage.setItem("sidebar-collapsed", collapsed ? "1" : "0"); } catch (_) {}
}

// ============================================================================
// 初始化
// ============================================================================

function init() {
    // 恢复侧边栏状态
    try {
        if (localStorage.getItem("sidebar-collapsed") === "1") {
            const sidebar = document.getElementById("sidebar");
            const toggle = document.getElementById("sidebar-toggle");
            sidebar.classList.add("collapsed");
            toggle.innerHTML = "&#9654;";
            toggle.title = "展开侧边栏";
        }
    } catch (_) {}

    // 侧边栏收起按钮
    document.getElementById("sidebar-toggle").addEventListener("click", toggleSidebar);
    // 侧边栏筛选按钮
    document.querySelectorAll(".sidebar-btn").forEach((btn) => {
        btn.addEventListener("click", () => {
            const filter = btn.dataset.filter;
            setSidebarFilter(filter);
        });
    });

    // 导航标签
    document.querySelectorAll(".nav-tab").forEach((tab) => {
        tab.addEventListener("click", () => {
            const view = tab.dataset.view;
            switchView(view);
            if (view === "home") loadPosterWall();
            else if (view === "settings") loadSettings();
        });
    });

    // 返回按钮
    document.getElementById("btn-back").addEventListener("click", () => {
        switchView("home");
        loadPosterWall();
    });
    document.getElementById("btn-tv-back").addEventListener("click", () => {
        switchView("home");
        loadPosterWall();
    });

    // 工具栏
    document.getElementById("sort-select").addEventListener("change", loadPosterWall);
    document.getElementById("genre-select").addEventListener("change", loadPosterWall);
    document.getElementById("btn-rescan").addEventListener("click", triggerScanFromWall);

    // 搜索
    document.getElementById("search-input").addEventListener("input", handleSearchInput);
    document.getElementById("btn-search-clear").addEventListener("click", clearSearch);

    // 已看/未看筛选按钮
    document.querySelectorAll(".sidebar-watched").forEach((btn) => {
        btn.addEventListener("click", () => {
            document.querySelectorAll(".sidebar-watched").forEach((b) => b.classList.remove("active"));
            btn.classList.add("active");
            currentWatched = btn.dataset.watched;
            loadPosterWall();
        });
    });

    // 收藏筛选按钮
    document.getElementById("btn-nav-fav").addEventListener("click", toggleFavoritesFilter);

    // 设置页
    document.getElementById("btn-add-root").addEventListener("click", addMediaRoot);
    document.getElementById("btn-browse-folder").addEventListener("click", browseFolder);
    document.getElementById("btn-save-player").addEventListener("click", savePlayerPath);
    document.getElementById("btn-scan").addEventListener("click", triggerScan);
    document.getElementById("btn-scan-incr").addEventListener("click", triggerScanIncremental);

    // 键盘快捷键
    document.getElementById("input-player-path").addEventListener("keydown", (e) => {
        if (e.key === "Enter") savePlayerPath();
    });
    document.getElementById("input-media-root").addEventListener("keydown", (e) => {
        if (e.key === "Enter") addMediaRoot();
    });

    // 初始加载
    loadGenres();
    loadPosterWall();
}

async function loadGenres() {
    try {
        const data = await apiGet(`${API_BASE}/genres`);
        const select = document.getElementById("genre-select");
        const currentVal = select.value;
        select.innerHTML = '<option value="">全部类型</option>';
        (data.genres || []).forEach((g) => {
            const opt = document.createElement("option");
            opt.value = g;
            opt.textContent = g;
            select.appendChild(opt);
        });
        select.value = currentVal;
    } catch (err) {
        console.error("加载类型列表失败:", err);
    }
}

document.addEventListener("DOMContentLoaded", init);
