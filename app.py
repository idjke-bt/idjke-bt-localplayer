"""
app.py — Flask 主应用
提供 REST API 路由、静态文件服务、启动入口。
仅监听 127.0.0.1，不对局域网暴露。
"""

import json
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
    if not real_path or not os.path.isfile(real_path):
        return "", 404
    return send_file(real_path)


# ===========================================================================
# 播放器路径自动检测
# ===========================================================================

# 常见播放器安装路径（按优先级排列）
PLAYER_CANDIDATES = [
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


# ===========================================================================
# REST API — 电影相关
# ===========================================================================


@app.route("/api/movies", methods=["GET"])
def api_get_movies():
    """
    获取所有电影列表。
    Query: sort=title|year|rating, genre=类型筛选
    Returns: {"movies": [...], "count": int}
    """
    sort_by = request.args.get("sort", "title")
    genre = request.args.get("genre", None)
    movies = database.get_movies(sort_by=sort_by, genre=genre)
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
        subprocess.Popen(
            [player_path, video_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        database.mark_as_played(movie_id)
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


@app.route("/api/scan", methods=["POST"])
def api_scan():
    """手动触发全量媒体库扫描（后台线程 + SSE 进度）。"""
    global _scan_queue, _scan_thread

    if _scan_thread and _scan_thread.is_alive():
        return jsonify({"error": "扫描正在进行中，请等待完成"}), 409

    _scan_queue = queue.Queue()

    def progress_callback(status, detail):
        _scan_queue.put({"event": "progress", "status": status, "detail": detail})

    def run_scan():
        try:
            stats = scanner.scan_all_roots(progress_callback=progress_callback, full_refresh=True)
            _scan_queue.put({"event": "done", "stats": stats})
        except Exception as e:
            _scan_queue.put({"event": "error", "detail": str(e)})

    _scan_thread = threading.Thread(target=run_scan, daemon=True)
    _scan_thread.start()
    return jsonify({"status": "started"})


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

    return jsonify({"status": "ok", "settings": database.get_settings()})


# ===========================================================================
# 启动入口
# ===========================================================================


def open_browser():
    """延迟打开默认浏览器访问本地地址。"""
    webbrowser.open("http://127.0.0.1:5000")


if __name__ == "__main__":
    print("=" * 50)
    print("  LocalPlayer — 本地媒体库管理工具")
    print("  访问地址: http://127.0.0.1:5000")
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

    app.run(host="127.0.0.1", port=5000, debug=False)
