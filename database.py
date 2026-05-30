"""
database.py — SQLite 数据库模块
负责数据库初始化、电影/电视剧/单集表与设置表的 CRUD 操作。
"""

import sqlite3
import json
import logging
import os
import re
from datetime import datetime

logger = logging.getLogger("database")

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "localplayer.db")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# =============================================================================
# 初始化
# =============================================================================

def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    # --- movies 表 ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS movies (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            folder_path     TEXT    NOT NULL UNIQUE,
            title           TEXT    NOT NULL,
            original_title  TEXT    DEFAULT '',
            year            TEXT    DEFAULT '',
            plot            TEXT    DEFAULT '',
            rating          TEXT    DEFAULT '',
            genre           TEXT    DEFAULT '',
            poster_path     TEXT    DEFAULT '',
            fanart_path     TEXT    DEFAULT '',
            video_path      TEXT    DEFAULT '',
            director        TEXT    DEFAULT '',
            writer          TEXT    DEFAULT '',
            actors          TEXT    DEFAULT '',
            runtime         TEXT    DEFAULT '',
            is_watched      INTEGER DEFAULT 0,
            is_favorite     INTEGER DEFAULT 0,
            last_played_time TEXT   DEFAULT NULL,
            play_progress   INTEGER DEFAULT 0,
            created_at      TEXT    NOT NULL,
            updated_at      TEXT    NOT NULL
        )
    """)

    # 兼容旧库：为新字段添加列
    new_movie_cols = {
        "director": "TEXT DEFAULT ''",
        "writer": "TEXT DEFAULT ''",
        "actors": "TEXT DEFAULT ''",
        "runtime": "TEXT DEFAULT ''",
    }
    existing_cols = {row[1] for row in cursor.execute("PRAGMA table_info(movies)")}
    for col_name, col_def in new_movie_cols.items():
        if col_name not in existing_cols:
            cursor.execute(f"ALTER TABLE movies ADD COLUMN {col_name} {col_def}")

    new_movie_cols2 = {"video_specs": "TEXT DEFAULT ''"}
    existing_cols2 = {row[1] for row in cursor.execute("PRAGMA table_info(movies)")}
    for col_name, col_def in new_movie_cols2.items():
        if col_name not in existing_cols2:
            cursor.execute(f"ALTER TABLE movies ADD COLUMN {col_name} {col_def}")

    new_movie_cols3 = {"media_info": "TEXT DEFAULT ''"}
    existing_cols3 = {row[1] for row in cursor.execute("PRAGMA table_info(movies)")}
    for col_name, col_def in new_movie_cols3.items():
        if col_name not in existing_cols3:
            cursor.execute(f"ALTER TABLE movies ADD COLUMN {col_name} {col_def}")

    # --- shows 表（电视剧） ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS shows (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            folder_path     TEXT    NOT NULL UNIQUE,
            title           TEXT    NOT NULL,
            original_title  TEXT    DEFAULT '',
            year            TEXT    DEFAULT '',
            plot            TEXT    DEFAULT '',
            rating          TEXT    DEFAULT '',
            genre           TEXT    DEFAULT '',
            poster_path     TEXT    DEFAULT '',
            fanart_path     TEXT    DEFAULT '',
            director        TEXT    DEFAULT '',
            writer          TEXT    DEFAULT '',
            actors          TEXT    DEFAULT '',
            is_favorite     INTEGER DEFAULT 0,
            season_count    INTEGER DEFAULT 0,
            created_at      TEXT    NOT NULL,
            updated_at      TEXT    NOT NULL
        )
    """)

    # --- episodes 表（单集） ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS episodes (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            show_id         INTEGER NOT NULL,
            season          INTEGER NOT NULL,
            episode         INTEGER NOT NULL,
            title           TEXT    DEFAULT '',
            plot            TEXT    DEFAULT '',
            rating          TEXT    DEFAULT '',
            thumb_path      TEXT    DEFAULT '',
            video_path      TEXT    DEFAULT '',
            is_watched      INTEGER DEFAULT 0,
            created_at      TEXT    NOT NULL,
            updated_at      TEXT    NOT NULL,
            FOREIGN KEY (show_id) REFERENCES shows(id) ON DELETE CASCADE,
            UNIQUE(show_id, season, episode)
        )
    """)

    # --- settings 表 ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)

    defaults = {
        "media_roots": json.dumps([], ensure_ascii=True),
        "player_path": r"D:\tools\mpv-lazy\mpv-lazy.exe",
    }
    for key, value in defaults.items():
        cursor.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value)
        )

    # 兼容旧库：为 shows 表添加 video_specs 列
    new_show_cols = {"video_specs": "TEXT DEFAULT ''"}
    existing_show_cols = {row[1] for row in cursor.execute("PRAGMA table_info(shows)")}
    for col_name, col_def in new_show_cols.items():
        if col_name not in existing_show_cols:
            cursor.execute(f"ALTER TABLE shows ADD COLUMN {col_name} {col_def}")

    # 兼容旧库：为 episodes 表添加 media_info 列
    new_ep_cols = {"media_info": "TEXT DEFAULT ''"}
    existing_ep_cols = {row[1] for row in cursor.execute("PRAGMA table_info(episodes)")}
    for col_name, col_def in new_ep_cols.items():
        if col_name not in existing_ep_cols:
            cursor.execute(f"ALTER TABLE episodes ADD COLUMN {col_name} {col_def}")

    conn.commit()
    conn.close()
    logger.info("数据库初始化完成")
# =============================================================================

def _deserialize_metadata(row):
    """将数据库中的 JSON 字符串字段反序列化为列表，兼容旧逗号分隔格式。"""
    for field in ("genre", "director", "writer"):
        val = row.get(field)
        if isinstance(val, str) and val:
            try:
                row[field] = json.loads(val)
            except (json.JSONDecodeError, TypeError):
                row[field] = [g.strip() for g in re.split(r'[,/]', val) if g.strip()]
        elif not val:
            row[field] = []
    # actors
    val = row.get("actors")
    if isinstance(val, str) and val:
        try:
            row["actors"] = json.loads(val)
        except (json.JSONDecodeError, TypeError):
            row["actors"] = []
    elif not val:
        row["actors"] = []
    return row

def get_movies(sort_by="title", genre=None, favorite_only=False, search=None):
    allowed_sort = {
        "title": "title COLLATE NOCASE ASC",
        "year": "year DESC",
        "rating": "CAST(rating AS REAL) DESC",
    }
    order_clause = allowed_sort.get(sort_by, "title COLLATE NOCASE ASC")
    conditions = []
    params = []
    if genre:
        conditions.append("genre LIKE ?")
        params.append(f"%{genre}%")
    if favorite_only:
        conditions.append("is_favorite = 1")
    if search and search.strip():
        kw = f"%{search.strip()}%"
        conditions.append("(title LIKE ? OR original_title LIKE ? OR plot LIKE ?)")
        params.extend([kw, kw, kw])
    where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    conn = get_connection()
    rows = conn.execute(
        f"SELECT *, 'movie' AS media_type FROM movies {where_clause} ORDER BY {order_clause}",
        params,
    ).fetchall()
    conn.close()
    return [_deserialize_metadata(dict(row)) for row in rows]


def get_movie(movie_id):
    conn = get_connection()
    row = conn.execute("SELECT *, 'movie' AS media_type FROM movies WHERE id = ?", (movie_id,)).fetchone()
    conn.close()
    return _deserialize_metadata(dict(row)) if row else None


def _json_arr(val):
    """将 Python 列表序列化为 JSON 字符串；若已是字符串则原样返回。"""
    if isinstance(val, list):
        return json.dumps(val, ensure_ascii=True)
    return val if val else "[]"

def upsert_movie(folder_path, data):
    conn = get_connection()
    now = datetime.now().isoformat()
    actors_json = json.dumps(data.get("actors", []), ensure_ascii=True)
    genre_json = _json_arr(data.get("genre", []))
    director_json = _json_arr(data.get("director", []))
    writer_json = _json_arr(data.get("writer", []))
    existing = conn.execute("SELECT id FROM movies WHERE folder_path = ?", (folder_path,)).fetchone()
    if existing:
        conn.execute("""
            UPDATE movies SET title=?, original_title=?, year=?, plot=?, rating=?, genre=?,
            director=?, writer=?, actors=?, runtime=?,
            poster_path=?, fanart_path=?, video_path=?, video_specs=?, media_info=?, updated_at=?
            WHERE folder_path=?
        """, (
            data["title"], data.get("original_title", ""), data.get("year", ""),
            data.get("plot", ""), data.get("rating", ""), genre_json,
            director_json, writer_json, actors_json,
            data.get("runtime", ""),
            data.get("poster_path", ""), data.get("fanart_path", ""), data.get("video_path", ""),
            data.get("video_specs", ""), data.get("media_info", ""),
            now, folder_path,
        ))
        movie_id = existing["id"]
    else:
        cursor = conn.execute("""
            INSERT INTO movies (folder_path, title, original_title, year, plot, rating,
            genre, director, writer, actors, runtime,
            poster_path, fanart_path, video_path, video_specs, media_info, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            folder_path, data["title"], data.get("original_title", ""), data.get("year", ""),
            data.get("plot", ""), data.get("rating", ""), genre_json,
            director_json, writer_json, actors_json,
            data.get("runtime", ""),
            data.get("poster_path", ""), data.get("fanart_path", ""), data.get("video_path", ""),
            data.get("video_specs", ""), data.get("media_info", ""),
            now, now,
        ))
        movie_id = cursor.lastrowid
        logger.info("新增电影: %s", data["title"])
    conn.commit()
    conn.close()
    return movie_id


