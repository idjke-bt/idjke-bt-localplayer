/*
 * app.js — LocalPlayer 前端逻辑
 * 海报墙渲染、详情页、设置页、API 调用与交互处理
 */

// ============================================================================
// 配置
// ============================================================================

const API_BASE = "/api";

// ============================================================================
// 全局状态
// ============================================================================

let currentMovieId = null;

// ============================================================================
// 工具函数
// ============================================================================

/** HTML 转义 */
function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
}

/** GET 请求 */
async function apiGet(url) {
    const res = await fetch(url);
    if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.error || `HTTP ${res.status}`);
    }
    return res.json();
}

/** POST 请求 */
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
}

// ============================================================================
// 海报墙
// ============================================================================

async function loadPosterWall() {
    const sortBy = document.getElementById("sort-select").value;
    const genre = document.getElementById("genre-select").value;
    const url = `${API_BASE}/movies?sort=${sortBy}&genre=${encodeURIComponent(genre)}`;

    try {
        const data = await apiGet(url);
        renderPosterGrid(data.movies);
        document.getElementById("movie-count").textContent = `共 ${data.count} 部`;
    } catch (err) {
        console.error("加载电影列表失败:", err);
        document.getElementById("poster-grid").innerHTML =
            '<p style="padding:24px;color:var(--text-secondary)">加载失败，请检查后端是否正常运行。</p>';
    }
}

