"""
app.py — Flask 主应用
提供 REST API 路由、静态文件服务、启动入口。
仅监听 127.0.0.1，不对局域网暴露。
"""

import json
import logging
import os
import queue
import subprocess
import sys
import threading
import webbrowser
from threading import Timer

from flask import Flask, Response, jsonify, request, send_file, send_from_directory, make_response

import database
import scanner

# ---------------------------------------------------------------------------
# 配置加载
# ---------------------------------------------------------------------------

try:
    from config import (
        LOG_DIR as _CFG_LOG_DIR,
        FLASK_HOST as _CFG_FLASK_HOST,
        FLASK_PORT as _CFG_FLASK_PORT,
        PLAYER_CANDIDATES as _CFG_PLAYER_CANDIDATES,
        DEFAULT_PLAYER_PATH as _CFG_DEFAULT_PLAYER_PATH,
    )
except ImportError:
    _CFG_LOG_DIR = None
    _CFG_FLASK_HOST = "127.0.0.1"
    _CFG_FLASK_PORT = 5000
    _CFG_PLAYER_CANDIDATES = None
    _CFG_DEFAULT_PLAYER_PATH = None

# ---------------------------------------------------------------------------
# 日志系统
# ---------------------------------------------------------------------------

LOG_DIR = _CFG_LOG_DIR or os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(os.path.join(LOG_DIR, "app.log"), encoding="utf-8"),
    ],
)
# 单独的 ERROR 级别日志文件
error_handler = logging.FileHandler(os.path.join(LOG_DIR, "error.log"), encoding="utf-8")
error_handler.setLevel(logging.ERROR)
error_handler.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
))
logging.getLogger().addHandler(error_handler)

logger = logging.getLogger("app")

# ---------------------------------------------------------------------------
# Flask 应用初始化
# ---------------------------------------------------------------------------

app = Flask(__name__)

# 确保 JSON 响应使用 UTF-8，中文不转义为 \uXXXX
app.config["JSON_AS_ASCII"] = False
app.config["JSONIFY_MIMETYPE"] = "application/json; charset=utf-8"

# 确保首次启动时数据库已初始化
with app.app_context():
    database.init_db()


# 请求后强制 UTF-8 响应头
@app.after_request
def set_response_encoding(response):
    response.headers["Content-Type"] = response.content_type + "; charset=utf-8"
    return response