def update_movie_status(movie_id, field, value):
    allowed_fields = {"is_watched", "is_favorite", "play_progress", "last_played_time"}
    if field not in allowed_fields:
        raise ValueError(f"不允许更新的字段: {field}")
    now = datetime.now().isoformat()
    conn = get_connection()
    conn.execute(
        f"UPDATE movies SET {field} = ?, updated_at = ? WHERE id = ?",
        (value, now, movie_id),
    )
    conn.commit()
    conn.close()


def mark_as_played(movie_id):
    now = datetime.now().isoformat()
    conn = get_connection()
    conn.execute(
        "UPDATE movies SET last_played_time = ?, updated_at = ? WHERE id = ?",
        (now, now, movie_id),
    )
    conn.commit()
    conn.close()


def toggle_watched(movie_id):
    conn = get_connection()
    row = conn.execute("SELECT is_watched FROM movies WHERE id = ?", (movie_id,)).fetchone()
    if row is None:
        conn.close()
        return None
    new_val = 0 if row["is_watched"] else 1
    now = datetime.now().isoformat()
    conn.execute("UPDATE movies SET is_watched = ?, updated_at = ? WHERE id = ?", (new_val, now, movie_id))
    conn.commit()
    conn.close()
    return new_val


def toggle_favorite(movie_id):
    conn = get_connection()
    row = conn.execute("SELECT is_favorite FROM movies WHERE id = ?", (movie_id,)).fetchone()
    if row is None:
        conn.close()
        return None
    new_val = 0 if row["is_favorite"] else 1
    now = datetime.now().isoformat()
    conn.execute("UPDATE movies SET is_favorite = ?, updated_at = ? WHERE id = ?", (new_val, now, movie_id))
    conn.commit()
    conn.close()
    return new_val