async function renderPosterGrid(movies) {
    const grid = document.getElementById("poster-grid");
    if (!movies.length) {
        // 检查是否配置了媒体根目录
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
                    <p>已配置媒体根目录，但尚未扫描到任何电影。</p>
                    <p class="welcome-hint">请确认目录中包含视频文件 (mkv/mp4/avi)，然后执行扫描。</p>
                    <button class="welcome-btn" onclick="triggerScanFromWall()">立即扫描</button>
                </div>`;
        } else {
            grid.innerHTML = `
                <div class="welcome-card">
                    <div class="welcome-icon">📂</div>
                    <h2>欢迎使用 LocalPlayer</h2>
                    <p>开始使用前，请先配置媒体库根目录。</p>
                    <p class="welcome-hint">将你存放电影的文件夹路径添加到设置中，然后执行扫描即可建立媒体库。</p>
                    <button class="welcome-btn" onclick="switchView('settings');loadSettings();">前往设置</button>
                </div>`;
        }
        return;
    }

    grid.innerHTML = movies.map((m) => {
        const posterUrl = m.poster_path
            ? `/poster?path=${encodeURIComponent(m.poster_path)}`
            : "";

        // 图片或占位符
        const imgHtml = posterUrl
            ? `<div class="card-img-container"><img class="card-img" src="${posterUrl}" alt="${escapeHtml(m.title)}" loading="lazy" onerror="this.outerHTML='<div class=\\'card-img-placeholder\\'>&#127916;</div>'"></div>`
            : `<div class="card-img-placeholder">&#127916;</div>`;

        // 角标
        let badges = "";
        if (!m.is_watched) badges += '<span class="badge badge-new">NEW</span>';
        if (m.is_watched) badges += '<span class="badge badge-watched">&#10003; 已看</span>';
        if (m.is_favorite) badges += '<span class="badge badge-favorite">&#9829;</span>';

        return `
        <div class="poster-card" data-id="${m.id}" onclick="event.stopPropagation(); openDetail(${m.id});" title="${escapeHtml(m.title)}">
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
// 详情页
// ============================================================================

async function openDetail(movieId) {
    currentMovieId = movieId;
    switchView("detail");
    // 立即显示加载状态
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

function renderDetail(movie) {
    const container = document.getElementById("detail-container");
    const posterUrl = movie.poster_path
        ? `/poster?path=${encodeURIComponent(movie.poster_path)}`
        : "";

    const watchedText = movie.is_watched ? "已看" : "未看";
    const favClass = movie.is_favorite ? "favorited" : "";

    // 演员列表：解析 JSON 字符串
    let actors = [];
    try {
        actors = typeof movie.actors === "string" ? JSON.parse(movie.actors) : (movie.actors || []);
    } catch (_) { actors = []; }
    // 只取前 5 位
    const actorNames = actors.slice(0, 5).map((a) => escapeHtml(a.name)).join("、");

    // 时长格式化
    let runtimeStr = "";
    if (movie.runtime) {
        const mins = parseInt(movie.runtime, 10);
        if (!isNaN(mins)) {
            const h = Math.floor(mins / 60);
            const m = mins % 60;
            runtimeStr = h > 0 ? `${h} 小时 ${m} 分钟` : `${m} 分钟`;
        } else {
            runtimeStr = movie.runtime;
        }
    }

    // 类型格式化
    const genreStr = movie.genre ? escapeHtml(movie.genre).replace(/, /g, " / ") : "";

    // 构建元数据行
    const metaLines = [];
    if (movie.director) metaLines.push(`<span class="meta-label">导演</span> ${escapeHtml(movie.director)}`);
    if (movie.writer) metaLines.push(`<span class="meta-label">编剧</span> ${escapeHtml(movie.writer)}`);
    if (actorNames) metaLines.push(`<span class="meta-label">主演</span> ${actorNames}`);
    if (genreStr) metaLines.push(`<span class="meta-label">类型</span> ${genreStr}`);
    if (runtimeStr) metaLines.push(`<span class="meta-label">时长</span> ${runtimeStr}`);

    container.innerHTML = `
        <div class="detail-header">
            ${posterUrl
                ? `<img class="detail-poster" src="${posterUrl}" alt="${escapeHtml(movie.title)}" onerror="this.style.display='none'">`
                : ""}
            <div class="detail-meta">
                <h2 class="detail-title">${escapeHtml(movie.title)}</h2>
                ${movie.original_title ? `<p class="detail-original-title">${escapeHtml(movie.original_title)}</p>` : ""}
                <p class="detail-year">${movie.year || "未知年份"}</p>
                ${movie.rating ? `<p class="detail-rating">&#9733; ${movie.rating}</p>` : ""}
                ${metaLines.length ? `<div class="detail-meta-lines">${metaLines.map((l) => `<p class="detail-meta-line">${l}</p>`).join("")}</div>` : ""}
                <p class="detail-plot">${escapeHtml(movie.plot || "暂无简介")}</p>
                ${movie.last_played_time ? `<p style="color:var(--text-secondary);font-size:13px;">上次播放: ${new Date(movie.last_played_time).toLocaleString("zh-CN")}</p>` : ""}
                <div class="detail-actions">
                    <button class="btn-play" onclick="playMovie(${movie.id})">&#9654; 播放</button>
                    <button class="btn-icon ${movie.is_watched ? 'active' : ''}" onclick="toggleWatched(${movie.id})" title="${watchedText}">
                        &#10003;
                    </button>
                    <button class="btn-icon ${favClass}" onclick="toggleFavorite(${movie.id})" title="收藏">
                        &#9829;
                    </button>
                    <button class="btn-icon btn-delete" onclick="deleteMovie(${movie.id})" title="删除此条目">
                        &#128465;
                    </button>
                </div>
            </div>
        </div>
    `;

    // 设置 fanart 背景
    setFanartBackground(movie);
}

async function playMovie(movieId) {
    const btn = document.querySelector(".btn-play");
    if (btn) { btn.disabled = true; btn.textContent = "启动中..."; }

    try {
        const result = await apiPost(`${API_BASE}/movies/${movieId}/play`);
        if (result.status === "ok") {
            showToast(result.message, "success");
            // 刷新详情显示播放时间
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

function startScan({ onProgress, onDone, onError }) {
    if (_scanEventSource) {
        _scanEventSource.close();
        _scanEventSource = null;
    }

    // 先 POST 触发扫描
    fetch(`${API_BASE}/scan`, { method: "POST" })
        .then((res) => {
            if (res.status === 409) {
                onError("扫描正在进行中，请等待完成");
                return;
            }
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            // 连接 SSE 进度流
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

/** 设置页扫描 — 实时日志 + 完成后自动切回海报墙 */
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
            logDiv.textContent =
                `扫描完成！\n` +
                `共处理: ${stats.total} 部 | ` +
                `新增: ${stats.added} | ` +
                `更新: ${stats.updated} | ` +
                `清理过期: ${stats.deleted || 0}\n` +
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

/** 海报墙扫描 — toast 反馈 + 自动刷新 */
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
            const msg = `扫描完成！找到 ${stats.total} 部` +
                (stats.deleted ? `，清理 ${stats.deleted} 部` : "");
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
// Fanart 背景
// ============================================================================

function setFanartBackground(movie) {
    const view = document.getElementById("view-detail");
    if (movie.fanart_path) {
        const url = `/fanart?path=${encodeURIComponent(movie.fanart_path)}`;
        view.style.backgroundImage = `
            linear-gradient(to bottom,
                rgba(10,10,10,0.65) 0%,
                rgba(10,10,10,0.75) 40%,
                rgba(10,10,10,0.88) 70%,
                rgba(10,10,10,0.97) 100%
            ),
            url(${url})
        `.replace(/\s+/g, " ").trim();
        view.style.backgroundSize = "cover";
        view.style.backgroundPosition = "center top";
        view.style.backgroundRepeat = "no-repeat";
        view.style.backgroundAttachment = "scroll";
        view.classList.add("has-fanart");
    } else {
        view.style.backgroundImage = "";
        view.style.backgroundSize = "";
        view.style.backgroundPosition = "";
        view.style.backgroundRepeat = "";
        view.style.backgroundAttachment = "";
        view.classList.remove("has-fanart");
    }
}

// ============================================================================
// 初始化
// ============================================================================

function init() {
    // 导航标签
    document.querySelectorAll(".nav-tab").forEach((tab) => {
        tab.addEventListener("click", () => {
            const view = tab.dataset.view;
            switchView(view);
            if (view === "home") loadPosterWall();
            else if (view === "settings") loadSettings();
        });
    });

    // 返回海报墙
    document.getElementById("btn-back").addEventListener("click", () => {
        switchView("home");
        loadPosterWall();
    });

    // 工具栏
    document.getElementById("sort-select").addEventListener("change", loadPosterWall);
    document.getElementById("genre-select").addEventListener("change", loadPosterWall);
    document.getElementById("btn-rescan").addEventListener("click", triggerScanFromWall);

    // 设置页
    document.getElementById("btn-add-root").addEventListener("click", addMediaRoot);
    document.getElementById("btn-save-player").addEventListener("click", savePlayerPath);
    document.getElementById("btn-scan").addEventListener("click", triggerScan);

    // 键盘快捷键：Enter 保存
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