@app.after_request
def set_cache_headers(response):
    """为图片响应设置 Cache-Control 头，防止浏览器缓存过期图片。"""
    ct = response.content_type or ""
    if ct.startswith("image/"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


# ---------------------------------------------------------------------------
# 静态文件路由
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    """返回单页应用的主 HTML 页面。"""
    return send_from_directory("templates", "index.html")


@app.route("/static/<path:filename>")
def static_files(filename):
    """提供静态文件服务（CSS、JS）。"""
    return send_from_directory("static", filename)


@app.route("/poster")
def serve_poster():
    """
    提供海报图的本地文件访问。
    通过查询参数 ?path= 传入绝对路径，Flask 读取并返回图片流。
    """
    real_path = request.args.get("path", "")
    logger.debug("海报请求: path=%s, exists=%s", real_path, os.path.isfile(real_path))
    if not real_path or not os.path.isfile(real_path):
        return "", 404
    return send_file(real_path)

@app.route("/fanart")
def serve_fanart():
    """
    提供背景图的本地文件访问。
    通过查询参数 ?path= 传入绝对路径。
    """
    real_path = request.args.get("path", "")
    logger.debug("背景图请求: path=%s, exists=%s", real_path, os.path.isfile(real_path))
    if not real_path or not os.path.isfile(real_path):
        return "", 404
    return send_file(real_path)


# =============================================================================
# ID 驱动的图片路由：按媒体类型区分，避免电影/电视剧 ID 冲突
# =============================================================================

@app.route("/api/movie/<int:movie_id>/poster")
def serve_movie_poster(movie_id):
    """通过电影 ID 提供海报。"""
    row = database.get_movie(movie_id)
    if row and row.get("poster_path"):
        path = row["poster_path"]
        if os.path.isfile(path):
            logger.info("电影海报: id=%d, path=%s", movie_id, path)
            response = send_file(path)
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            return response
    logger.warning("电影海报未找到: id=%d", movie_id)
    return "", 404


@app.route("/api/movie/<int:movie_id>/fanart")
def serve_movie_fanart(movie_id):
    """通过电影 ID 提供背景图。"""
    row = database.get_movie(movie_id)
    if row and row.get("fanart_path"):
        path = row["fanart_path"]
        if os.path.isfile(path):
            logger.info("电影背景图: id=%d, path=%s", movie_id, path)
            response = send_file(path)
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            return response
    logger.warning("电影背景图未找到: id=%d", movie_id)
    return "", 404


@app.route("/api/show/<int:show_id>/poster")
def serve_show_poster(show_id):
    """通过电视剧 ID 提供海报。"""
    row = database.get_show(show_id)
    if row and row.get("poster_path"):
        path = row["poster_path"]
        if os.path.isfile(path):
            logger.info("电视剧海报: id=%d, path=%s", show_id, path)
            response = send_file(path)
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            return response
    logger.warning("电视剧海报未找到: id=%d", show_id)
    return "", 404


@app.route("/api/show/<int:show_id>/fanart")
def serve_show_fanart(show_id):
    """通过电视剧 ID 提供背景图。"""
    row = database.get_show(show_id)
    if row and row.get("fanart_path"):
        path = row["fanart_path"]
        if os.path.isfile(path):
            logger.info("电视剧背景图: id=%d, path=%s", show_id, path)
            response = send_file(path)
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            return response
    logger.warning("电视剧背景图未找到: id=%d", show_id)
    return "", 404


@app.route("/api/thumb/<int:episode_id>")
def serve_thumb_by_id(episode_id):
    """通过单集 ID 提供缩略图。"""
    row = database.get_episode(episode_id)
    if row and row.get("thumb_path"):
        path = row["thumb_path"]
        if os.path.isfile(path):
            logger.info("缩略图: id=%d, path=%s", episode_id, path)
            response = send_file(path)
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            return response
    logger.warning("缩略图未找到: id=%d", episode_id)
    return "", 404
# 播放器路径自动检测
# ===========================================================================

# 常见播放器安装路径（按优先级排列）
PLAYER_CANDIDATES = _CFG_PLAYER_CANDIDATES or [
    r"D:\tools\mpv-lazy\mpv-lazy.exe",
    r"C:\tools\mpv-lazy\mpv-lazy.exe",
    r"C:\Program Files\mpv\mpv.exe",
    r"C:\Program Files (x86)\mpv\mpv.exe",
    r"D:\Program Files\mpv\mpv.exe",
    # VLC
    r"C:\Program Files\VideoLAN\VLC\vlc.exe",
    r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe",
    r"D:\Program Files\VideoLAN\VLC\vlc.exe",
    # PotPlayer
    r"C:\Program Files\DAUM\PotPlayer\PotPlayerMini64.exe",
    r"C:\Program Files (x86)\DAUM\PotPlayer\PotPlayerMini.exe",
    r"D:\Program Files\DAUM\PotPlayer\PotPlayerMini64.exe",
]


def detect_player():
    """在常见路径中检测已安装的播放器，返回第一个存在的路径。"""
    for candidate in PLAYER_CANDIDATES:
        if os.path.isfile(candidate):
            return candidate
    return PLAYER_CANDIDATES[0]  # 回退到默认值


def _get_player_args(player_path):
    """
    根据播放器类型返回全屏/置顶的 CLI 参数。
    """
    basename = os.path.basename(player_path).lower()
    if "mpv" in basename:
        return ["--ontop", "--fullscreen"]
    if "vlc" in basename:
        return ["--fullscreen", "--video-on-top"]
    if "potplayer" in basename or "potplayermini" in basename:
        return ["/fullscreen"]
    return []


# ===========================================================================
# REST API — 电影相关
# ===========================================================================


@app.route("/api/movies", methods=["GET"])
def api_get_movies():
    """
    获取所有电影列表。
    Query: sort=title|year|rating, genre=类型筛选, favorite=true|false, search=关键字
    Returns: {"movies": [...], "count": int}
    """
    sort_by = request.args.get("sort", "title")
    genre = request.args.get("genre", None)
    favorite_only = request.args.get("favorite", "").lower() == "true"
    search = request.args.get("search", None)
    watched = request.args.get("watched", None)
    if watched is not None:
        watched = watched.lower() == "true"
    movies = database.get_movies(sort_by=sort_by, genre=genre, favorite_only=favorite_only, search=search, watched=watched)
    return jsonify({"movies": movies, "count": len(movies)})


@app.route("/api/movies/<int:movie_id>", methods=["GET"])
def api_get_movie(movie_id):
    """获取单部电影详情。"""
    movie = database.get_movie(movie_id)
    if movie is None:
        return jsonify({"error": "电影不存在"}), 404
    return jsonify(movie)


@app.route("/api/movies/<int:movie_id>/play", methods=["POST"])
def api_play_movie(movie_id):
    """
    触发外部播放器播放指定电影。
    通过 subprocess.Popen 启动播放器并传入视频路径，
    启动后立即返回，不等待播放器进程结束。
    """
    movie = database.get_movie(movie_id)
    if movie is None:
        return jsonify({"error": "电影不存在"}), 404

    video_path = movie.get("video_path", "")
    if not video_path or not os.path.isfile(video_path):
        return jsonify({"error": f"视频文件不存在: {video_path}"}), 404

    player_path = database.get_setting("player_path")
    if not player_path or not os.path.isfile(player_path):
        # 尝试自动检测
        auto_player = detect_player()
        if os.path.isfile(auto_player):
            database.update_setting("player_path", auto_player)
            player_path = auto_player
        else:
            return jsonify({
                "error": f"播放器未找到。请在设置中配置播放器路径，或安装 mpv/vlc/potplayer 到默认路径。当前尝试: {player_path}"
            }), 500

    try:
        args = [player_path] + _get_player_args(player_path) + [video_path]
        subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        database.mark_as_played(movie_id)
        logger.info("播放电影: %s (player=%s)", movie['title'], player_path)
        return jsonify({"status": "ok", "message": f"正在播放: {movie['title']}", "player": player_path})
    except Exception as e:
        return jsonify({"error": f"播放器启动失败 ({player_path}): {str(e)}"}), 500


@app.route("/api/movies/<int:movie_id>/watched", methods=["POST"])
def api_toggle_watched(movie_id):
    """切换已看/未看状态。"""
    new_val = database.toggle_watched(movie_id)
    if new_val is None:
        return jsonify({"error": "电影不存在"}), 404
    return jsonify({"movie_id": movie_id, "is_watched": new_val})


@app.route("/api/movies/<int:movie_id>/favorite", methods=["POST"])
def api_toggle_favorite(movie_id):
    """切换收藏/取消收藏状态。"""
    new_val = database.toggle_favorite(movie_id)
    if new_val is None:
        return jsonify({"error": "电影不存在"}), 404
    return jsonify({"movie_id": movie_id, "is_favorite": new_val})


@app.route("/api/movies/<int:movie_id>", methods=["DELETE"])
def api_delete_movie(movie_id):
    """删除单部电影记录（不删除实际文件）。"""
    deleted = database.delete_movie(movie_id)
    if not deleted:
        return jsonify({"error": "电影不存在"}), 404
    return jsonify({"status": "ok", "message": "已删除"})


# ===========================================================================
# REST API — 电视剧相关
# ===========================================================================


@app.route("/api/shows", methods=["GET"])
def api_get_shows():
    """
    获取所有电视剧列表。
    Query: sort=title|year|rating, genre=类型筛选, favorite=true|false, search=关键字, watched=true|false
    """
    sort_by = request.args.get("sort", "title")
    genre = request.args.get("genre", None)
    favorite_only = request.args.get("favorite", "").lower() == "true"
    search = request.args.get("search", None)
    watched = request.args.get("watched", None)
    if watched is not None:
        watched = watched.lower() == "true"
    shows = database.get_shows(sort_by=sort_by, genre=genre, favorite_only=favorite_only, search=search, watched=watched)
    return jsonify({"shows": shows, "count": len(shows)})


@app.route("/api/shows/<int:show_id>", methods=["GET"])
def api_get_show(show_id):
    """获取单部电视剧详情。"""
    show = database.get_show(show_id)
    if show is None:
        return jsonify({"error": "电视剧不存在"}), 404
    return jsonify(show)


@app.route("/api/shows/<int:show_id>/episodes", methods=["GET"])
def api_get_show_episodes(show_id):
    """获取某电视剧的所有单集，按季分组。"""
    show = database.get_show(show_id)
    if show is None:
        return jsonify({"error": "电视剧不存在"}), 404
    season = request.args.get("season")
    season = int(season) if season else None
    episodes = database.get_episodes(show_id, season=season)
    seasons = database.get_show_seasons(show_id)
    return jsonify({"show": show, "episodes": episodes, "seasons": seasons})


@app.route("/api/shows/<int:show_id>/favorite", methods=["POST"])
def api_toggle_show_favorite(show_id):
    """切换电视剧收藏状态。"""
    new_val = database.toggle_show_favorite(show_id)
    if new_val is None:
        return jsonify({"error": "电视剧不存在"}), 404
    return jsonify({"show_id": show_id, "is_favorite": new_val})


@app.route("/api/shows/<int:show_id>", methods=["DELETE"])
def api_delete_show(show_id):
    """删除电视剧及其所有单集记录。"""
    deleted = database.delete_show(show_id)
    if not deleted:
        return jsonify({"error": "电视剧不存在"}), 404
    return jsonify({"status": "ok", "message": "已删除"})


@app.route("/api/episodes/<int:episode_id>/watched", methods=["POST"])
def api_toggle_episode_watched(episode_id):
    """切换单集已看/未看状态。"""
    new_val = database.toggle_episode_watched(episode_id)
    if new_val is None:
        return jsonify({"error": "单集不存在"}), 404
    return jsonify({"episode_id": episode_id, "is_watched": new_val})


@app.route("/api/episodes/<int:episode_id>/play", methods=["POST"])
def api_play_episode(episode_id):
    """使用外部播放器播放指定单集。"""
    episode = database.get_episode(episode_id)
    if episode is None:
        return jsonify({"error": "单集不存在"}), 404

    video_path = episode.get("video_path", "")
    if not video_path or not os.path.isfile(video_path):
        return jsonify({"error": f"视频文件不存在: {video_path}"}), 404

    player_path = database.get_setting("player_path")
    if not player_path or not os.path.isfile(player_path):
        auto_player = detect_player()
        if os.path.isfile(auto_player):
            database.update_setting("player_path", auto_player)
            player_path = auto_player
        else:
            return jsonify({
                "error": f"播放器未找到。请在设置中配置播放器路径。"
            }), 500

    try:
        args = [player_path] + _get_player_args(player_path) + [video_path]
        subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # 标记为已看
        database.toggle_episode_watched(episode_id)
        logger.info("播放单集: %s (player=%s)", episode.get('title', ''), player_path)
        return jsonify({"status": "ok", "message": f"正在播放: {episode.get('title', '')}", "player": player_path})
    except Exception as e:
        return jsonify({"error": f"播放器启动失败: {str(e)}"}), 500


# ===========================================================================
# REST API — 电视剧批量标记已看
# ===========================================================================


@app.route("/api/shows/<int:show_id>/watched", methods=["POST"])
def api_toggle_show_watched(show_id):
    """切换整部电视剧所有单集的已看/未看状态。"""
    show = database.get_show(show_id)
    if show is None:
        return jsonify({"error": "电视剧不存在"}), 404

    all_watched = database.is_show_all_watched(show_id)
    count = database.mark_show_watched(show_id, not all_watched)
    return jsonify({"show_id": show_id, "all_watched": not all_watched, "updated_count": count})


@app.route("/api/shows/<int:show_id>/seasons/<int:season>/watched", methods=["POST"])
def api_toggle_season_watched(show_id, season):
    """切换某季所有单集的已看/未看状态。"""
    show = database.get_show(show_id)
    if show is None:
        return jsonify({"error": "电视剧不存在"}), 404

    episodes = database.get_episodes(show_id, season=season)
    if not episodes:
        return jsonify({"error": "该季没有单集"}), 404

    all_watched = all(ep["is_watched"] for ep in episodes)
    count = database.mark_season_watched(show_id, season, not all_watched)
    return jsonify({"show_id": show_id, "season": season, "all_watched": not all_watched, "updated_count": count})


# ===========================================================================
# REST API — 文件夹浏览
# ===========================================================================


@app.route("/api/browse-folder", methods=["POST"])
def api_browse_folder():
    """调用系统原生文件夹选择对话框，返回用户选中的路径。"""
    try:
        ps_script = (
            "Add-Type -AssemblyName System.Windows.Forms; "
            "$f = New-Object System.Windows.Forms.FolderBrowserDialog; "
            "$f.Description = '选择媒体库根目录'; "
            "$f.ShowNewFolderButton = $true; "
            "if ($f.ShowDialog() -eq 'OK') { $f.SelectedPath } else { '' }"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            error_detail = result.stderr.strip() or "未知错误"
            logger.error("PowerShell 文件夹选择失败: %s", error_detail)
            return jsonify({"error": f"PowerShell 执行失败: {error_detail}"}), 500
        selected = result.stdout.strip()
        if selected and os.path.isdir(selected):
            return jsonify({"path": selected})
        return jsonify({"path": ""})
    except subprocess.TimeoutExpired:
        return jsonify({"error": "文件夹选择超时，请手动输入路径"}), 500
    except Exception as e:
        logger.error("文件夹选择异常: %s", e)
        return jsonify({"error": f"文件夹选择失败: {str(e)}"}), 500


# ===========================================================================
# REST API — 统一媒体查询（供侧边栏筛选使用）
# ===========================================================================


@app.route("/api/all_media", methods=["GET"])
def api_get_all_media():
    """获取所有媒体（电影+电视剧），用于侧边栏筛选。"""
    sort_by = request.args.get("sort", "title")
    genre = request.args.get("genre", None)
    favorite_only = request.args.get("favorite", "").lower() == "true"
    media_type = request.args.get("type", None)
    search = request.args.get("search", None)
    watched = request.args.get("watched", None)
    if watched is not None:
        watched = watched.lower() == "true"
    all_items = database.get_all_media(
        sort_by=sort_by, genre=genre, favorite_only=favorite_only, search=search, watched=watched
    )
    if media_type:
        all_items = [m for m in all_items if m.get("media_type") == media_type]
    return jsonify({"media": all_items, "count": len(all_items)})


# ===========================================================================
# REST API — 扫描（含 SSE 进度推送）
# ===========================================================================

# 扫描进度全局状态
_scan_queue = None
_scan_thread = None


@app.route("/api/genres", methods=["GET"])
def api_get_genres():
    """获取所有不重复的类型标签列表。"""
    genres = database.get_genres()
    return jsonify({"genres": genres})


@app.route("/api/reset", methods=["POST"])
def api_reset():
    """重置数据库：清空所有电影、电视剧、单集记录（保留设置）。"""
    try:
        database.reset_all_media()
        logger.info("数据库已重置（电影、电视剧、单集已清空）")
        return jsonify({"status": "ok", "message": "数据库已重置，请重新扫描"})
    except Exception as e:
        logger.error("重置数据库失败: %s", str(e))
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/scan", methods=["POST"])
def api_scan():
    """触发媒体库扫描（后台线程 + SSE 进度）。
    Query: mode=full (默认全量刷新) | mode=incremental (仅扫描新增文件夹)
    """
    global _scan_queue, _scan_thread

    mode = request.args.get("mode", "full")

    if _scan_thread and _scan_thread.is_alive():
        return jsonify({"error": "扫描正在进行中，请等待完成"}), 409

    _scan_queue = queue.Queue()

    def progress_callback(status, detail):
        _scan_queue.put({"event": "progress", "status": status, "detail": detail})

    def run_scan():
        try:
            if mode == "incremental":
                stats = scanner.scan_all_roots(
                    progress_callback=progress_callback, full_refresh=False, incremental=True
                )
                _scan_queue.put({"event": "done", "stats": stats})
                logger.info("增量扫描完成: %s", stats)
            else:
                stats = scanner.scan_all_roots(progress_callback=progress_callback, full_refresh=True)
                _scan_queue.put({"event": "done", "stats": stats})
                logger.info("全量扫描完成: %s", stats)
        except Exception as e:
            _scan_queue.put({"event": "error", "detail": str(e)})
            logger.error("扫描失败: %s", e, exc_info=True)

    _scan_thread = threading.Thread(target=run_scan, daemon=True)
    _scan_thread.start()
    logger.info("开始%s扫描", "增量" if mode == "incremental" else "全量")
    return jsonify({"status": "started", "mode": mode})


@app.route("/api/scan/progress")
def api_scan_progress():
    """SSE 端点：推送扫描进度事件。"""
    def generate():
        while True:
            try:
                event = _scan_queue.get(timeout=30) if _scan_queue else None
                if event is None:
                    yield ": heartbeat\n\n"
                    continue
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                if event.get("event") in ("done", "error"):
                    break
            except queue.Empty:
                yield ": heartbeat\n\n"
    return Response(generate(), mimetype="text/event-stream")


# ===========================================================================
# REST API — 设置
# ===========================================================================


@app.route("/api/settings", methods=["GET"])
def api_get_settings():
    """获取所有设置项。"""
    settings = database.get_settings()
    return jsonify({"settings": settings})


@app.route("/api/settings", methods=["POST"])
def api_update_settings():
    """
    批量更新设置项。
    Request body: {"media_roots": [...], "player_path": "..."}
    """
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "请求体需为有效 JSON"}), 400

    updatable = {"media_roots", "player_path"}
    for key, value in data.items():
        if key in updatable:
            database.update_setting(key, value)

    logger.info("设置已更新: %s", list(data.keys()))
    return jsonify({"status": "ok", "settings": database.get_settings()})


# ===========================================================================
# 启动入口
# ===========================================================================


def open_browser():
    """延迟打开默认浏览器访问本地地址。"""
    webbrowser.open(f"http://{_CFG_FLASK_HOST}:{_CFG_FLASK_PORT}")


if __name__ == "__main__":
    logger.info("LocalPlayer 启动")
    print("=" * 50)
    print("  LocalPlayer — 本地媒体库管理工具")
    print(f"  访问地址: http://{_CFG_FLASK_HOST}:{_CFG_FLASK_PORT}")
    print("  按 Ctrl+C 退出")
    print("=" * 50)

    # 首次启动检测播放器
    current_player = database.get_setting("player_path")
    if not current_player or not os.path.isfile(current_player):
        auto_player = detect_player()
        if os.path.isfile(auto_player):
            database.update_setting("player_path", auto_player)
            print(f"  自动检测到播放器: {auto_player}")
        else:
            print(f"  未检测到播放器，请通过设置页配置播放器路径")

    # 启动后自动打开浏览器
    Timer(1.0, open_browser).start()

    app.run(host=_CFG_FLASK_HOST, port=_CFG_FLASK_PORT, debug=False)
