"""
scanner.py — 媒体扫描器模块
递归扫描所有配置的根目录，解析 movie.nfo，识别海报与背景图，
将结果通过 database 模块写入 SQLite。支持全量刷新模式。
"""

import os
import re
import xml.etree.ElementTree as ET

import database

# 支持的视频文件扩展名（小写）
VIDEO_EXTENSIONS = {".mkv", ".mp4", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v", ".mpg", ".mpeg"}

# 海报文件名候选（精确匹配，按优先级排列）
POSTER_NAMES = ["poster.jpg", "folder.jpg", "poster.png", "folder.png", "cover.jpg", "cover.png"]

# 背景图文件名候选（精确匹配）
FANART_NAMES = ["fanart.jpg", "fanart.png", "backdrop.jpg", "background.jpg"]

# 模糊匹配关键词（用于精确匹配未命中时的回退搜索）
POSTER_KEYWORDS = ["poster", "folder", "cover"]
FANART_KEYWORDS = ["fanart", "backdrop", "background"]

# =============================================================================
# 标题清理：从视频文件名中移除分辨率、编码、音轨等标签
# =============================================================================

# 按顺序应用的正则替换模式（大小写不敏感）
CLEANUP_PATTERNS = [
    # 音轨标签（较长、具体的先匹配）
    r'\b(dts-hd[\s-]?ma|dts-hd|dtshd|truehd|atmos)\b',
    r'\b(dts|aac|ac3|eac3|flac|mp3|ddp?5\.1|ddp?7\.1|ddp?2\.0)\b',
    # HDR
    r'\b(hdr10\+|hdr10|dolby[\s-]?vision|dv)\b',
    r'\b(hdr|sdr|hlg)\b',
    # 编码
    r'\b(x264|x265|h264|h265|hevc|avc|av1|vp9|mpeg2|divx|xvid)\b',
    # 来源 / 版本
    r'\b(bluray|blu-ray|remux|web-dl|webdl|webrip|web-rip|hdtv|bdrip|brrip|dvdrip|dvd)\b',
    # 分辨率 / 画质
    r'\b(2160p|1080p|720p|480p|4k|8k|uhd|hd|sd)\b',
    # 音轨语言缩写
    r'\b(chi|chs|cht|eng|jpn|kor|fre|ger|ita|spa|por|rus|ara|hin|tha|vie)\b',
    # 常见组名
    r'\b(wiki|chd|hdchina|hdroad|hds|hdtime|hdarea|beitai|cmct|frds|mnhd|tigole|qxr|yify|rarbg|galaxy|evo|fgt|sparks|amiable|droned|geckos|dreamhd)\b',
    # 各种标签
    r'\b(proper|repack|rerip|internal|limited|extended|unrated|directors[\s-]?cut|theatrical[\s-]?cut|imax|open[\s-]?matte)\b',
    r'\b(multi|complete|remastered|restored|criterion|collection|special[\s-]?edition)\b',
    # 声道
    r'\b\d+\.\d\b',
    # 方括号内的内容
    r'\[.*?\]',
    # MA 标签（如 DTSHD-MA 残留的 MA）
    r'\bma\b',
    # V1 V2 V3 等版本号
    r'\bv\d+\b',
]


def clean_title(filename):
    """
    从视频文件名中智能移除分辨率、编码、音轨、压制组等标签，提取干净的标题。

    核心思路：两轮清理。第一轮在点号被替换为空格之前执行，正确匹配
    如 "MA5.1" 这种靠点号分隔的组合；第二轮在点号→空格后再清理残留。

    Args:
        filename: 不含扩展名的视频文件名，如 "Avatar.2009.2160p.BluRay.x265"

    Returns:
        str: 清理后的标题，如 "Avatar 2009"
    """
    cleaned = filename.strip()

    # ── 保存年份（用不含 _ 和 . 的唯一占位符）──
    year_match = re.search(r'\b((?:19|20)\d{2})\b', cleaned)
    year_str = year_match.group(1) if year_match else ""
    cleaned = re.sub(r'\b((?:19|20)\d{2})\b', ' @@YR@@ ', cleaned)

    # ── 第一轮：在有点号的情况下匹配 ──
    for _ in range(3):
        changed = False
        for pattern in CLEANUP_PATTERNS:
            new_text = re.sub(pattern, ' ', cleaned, flags=re.IGNORECASE)
            if new_text != cleaned:
                changed = True
                cleaned = new_text
        if not changed:
            break

    # ── 点号和下划线 → 空格 ──
    cleaned = cleaned.replace(".", " ").replace("_", " ")

    # ── 放回年份（放在空格替换之后，避免 . / _ 破坏占位符）──
    cleaned = cleaned.replace('@@YR@@', year_str if year_str else '')

    # ── 第二轮：在空格版本上再次清理 ──
    for _ in range(3):
        changed = False
        for pattern in CLEANUP_PATTERNS:
            new_text = re.sub(pattern, ' ', cleaned, flags=re.IGNORECASE)
            if new_text != cleaned:
                changed = True
                cleaned = new_text
        if not changed:
            break

    # ── 最终清理 ──
    # 残留的 "MA5" 等（音轨残留，如 DTS-HD MA5.1 清理后的 MA5）
    cleaned = re.sub(r'\bma\d*\b', ' ', cleaned, flags=re.IGNORECASE)
    # 残留的音频数字组合
    cleaned = re.sub(r'\b\d+Audio\b', ' ', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\bAudio\b', ' ', cleaned, flags=re.IGNORECASE)
    # 独立的单个数字（声道残留）
    cleaned = re.sub(r'\b\d\b', ' ', cleaned)
    # 去除连字符
    cleaned = re.sub(r'\s*-\s*', ' ', cleaned)
    # 合并空格
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    # 修复括号内多余空格：如 "( 2017 )" → "(2017)"
    cleaned = re.sub(r'\(\s+', '(', cleaned)
    cleaned = re.sub(r'\s+\)', ')', cleaned)
    # 去除首尾残留标点
    cleaned = cleaned.strip(' -.,;:')
    # 去除空括号
    cleaned = re.sub(r'\(\s*\)', '', cleaned)
    cleaned = re.sub(r'\[\s*\]', '', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()

    if not cleaned:
        cleaned = filename

    return cleaned.strip()


# =============================================================================
# NFO 解析
# =============================================================================


def parse_nfo(nfo_path):
    """
    解析 Kodi XBMC 格式的 movie.nfo 文件。

    支持：
    - 单个或多级 <genre> 标签（多个以逗号拼接）
    - <ratings><rating><value> 嵌套评分
    - <movie> 根元素或直接以 <title> 等为根的情况
    - <director>, <credits>/<writer>, <actor> (含 name/role), <runtime>

    Args:
        nfo_path: nfo 文件的绝对路径

    Returns:
        dict: 包含 title, original_title, year, plot, rating, genre,
              director, writer, actors, runtime 等字段。解析失败返回空 dict。
    """
    try:
        tree = ET.parse(nfo_path)
        root = tree.getroot()
    except (ET.ParseError, FileNotFoundError):
        return {}

    result = {}
    movie_elem = root if root.tag == "movie" else root

    # 简单字段：取第一个匹配元素的文本
    simple_tags = {
        "title": "title",
        "originaltitle": "original_title",
        "year": "year",
        "plot": "plot",
        "director": "director",
        "runtime": "runtime",
    }
    for tag, key in simple_tags.items():
        elem = movie_elem.find(tag)
        if elem is not None and elem.text:
            result[key] = elem.text.strip()

    # 编剧：优先 <credits>，回退到 <writer>
    for tag in ("credits", "writer"):
        elem = movie_elem.find(tag)
        if elem is not None and elem.text and elem.text.strip():
            result["writer"] = elem.text.strip()
            break

    # 演员：<actor> 列表，含 <name> 和 <role>
    actors = []
    for actor_elem in movie_elem.findall("actor"):
        name_elem = actor_elem.find("name")
        role_elem = actor_elem.find("role")
        if name_elem is not None and name_elem.text and name_elem.text.strip():
            actor = {"name": name_elem.text.strip()}
            if role_elem is not None and role_elem.text and role_elem.text.strip():
                actor["role"] = role_elem.text.strip()
            actors.append(actor)
    result["actors"] = actors

    # 评分：优先 <ratings><rating><value>，回退到 <rating>
    rating = ""
    ratings_elem = movie_elem.find("ratings")
    if ratings_elem is not None:
        rating_elem = ratings_elem.find("rating")
        if rating_elem is not None:
            value_elem = rating_elem.find("value")
            if value_elem is not None and value_elem.text:
                rating = value_elem.text.strip()
    if not rating:
        elem = movie_elem.find("rating")
        if elem is not None and elem.text:
            rating = elem.text.strip()
    result["rating"] = rating

    # 类型：可能有多个 <genre> 标签
    genres = []
    for elem in movie_elem.findall("genre"):
        if elem.text and elem.text.strip():
            genres.append(elem.text.strip())
    result["genre"] = ", ".join(genres) if genres else ""

    return result


# =============================================================================
# 文件查找
# =============================================================================


def find_video_file(folder_path):
    """在指定文件夹中查找第一个视频文件。"""
    try:
        for entry in os.scandir(folder_path):
            if entry.is_file():
                ext = os.path.splitext(entry.name)[1].lower()
                if ext in VIDEO_EXTENSIONS:
                    return entry.path
    except OSError:
        pass
    return None


def find_nfo_file(folder_path):
    """
    在文件夹中查找 nfo 文件。
    优先 movie.nfo，否则返回第一个 *.nfo 文件。
    """
    movie_nfo = os.path.join(folder_path, "movie.nfo")
    if os.path.isfile(movie_nfo):
        return movie_nfo
    # 回退：查找任意 .nfo 文件
    try:
        for entry in os.scandir(folder_path):
            if entry.is_file() and entry.name.lower().endswith(".nfo"):
                return entry.path
    except OSError:
        pass
    return ""


def find_poster(folder_path):
    """
    在文件夹中查找海报图片。

    1. 先精确匹配标准文件名（poster.jpg, folder.jpg 等）
    2. 未命中则扫描所有图片文件，匹配文件名包含 poster/folder/cover 关键词
    """
    # 精确匹配
    for name in POSTER_NAMES:
        candidate = os.path.join(folder_path, name)
        if os.path.isfile(candidate):
            return candidate

    # 模糊匹配：扫描所有图片文件
    image_exts = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
    try:
        for entry in os.scandir(folder_path):
            if entry.is_file():
                ext = os.path.splitext(entry.name)[1].lower()
                if ext in image_exts:
                    name_lower = entry.name.lower()
                    for keyword in POSTER_KEYWORDS:
                        if keyword in name_lower:
                            return entry.path
    except OSError:
        pass
    return ""


def find_fanart(folder_path):
    """
    在文件夹中查找背景图。

    1. 先精确匹配标准文件名（fanart.jpg 等）
    2. 未命中则扫描所有图片文件，匹配文件名包含 fanart/backdrop/background 关键词
    """
    # 精确匹配
    for name in FANART_NAMES:
        candidate = os.path.join(folder_path, name)
        if os.path.isfile(candidate):
            return candidate

    # 模糊匹配
    image_exts = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
    try:
        for entry in os.scandir(folder_path):
            if entry.is_file():
                ext = os.path.splitext(entry.name)[1].lower()
                if ext in image_exts:
                    name_lower = entry.name.lower()
                    for keyword in FANART_KEYWORDS:
                        if keyword in name_lower:
                            return entry.path
    except OSError:
        pass
    return ""


# =============================================================================
# 主扫描逻辑
# =============================================================================


def scan_folder(folder_path):
    """
    扫描单个文件夹：查找视频文件、解析 nfo、识别图片，写入数据库。

    标题优先级：
    1. movie.nfo 中的 <title>
    2. 经过 clean_title() 清理后的视频文件名

    Args:
        folder_path: 文件夹绝对路径

    Returns:
        dict | None: 写入数据库的记录数据，如果文件夹不含视频则返回 None
    """
    if not os.path.isdir(folder_path):
        return None

    # 查找视频文件
    video_path = find_video_file(folder_path)
    if not video_path:
        return None

    # 查找并解析 nfo 文件（movie.nfo 或任意 .nfo）
    nfo_path = find_nfo_file(folder_path)
    nfo_data = parse_nfo(nfo_path) if nfo_path else {}

    # 标题：优先 nfo.title，否则从视频文件名清理
    if nfo_data.get("title"):
        title = nfo_data["title"]
    else:
        video_name = os.path.splitext(os.path.basename(video_path))[0]
        title = clean_title(video_name)

    # 查找海报和背景图
    poster_path = find_poster(folder_path)
    fanart_path = find_fanart(folder_path)

    movie_data = {
        "title": title,
        "original_title": nfo_data.get("original_title", ""),
        "year": nfo_data.get("year", ""),
        "plot": nfo_data.get("plot", "无简介"),
        "rating": nfo_data.get("rating", ""),
        "genre": nfo_data.get("genre", ""),
        "director": nfo_data.get("director", ""),
        "writer": nfo_data.get("writer", ""),
        "actors": nfo_data.get("actors", []),
        "runtime": nfo_data.get("runtime", ""),
        "poster_path": poster_path,
        "fanart_path": fanart_path,
        "video_path": video_path,
    }

    movie_id = database.upsert_movie(folder_path, movie_data)
    movie_data["id"] = movie_id
    return movie_data


def scan_all_roots(progress_callback=None, full_refresh=True):
    """
    扫描所有配置的媒体库根目录。

    全量刷新模式下会先收集磁盘上所有有效文件夹，
    扫描后删除数据库中磁盘上已不存在的过期记录。

    Args:
        progress_callback: 可选回调 callback(status, detail)
        full_refresh: 是否全量刷新（默认 True）

    Returns:
        dict: {"total", "added", "updated", "deleted", "errors"}
    """
    media_roots = database.get_setting("media_roots")
    if not media_roots:
        if progress_callback:
            progress_callback("complete", "未配置媒体库根目录")
        return {"total": 0, "added": 0, "updated": 0, "deleted": 0, "errors": []}

    stats = {"total": 0, "added": 0, "updated": 0, "deleted": 0, "errors": []}
    on_disk_paths = set()

    for root_dir in media_roots:
        if not os.path.isdir(root_dir):
            stats["errors"].append(f"目录不存在: {root_dir}")
            continue

        for dirpath, _dirnames, filenames in os.walk(root_dir):
            has_video = any(
                os.path.splitext(f)[1].lower() in VIDEO_EXTENSIONS
                for f in filenames
            )
            if not has_video:
                continue

            on_disk_paths.add(dirpath)

            if progress_callback:
                progress_callback("scanning", dirpath)

            try:
                existing = _get_movie_by_folder(dirpath)
                is_new = existing is None

                result = scan_folder(dirpath)
                if result:
                    stats["total"] += 1
                    if is_new:
                        stats["added"] += 1
                    else:
                        stats["updated"] += 1

                    if progress_callback:
                        label = "新增" if is_new else "更新"
                        progress_callback("found", f"[{label}] {result['title']}")
            except Exception as e:
                stats["errors"].append(f"{dirpath}: {str(e)}")

    # 全量刷新：删除磁盘上已不存在的记录
    if full_refresh and on_disk_paths:
        if progress_callback:
            progress_callback("cleanup", "正在清理过期记录...")
        deleted_count = database.delete_stale_movies(on_disk_paths)
        stats["deleted"] = deleted_count
        if progress_callback and deleted_count > 0:
            progress_callback("cleanup", f"已清理 {deleted_count} 条过期记录")

    if progress_callback:
        parts = [
            f"扫描完成：共 {stats['total']} 部",
            f"新增 {stats['added']}",
            f"更新 {stats['updated']}",
        ]
        if stats["deleted"] > 0:
            parts.append(f"清理 {stats['deleted']}")
        parts.append(f"错误 {len(stats['errors'])}")
        progress_callback("complete", "，".join(parts))

    return stats


def _get_movie_by_folder(folder_path):
    """查询数据库是否已存在该文件夹的记录。"""
    conn = database.get_connection()
    row = conn.execute(
        "SELECT id FROM movies WHERE folder_path = ?", (folder_path,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None