def delete_movie(movie_id):
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
# 电视剧 CRUD
# =============================================================================

def get_shows(sort_by="title", genre=None, favorite_only=False, search=None):
    allowed_sort = {
        "title": "title COLLATE NOCASE ASC",
        "year": "year DESC",
        "rating": "CAST(rating AS REAL) DESC",
    }
    order_clause = allowed_sort.get(sort_by, "title COLLATE NOCASE ASC")
    conditions = []
    params = []
    if genre:
        conditions.append("genre LIKE ?")
        params.append(f"%{genre}%")
    if favorite_only:
        conditions.append("is_favorite = 1")
    if search and search.strip():
        kw = f"%{search.strip()}%"
        conditions.append("(title LIKE ? OR original_title LIKE ? OR plot LIKE ?)")
        params.extend([kw, kw, kw])
    where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    conn = get_connection()
    rows = conn.execute(
        f"SELECT *, 'tvshow' AS media_type FROM shows {where_clause} ORDER BY {order_clause}",
        params,
    ).fetchall()
    conn.close()
    return [_deserialize_metadata(dict(row)) for row in rows]


def get_show(show_id):
    conn = get_connection()
    row = conn.execute("SELECT *, 'tvshow' AS media_type FROM shows WHERE id = ?", (show_id,)).fetchone()
    conn.close()
    return _deserialize_metadata(dict(row)) if row else None


