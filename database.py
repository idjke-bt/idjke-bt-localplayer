"""
database.py — SQLite 数据库模块
负责数据库初始化、媒体库表与设置表的 CRUD 操作。
"""

import sqlite3
import json
import os
from datetime import datetime

# 数据库文件路径，默认放在项目根目录
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "localplayer.db")

# =============================================================================
# 数据库连接
# =============================================================================


def get_connection():
    """获取数据库连接（自动启用 WAL 模式和行工厂）。"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# =============================================================================
# 初始化
# =============================================================================


def init_db():
    """初始化数据库：创建 movies 表和 settings 表（如不存在）。"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS movies (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            folder_path     TEXT    NOT NULL UNIQUE,       -- 视频文件夹的绝对路径，用作去重键
            title           TEXT    NOT NULL,               -- 影片标题
            original_title  TEXT    DEFAULT '',             -- 原名
            year            TEXT    DEFAULT '',             -- 年份
            plot            TEXT    DEFAULT '',             -- 简介
            rating          TEXT    DEFAULT '',             -- 评分
            genre           TEXT    DEFAULT '',             -- 类型（逗号分隔）
            poster_path     TEXT    DEFAULT '',             -- 海报图片绝对路径
            fanart_path     TEXT    DEFAULT '',             -- 背景图片绝对路径
            video_path      TEXT    DEFAULT '',             -- 视频文件绝对路径
            director        TEXT    DEFAULT '',             -- 导演
            writer          TEXT    DEFAULT '',             -- 编剧
            actors          TEXT    DEFAULT '',             -- 演员（JSON 数组）
            runtime         TEXT    DEFAULT '',             -- 时长（分钟）
            is_watched      INTEGER DEFAULT 0,             -- 是否已看 (0/1)
            is_favorite     INTEGER DEFAULT 0,             -- 是否收藏 (0/1)
            last_played_time TEXT   DEFAULT NULL,           -- 上次播放时间 (ISO格式)
            play_progress   INTEGER DEFAULT 0,             -- 播放进度 (秒)
            created_at      TEXT    NOT NULL,               -- 记录创建时间
            updated_at      TEXT    NOT NULL                -- 记录更新时间
        )
        """
    )

    # 兼容旧库：为新字段添加列（如不存在）
    new_columns = {
        "director": "TEXT DEFAULT ''",
        "writer": "TEXT DEFAULT ''",
        "actors": "TEXT DEFAULT ''",
        "runtime": "TEXT DEFAULT ''",
    }
    existing_cols = {row[1] for row in cursor.execute("PRAGMA table_info(movies)")}
    for col_name, col_def in new_columns.items():
        if col_name not in existing_cols:
            cursor.execute(f"ALTER TABLE movies ADD COLUMN {col_name} {col_def}")

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,   -- 设置项名称
            value TEXT NOT NULL       -- 设置项值（JSON 字符串或普通字符串）
        )
        """
    )

    # 初始化默认设置（仅在不存在时写入）
    defaults = {
        "media_roots": json.dumps([], ensure_ascii=True),
        "player_path": r"D:\tools\mpv-lazy\mpv-lazy.exe",
    }
    for key, value in defaults.items():
        cursor.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
            (key, value),
        )

    conn.commit()
    conn.close()


# =============================================================================
# 电影 CRUD
# =============================================================================