def upsert_show(folder_path, data):
    conn = get_connection()
    now = datetime.now().isoformat()
    actors_json = json.dumps(data.get("actors", []), ensure_ascii=True)
    genre_json = _json_arr(data.get("genre", []))
    director_json = _json_arr(data.get("director", []))
    writer_json = _json_arr(data.get("writer", []))
    existing = conn.execute("SELECT id FROM shows WHERE folder_path = ?", (folder_path,)).fetchone()
    if existing:
        conn.execute("""
            UPDATE shows SET title=?, original_title=?, year=?, plot=?, rating=?, genre=?,
            director=?, writer=?, actors=?, poster_path=?, fanart_path=?,
            season_count=?, video_specs=?, updated_at=?
            WHERE folder_path=?
        """, (
            data["title"], data.get("original_title", ""), data.get("year", ""),
            data.get("plot", ""), data.get("rating", ""), genre_json,
            director_json, writer_json, actors_json,
            data.get("poster_path", ""), data.get("fanart_path", ""),
            data.get("season_count", 0), data.get("video_specs", ""),
            now, folder_path,
        ))
        show_id = existing["id"]
    else:
        cursor = conn.execute("""
            INSERT INTO shows (folder_path, title, original_title, year, plot, rating,
            genre, director, writer, actors, poster_path, fanart_path, season_count,
            video_specs, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            folder_path, data["title"], data.get("original_title", ""), data.get("year", ""),
            data.get("plot", ""), data.get("rating", ""), genre_json,
            director_json, writer_json, actors_json,
            data.get("poster_path", ""), data.get("fanart_path", ""),
            data.get("season_count", 0), data.get("video_specs", ""),
            now, now,
        ))
        show_id = cursor.lastrowid
        logger.info("新增电视剧: %s", data["title"])
    conn.commit()
    conn.close()
    return show_id


def toggle_show_favorite(show_id):
    conn = get_connection()
    row = conn.execute("SELECT is_favorite FROM shows WHERE id = ?", (show_id,)).fetchone()
    if row is None:
        conn.close()
        return None
    new_val = 0 if row["is_favorite"] else 1
    now = datetime.now().isoformat()
    conn.execute("UPDATE shows SET is_favorite = ?, updated_at = ? WHERE id = ?", (new_val, now, show_id))
    conn.commit()
    conn.close()
    return new_val


def delete_show(show_id):
    conn = get_connection()
    row = conn.execute("SELECT id FROM shows WHERE id = ?", (show_id,)).fetchone()
    if row is None:
        conn.close()
        return False
    conn.execute("DELETE FROM episodes WHERE show_id = ?", (show_id,))
    conn.execute("DELETE FROM shows WHERE id = ?", (show_id,))
    conn.commit()
    conn.close()
    return True


# =============================================================================
# 单集 CRUD
# =============================================================================

def get_episodes(show_id, season=None):
    conn = get_connection()
    if season is not None:
        rows = conn.execute(
            "SELECT * FROM episodes WHERE show_id = ? AND season = ? ORDER BY episode",
            (show_id, season),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM episodes WHERE show_id = ? ORDER BY season, episode",
            (show_id,),
        ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_episode(episode_id):
    conn = get_connection()
    row = conn.execute("SELECT * FROM episodes WHERE id = ?", (episode_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def upsert_episode(show_id, season, episode, data):
    conn = get_connection()
    now = datetime.now().isoformat()
    existing = conn.execute(
        "SELECT id FROM episodes WHERE show_id = ? AND season = ? AND episode = ?",
        (show_id, season, episode),
    ).fetchone()
    if existing:
        conn.execute("""
            UPDATE episodes SET title=?, plot=?, rating=?, thumb_path=?, video_path=?,
            media_info=?, updated_at=?
            WHERE show_id=? AND season=? AND episode=?
        """, (
            data.get("title", ""), data.get("plot", ""), data.get("rating", ""),
            data.get("thumb_path", ""), data.get("video_path", ""),
            data.get("media_info", ""), now,
            show_id, season, episode,
        ))
        ep_id = existing["id"]
    else:
        cursor = conn.execute("""
            INSERT INTO episodes (show_id, season, episode, title, plot, rating,
            thumb_path, video_path, media_info, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, (
            show_id, season, episode,
            data.get("title", ""), data.get("plot", ""), data.get("rating", ""),
            data.get("thumb_path", ""), data.get("video_path", ""),
            data.get("media_info", ""),
            now, now,
        ))
        ep_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return ep_id


def delete_stale_episodes(show_id, on_disk_keys):
    """
    删除磁盘上已不存在的单集记录（保留 is_watched 状态不会被误删）。
    on_disk_keys: 扫描中发现的 (season, episode) 元组集合。
    返回删除的行数。
    """
    conn = get_connection()
    db_episodes = conn.execute(
        "SELECT id, season, episode FROM episodes WHERE show_id = ?", (show_id,)
    ).fetchall()
    stale_ids = [
        row["id"] for row in db_episodes
        if (row["season"], row["episode"]) not in on_disk_keys
    ]
    for ep_id in stale_ids:
        conn.execute("DELETE FROM episodes WHERE id = ?", (ep_id,))
    conn.commit()
    conn.close()
    if stale_ids:
        logger.info("清理过期单集 %d 条 (show_id=%s)", len(stale_ids), show_id)
    return len(stale_ids)


def toggle_episode_watched(episode_id):
    conn = get_connection()
    row = conn.execute("SELECT is_watched FROM episodes WHERE id = ?", (episode_id,)).fetchone()
    if row is None:
        conn.close()
        return None
    new_val = 0 if row["is_watched"] else 1
    now = datetime.now().isoformat()
    conn.execute("UPDATE episodes SET is_watched = ?, updated_at = ? WHERE id = ?", (new_val, now, episode_id))
    conn.commit()
    conn.close()
    return new_val


def get_show_seasons(show_id):
    conn = get_connection()
    rows = conn.execute(
        "SELECT DISTINCT season FROM episodes WHERE show_id = ? ORDER BY season", (show_id,)
    ).fetchall()
    conn.close()
    return [row["season"] for row in rows]


def mark_show_watched(show_id, watched):
    """将电视剧所有单集标记为已看或未看。返回更新的集数。"""
    now = datetime.now().isoformat()
    conn = get_connection()
    conn.execute(
        "UPDATE episodes SET is_watched = ?, updated_at = ? WHERE show_id = ?",
        (1 if watched else 0, now, show_id),
    )
    count = conn.execute("SELECT COUNT(*) FROM episodes WHERE show_id = ?", (show_id,)).fetchone()[0]
    conn.commit()
    conn.close()
    return count


def mark_season_watched(show_id, season, watched):
    """将某季所有单集标记为已看或未看。返回更新的集数。"""
    now = datetime.now().isoformat()
    conn = get_connection()
    conn.execute(
        "UPDATE episodes SET is_watched = ?, updated_at = ? WHERE show_id = ? AND season = ?",
        (1 if watched else 0, now, show_id, season),
    )
    count = conn.execute(
        "SELECT COUNT(*) FROM episodes WHERE show_id = ? AND season = ?", (show_id, season)
    ).fetchone()[0]
    conn.commit()
    conn.close()
    return count


def is_show_all_watched(show_id):
    """检查电视剧是否全部已看。"""
    conn = get_connection()
    total = conn.execute("SELECT COUNT(*) FROM episodes WHERE show_id = ?", (show_id,)).fetchone()[0]
    watched = conn.execute(
        "SELECT COUNT(*) FROM episodes WHERE show_id = ? AND is_watched = 1", (show_id,)
    ).fetchone()[0]
    conn.close()
    return total > 0 and total == watched


# =============================================================================
# 统一媒体查询（供侧边栏筛选使用）
# =============================================================================

def get_all_media(sort_by="title", genre=None, favorite_only=False, search=None):
    movies = get_movies(sort_by=sort_by, genre=genre, favorite_only=favorite_only, search=search)
    shows = get_shows(sort_by=sort_by, genre=genre, favorite_only=favorite_only, search=search)
    combined = movies + shows
    if sort_by == "title":
        combined.sort(key=lambda x: x.get("title", "").lower())
    elif sort_by == "year":
        combined.sort(key=lambda x: x.get("year", ""), reverse=True)
    elif sort_by == "rating":
        combined.sort(key=lambda x: float(x.get("rating") or 0), reverse=True)
    return combined


# =============================================================================
# 设置 CRUD
# =============================================================================

def get_settings():
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
    conn = get_connection()
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
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
    roots = get_setting("media_roots") or []
    if path not in roots:
        roots.append(path)
        update_setting("media_roots", roots)
    return roots


def remove_media_root(path):
    roots = get_setting("media_roots") or []
    if path in roots:
        roots.remove(path)
        update_setting("media_roots", roots)
    return roots


# =============================================================================
# 类型标签
# =============================================================================

def get_genres():
    conn = get_connection()
    genres = set()
    for table in ["movies", "shows"]:
        rows = conn.execute(f"SELECT genre FROM {table} WHERE genre != '' AND genre != '[]'").fetchall()
        for row in rows:
            val = row["genre"]
            try:
                genre_list = json.loads(val)
            except (json.JSONDecodeError, TypeError):
                genre_list = [g.strip() for g in val.split(",") if g.strip()]
            for g in genre_list:
                g = g.strip()
                if g:
                    genres.add(g)
    conn.close()
    return sorted(genres)


# =============================================================================
# 全量刷新辅助
# =============================================================================

def get_all_folder_paths():
    conn = get_connection()
    rows = conn.execute("SELECT folder_path FROM movies").fetchall()
    movie_paths = {row["folder_path"] for row in rows}
    rows = conn.execute("SELECT folder_path FROM shows").fetchall()
    show_paths = {row["folder_path"] for row in rows}
    conn.close()
    return movie_paths | show_paths


def get_all_show_paths():
    conn = get_connection()
    rows = conn.execute("SELECT folder_path FROM shows").fetchall()
    conn.close()
    return {row["folder_path"] for row in rows}


def reset_all_media():
    """清空所有电影、电视剧、单集记录（保留设置）。"""
    conn = get_connection()
    conn.execute("DELETE FROM episodes")
    conn.execute("DELETE FROM movies")
    conn.execute("DELETE FROM shows")
    conn.commit()
    conn.close()
    logger.info("已清空所有媒体记录")


def delete_stale_media(on_disk_movie_paths, on_disk_show_paths):
    conn = get_connection()
    deleted = 0

    db_movies = {row["folder_path"] for row in conn.execute("SELECT folder_path FROM movies").fetchall()}
    stale_movies = db_movies - on_disk_movie_paths
    for path in stale_movies:
        conn.execute("DELETE FROM movies WHERE folder_path = ?", (path,))
        deleted += 1

    db_shows = {row["folder_path"] for row in conn.execute("SELECT folder_path FROM shows").fetchall()}
    stale_shows = db_shows - on_disk_show_paths
    for path in stale_shows:
        show = conn.execute("SELECT id FROM shows WHERE folder_path = ?", (path,)).fetchone()
        if show:
            conn.execute("DELETE FROM episodes WHERE show_id = ?", (show["id"],))
            conn.execute("DELETE FROM shows WHERE folder_path = ?", (path,))
            deleted += 1

    conn.commit()
    conn.close()
    if deleted > 0:
        logger.info("清理过期记录: %d 条", deleted)
    return deleted