def get_movies(sort_by="title", genre=None):
    """
    获取所有电影列表，支持排序和类型筛选。

    Args:
        sort_by: 排序字段，可选 "title", "year", "rating"
        genre: 类型筛选字符串（大小写不敏感模糊匹配），为 None 则不过滤

    Returns:
        list[dict]: 电影信息字典列表
    """
    # 排序字段白名单，防止 SQL 注入
    allowed_sort = {
        "title": "title COLLATE NOCASE ASC",
        "year": "year DESC",
        "rating": "CAST(rating AS REAL) DESC",
    }
    order_clause = allowed_sort.get(sort_by, "title COLLATE NOCASE ASC")

    conn = get_connection()
    if genre:
        rows = conn.execute(
            f"SELECT * FROM movies WHERE genre LIKE ? ORDER BY {order_clause}",
            (f"%{genre}%",),
        ).fetchall()
    else:
        rows = conn.execute(
            f"SELECT * FROM movies ORDER BY {order_clause}"
        ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_movie(movie_id):
    """
    根据 ID 获取单部电影详情。

    Args:
        movie_id: 电影 ID

    Returns:
        dict | None: 电影信息字典，不存在则返回 None
    """
    conn = get_connection()
    row = conn.execute("SELECT * FROM movies WHERE id = ?", (movie_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def upsert_movie(folder_path, data):
    """
    插入或更新电影记录（基于 folder_path 去重）。

    Args:
        folder_path: 视频文件夹绝对路径（唯一键）
        data: 包含 title, original_title, year, plot, rating, genre,
              director, writer, actors, runtime,
              poster_path, fanart_path, video_path 的字典

    Returns:
        int: 受影响行的 id
    """
    conn = get_connection()
    now = datetime.now().isoformat()

    # 序列化演员列表
    actors_json = json.dumps(data.get("actors", []), ensure_ascii=True)

    existing = conn.execute(
        "SELECT id FROM movies WHERE folder_path = ?", (folder_path,)
    ).fetchone()

    if existing:
        # 更新已有记录
        conn.execute(
            """
            UPDATE movies SET
                title          = ?, original_title = ?, year   = ?,
                plot           = ?, rating         = ?, genre  = ?,
                director       = ?, writer         = ?, actors = ?,
                runtime        = ?,
                poster_path    = ?, fanart_path    = ?, video_path = ?,
                updated_at     = ?
            WHERE folder_path = ?
            """,
            (
                data["title"],
                data.get("original_title", ""),
                data.get("year", ""),
                data.get("plot", ""),
                data.get("rating", ""),
                data.get("genre", ""),
                data.get("director", ""),
                data.get("writer", ""),
                actors_json,
                data.get("runtime", ""),
                data.get("poster_path", ""),
                data.get("fanart_path", ""),
                data.get("video_path", ""),
                now,
                folder_path,
            ),
        )
        movie_id = existing["id"]
    else:
        # 插入新记录
        cursor = conn.execute(
            """
            INSERT INTO movies (
                folder_path, title, original_title, year, plot,
                rating, genre, director, writer, actors, runtime,
                poster_path, fanart_path, video_path,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                folder_path,
                data["title"],
                data.get("original_title", ""),
                data.get("year", ""),
                data.get("plot", ""),
                data.get("rating", ""),
                data.get("genre", ""),
                data.get("director", ""),
                data.get("writer", ""),
                actors_json,
                data.get("runtime", ""),
                data.get("poster_path", ""),
                data.get("fanart_path", ""),
                data.get("video_path", ""),
                now,
                now,
            ),
        )
        movie_id = cursor.lastrowid

    conn.commit()
    conn.close()
    return movie_id


def update_movie_status(movie_id, field, value):
    """
    更新电影的布尔/整数状态字段。

    Args:
        movie_id: 电影 ID
        field: 字段名（is_watched, is_favorite, play_progress）
        value: 新值
    """
    allowed_fields = {"is_watched", "is_favorite", "play_progress", "last_played_time"}
    if field not in allowed_fields:
        raise ValueError(f"不允许更新的字段: {field}")

    now = datetime.now().isoformat()
    conn = get_connection()

    if field == "last_played_time":
        conn.execute(
            "UPDATE movies SET last_played_time = ?, updated_at = ? WHERE id = ?",
            (value, now, movie_id),
        )
    else:
        conn.execute(
            f"UPDATE movies SET {field} = ?, updated_at = ? WHERE id = ?",
            (value, now, movie_id),
        )
    conn.commit()
    conn.close()


def mark_as_played(movie_id):
    """标记电影为已播放，记录播放时间。"""
    now = datetime.now().isoformat()
    conn = get_connection()
    conn.execute(
        "UPDATE movies SET last_played_time = ?, updated_at = ? WHERE id = ?",
        (now, now, movie_id),
    )
    conn.commit()
    conn.close()


def toggle_watched(movie_id):
    """切换已看/未看状态，返回切换后的新值。"""
    conn = get_connection()
    row = conn.execute(
        "SELECT is_watched FROM movies WHERE id = ?", (movie_id,)
    ).fetchone()
    if row is None:
        conn.close()
        return None
    new_val = 0 if row["is_watched"] else 1
    now = datetime.now().isoformat()
    conn.execute(
        "UPDATE movies SET is_watched = ?, updated_at = ? WHERE id = ?",
        (new_val, now, movie_id),
    )
    conn.commit()
    conn.close()
    return new_val


def toggle_favorite(movie_id):
    """切换收藏/取消收藏状态，返回切换后的新值。"""
    conn = get_connection()
    row = conn.execute(
        "SELECT is_favorite FROM movies WHERE id = ?", (movie_id,)
    ).fetchone()
    if row is None:
        conn.close()
        return None
    new_val = 0 if row["is_favorite"] else 1
    now = datetime.now().isoformat()
    conn.execute(
        "UPDATE movies SET is_favorite = ?, updated_at = ? WHERE id = ?",
        (new_val, now, movie_id),
    )
    conn.commit()
    conn.close()
    return new_val


def delete_movie(movie_id):
    """
    根据 ID 删除单部电影记录。

    Args:
        movie_id: 电影 ID

    Returns:
        bool: 是否成功删除（记录存在并已删除返回 True）
    """
    conn = get_connection()
    row = conn.execute("SELECT id FROM movies WHERE id = ?", (movie_id,)).fetchone()
    if row is None:
        conn.close()
        return False
    conn.execute("DELETE FROM movies WHERE id = ?", (movie_id,))
    conn.commit()
    conn.close()
    return True


# =============================================================================
# 设置 CRUD
# =============================================================================


def get_settings():
    """
    获取所有设置项，返回为字典。

    Returns:
        dict: {key: parsed_value}，media_roots 会自动从 JSON 解析为 list
    """
    conn = get_connection()
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    conn.close()

    settings = {}
    for row in rows:
        key, value = row["key"], row["value"]
        if key == "media_roots":
            try:
                settings[key] = json.loads(value)
            except json.JSONDecodeError:
                settings[key] = []
        else:
            settings[key] = value
    return settings


def get_setting(key):
    """获取单个设置项的值。"""
    conn = get_connection()
    row = conn.execute(
        "SELECT value FROM settings WHERE key = ?", (key,)
    ).fetchone()
    conn.close()
    if row is None:
        return None
    if key == "media_roots":
        try:
            return json.loads(row["value"])
        except json.JSONDecodeError:
            return []
    return row["value"]


def update_setting(key, value):
    """
    更新设置项的值。

    Args:
        key: 设置项名称
        value: 新值（media_roots 接受 list，会自动序列化）
    """
    if key == "media_roots":
        value = json.dumps(value, ensure_ascii=True)
    conn = get_connection()
    conn.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
        (key, str(value) if not isinstance(value, str) else value),
    )
    conn.commit()
    conn.close()


def add_media_root(path):
    """向 media_roots 列表中添加一个路径（去重）。"""
    roots = get_setting("media_roots") or []
    if path not in roots:
        roots.append(path)
        update_setting("media_roots", roots)
    return roots


def remove_media_root(path):
    """从 media_roots 列表中移除一个路径。"""
    roots = get_setting("media_roots") or []
    if path in roots:
        roots.remove(path)
        update_setting("media_roots", roots)
    return roots


def get_genres():
    """
    从数据库中提取所有不重复的类型标签。

    genre 字段为逗号分隔的字符串（如 "动作, 科幻"），
    此函数将其拆分、去重、排序后返回。

    Returns:
        list[str]: 排序后的独立类型列表
    """
    conn = get_connection()
    rows = conn.execute("SELECT genre FROM movies WHERE genre != ''").fetchall()
    conn.close()

    genres = set()
    for row in rows:
        for g in row["genre"].split(","):
            g = g.strip()
            if g:
                genres.add(g)
    return sorted(genres)


# =============================================================================
# 全量刷新辅助
# =============================================================================


def get_all_folder_paths():
    """
    获取数据库中所有电影记录的 folder_path 集合。

    Returns:
        set[str]: 所有已记录的文件夹绝对路径
    """
    conn = get_connection()
    rows = conn.execute("SELECT folder_path FROM movies").fetchall()
    conn.close()
    return {row["folder_path"] for row in rows}


def delete_stale_movies(on_disk_paths):
    """
    删除数据库中存在于磁盘上已不存在的电影记录（全量刷新时使用）。

    Args:
        on_disk_paths: set[str] — 当前磁盘上所有包含视频的文件夹绝对路径

    Returns:
        int: 被删除的记录数
    """
    db_paths = get_all_folder_paths()
    stale = db_paths - on_disk_paths
    if not stale:
        return 0

    conn = get_connection()
    for path in stale:
        conn.execute("DELETE FROM movies WHERE folder_path = ?", (path,))
    conn.commit()
    conn.close()
    return len(stale)
