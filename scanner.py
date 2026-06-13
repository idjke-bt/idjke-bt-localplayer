"""
scanner.py — 媒体扫描器模块
递归扫描所有配置的根目录，解析 movie.nfo，识别海报与背景图，
将结果通过 database 模块写入 SQLite。支持全量刷新模式。
"""

import json
import logging
import os
import re
import xml.etree.ElementTree as ET

import database

logger = logging.getLogger("scanner")

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
    # 通用 WEB 标签
    r'\bweb\b',
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
# 视频规格提取
# =============================================================================


def extract_video_specs(filename):
    """
    从视频文件名中检测技术规格。
    返回 dict，键: resolution, video_codec, hdr, audio, source。
    """
    text = filename.upper()
    specs = {}

    # 分辨率
    if re.search(r'\b2160P\b', text) or re.search(r'\b4K\b', text):
        specs["resolution"] = "4K"
    elif re.search(r'\b1080P\b', text):
        specs["resolution"] = "1080p"
    elif re.search(r'\b720P\b', text):
        specs["resolution"] = "720p"
    elif re.search(r'\b480P\b', text):
        specs["resolution"] = "480p"

    # 视频编码
    if re.search(r'\b(X265|HEVC|H\.265)\b', text):
        specs["video_codec"] = "HEVC"
    elif re.search(r'\b(X264|AVC|H\.264)\b', text):
        specs["video_codec"] = "H.264"
    elif re.search(r'\bAV1\b', text):
        specs["video_codec"] = "AV1"
    elif re.search(r'\bVP9\b', text):
        specs["video_codec"] = "VP9"

    # HDR
    if re.search(r'\bHDR10\+\b', text):
        specs["hdr"] = "HDR10+"
    elif re.search(r'\bHDR10\b', text):
        specs["hdr"] = "HDR10"
    elif re.search(r'\bDOLBY[\s-]?VISION\b', text) or re.search(r'\bDV\b', text):
        specs["hdr"] = "Dolby Vision"
    elif re.search(r'\bHDR\b', text):
        specs["hdr"] = "HDR"
    elif re.search(r'\bHLG\b', text):
        specs["hdr"] = "HLG"
    elif re.search(r'\bSDR\b', text):
        specs["hdr"] = "SDR"

    # 音频
    if re.search(r'\bDTS-HD[\s-]?MA\b', text) or re.search(r'\bDTSHD[\s-]?MA\b', text):
        specs["audio"] = "DTS-HD MA"
    elif re.search(r'\bTRUEHD\b', text):
        specs["audio"] = "TrueHD"
    elif re.search(r'\bATMOS\b', text):
        specs["audio"] = "Atmos"
    elif re.search(r'\bDTS-HD\b', text) or re.search(r'\bDTSHD\b', text):
        specs["audio"] = "DTS-HD"
    elif re.search(r'\bDTS\b', text):
        specs["audio"] = "DTS"
    elif re.search(r'\bAC3\b', text) or re.search(r'\bEAC3\b', text) or re.search(r'\bDDP\b', text):
        specs["audio"] = "Dolby Digital"
    elif re.search(r'\bAAC\b', text):
        specs["audio"] = "AAC"
    elif re.search(r'\bFLAC\b', text):
        specs["audio"] = "FLAC"

    # 来源
    if re.search(r'\bBLU[\s-]?RAY\b', text) or re.search(r'\bBLURAY\b', text):
        specs["source"] = "BluRay"
    elif re.search(r'\bREMUX\b', text):
        specs["source"] = "REMUX"
    elif re.search(r'\bWEB[\s-]?DL\b', text) or re.search(r'\bWEBDL\b', text):
        specs["source"] = "WEB-DL"
    elif re.search(r'\bWEB[\s-]?RIP\b', text):
        specs["source"] = "WebRip"
    elif re.search(r'\bHDTV\b', text):
        specs["source"] = "HDTV"
    elif re.search(r'\bBD[\s-]?RIP\b', text) or re.search(r'\bBRRIP\b', text):
        specs["source"] = "BDRip"
    elif re.search(r'\bDVD[\s-]?RIP\b', text) or re.search(r'\bDVDRIP\b', text):
        specs["source"] = "DVD"

    return specs


def parse_fileinfo(nfo_path):
    """
    解析 NFO 文件中的 <fileinfo><streamdetails> 块，提取完整的视频/音频/字幕流信息。
    返回 dict: {video: {...}, audio: [...], subtitles: [...]}
    """
    try:
        tree = ET.parse(nfo_path)
        root = tree.getroot()
    except (ET.ParseError, FileNotFoundError):
        return {}

    fileinfo_elem = root.find("fileinfo")
    if fileinfo_elem is None:
        return {}

    sd = fileinfo_elem.find("streamdetails")
    if sd is None:
        return {}

    result = {}

    # 视频流
    ve = sd.find("video")
    if ve is not None:
        video = {}
        for tag in ("codec", "aspect", "width", "height", "durationinseconds",
                     "stereomode", "scantype", "bitrate", "bitdepth",
                     "colorspace", "colortransfer", "pix_fmt"):
            elem = ve.find(tag)
            if elem is not None and elem.text and elem.text.strip():
                video[tag] = elem.text.strip()
        if video:
            result["video"] = video

    # 音频流（可能有多个）
    audio_list = []
    for ae in sd.findall("audio"):
        ainfo = {}
        for tag in ("title", "codec", "language", "channels", "channel_layout",
                     "samplerate", "bitdepth", "default"):
            elem = ae.find(tag)
            if elem is not None and elem.text and elem.text.strip():
                ainfo[tag] = elem.text.strip()
        if ainfo:
            audio_list.append(ainfo)
    if audio_list:
        result["audio"] = audio_list

    # 字幕流（可能有多个）
    sub_list = []
    for se in sd.findall("subtitle"):
        sinfo = {}
        for tag in ("title", "language", "format", "default", "forced"):
            elem = se.find(tag)
            if elem is not None and elem.text and elem.text.strip():
                sinfo[tag] = elem.text.strip()
        if sinfo:
            sub_list.append(sinfo)
    if sub_list:
        result["subtitles"] = sub_list

    return result


def extract_media_info_ffprobe(video_path):
    """
    使用 ffprobe 提取视频文件的详细技术信息。
    如果 ffprobe 不可用或执行失败，返回空 dict。
    """
    import subprocess
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", "-show_streams", video_path],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return {}
        data = json.loads(result.stdout)
    except (FileNotFoundError, subprocess.TimeoutExpired,
            json.JSONDecodeError, Exception):
        return {}

    info = {}
    streams = data.get("streams", [])
    fmt = data.get("format", {})

    # 文件信息
    info["file_path"] = video_path
    if fmt.get("size"):
        info["file_size"] = int(fmt["size"])
    if fmt.get("bit_rate"):
        info["overall_bitrate"] = int(fmt["bit_rate"])

    # 视频流
    for s in streams:
        if s.get("codec_type") == "video":
            v = {}
            tags = s.get("tags", {})
            if tags.get("title"):
                v["title"] = tags["title"]
            v["codec"] = s.get("codec_name", "").upper()
            if s.get("profile"):
                v["profile"] = s["profile"]
            if s.get("level"):
                level = s["level"]
                v["level"] = str(level / 10) if isinstance(level, int) and level > 10 else str(level)
            v["width"] = s.get("width")
            v["height"] = s.get("height")
            if s.get("display_aspect_ratio"):
                v["aspect"] = s["display_aspect_ratio"]
            else:
                w = s.get("width", 0)
                h = s.get("height", 0)
                if w and h:
                    from fractions import Fraction
                    frac = Fraction(w, h)
                    v["aspect"] = f"{frac.numerator}:{frac.denominator}"
            field = s.get("field_order", "")
            v["interlaced"] = field not in ("", "progressive", "unknown")
            if s.get("r_frame_rate"):
                try:
                    num, den = s["r_frame_rate"].split("/")
                    if int(den) > 0:
                        v["framerate"] = round(int(num) / int(den), 3)
                except (ValueError, ZeroDivisionError):
                    pass
            if s.get("bit_rate"):
                v["bitrate"] = int(s["bit_rate"])
            if s.get("color_space"):
                v["colorspace"] = s["color_space"].upper()
            if s.get("color_transfer"):
                v["color_transfer"] = s["color_transfer"].upper()
            if s.get("bits_per_raw_sample"):
                v["bit_depth"] = int(s["bits_per_raw_sample"])
            elif s.get("pix_fmt", "").endswith("10le"):
                v["bit_depth"] = 10
            if s.get("pix_fmt"):
                v["pixel_format"] = s["pix_fmt"]
            info["video"] = v
            break

    # 音频流
    audio_list = []
    for s in streams:
        if s.get("codec_type") == "audio":
            a = {}
            tags = s.get("tags", {})
            if tags.get("title"):
                a["title"] = tags["title"]
            lang = tags.get("language", "")
            if not lang:
                lang = s.get("tags", {}).get("language", "")
            if lang:
                a["language"] = lang
            a["codec"] = s.get("codec_name", "").upper()
            if s.get("channel_layout"):
                a["channel_layout"] = s["channel_layout"]
            a["channels"] = s.get("channels")
            if s.get("sample_rate"):
                a["sample_rate"] = int(s["sample_rate"])
            if s.get("bits_per_raw_sample"):
                a["bit_depth"] = int(s["bits_per_raw_sample"])
            disp = s.get("disposition", {})
            a["default"] = bool(disp.get("default", 0))
            audio_list.append(a)
    if audio_list:
        info["audio"] = audio_list

    # 字幕流
    sub_list = []
    for s in streams:
        if s.get("codec_type") == "subtitle":
            sub = {}
            tags = s.get("tags", {})
            if tags.get("title"):
                sub["title"] = tags["title"]
            lang = tags.get("language", "")
            if lang:
                sub["language"] = lang
            sub["format"] = s.get("codec_name", "").upper()
            disp = s.get("disposition", {})
            sub["default"] = bool(disp.get("default", 0))
            sub["forced"] = bool(disp.get("forced", 0))
            sub_list.append(sub)
    if sub_list:
        info["subtitles"] = sub_list

    return info


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
        "runtime": "runtime",
    }
    for tag, key in simple_tags.items():
        elem = movie_elem.find(tag)
        if elem is not None and elem.text:
            result[key] = elem.text.strip()

    # 导演：支持多个 <director> 标签
    directors = []
    for elem in movie_elem.findall("director"):
        if elem is not None and elem.text and elem.text.strip():
            directors.append(elem.text.strip())
    # 单标签且含分隔符时拆分
    if not directors:
        elem = movie_elem.find("director")
        if elem is not None and elem.text and elem.text.strip():
            directors = [d.strip() for d in re.split(r'[,/&]|\band\b', elem.text.strip()) if d.strip()]
    result["director"] = directors

    # 编剧：优先 <credits>，回退到 <writer>，拆分为列表
    writer_str = ""
    for tag in ("credits", "writer"):
        elem = movie_elem.find(tag)
        if elem is not None and elem.text and elem.text.strip():
            writer_str = elem.text.strip()
            break
    result["writer"] = [w.strip() for w in re.split(r'[,/&]|\band\b', writer_str) if w.strip()] if writer_str else []

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

    # 类型：可能有多个 <genre> 标签，返回列表
    genres = []
    for elem in movie_elem.findall("genre"):
        if elem.text and elem.text.strip():
            genres.append(elem.text.strip())
    result["genre"] = genres

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

    # 提取视频技术规格
    video_basename = os.path.splitext(os.path.basename(video_path))[0]
    video_specs = extract_video_specs(video_basename)
    fileinfo = parse_fileinfo(nfo_path) if nfo_path else {}
    if fileinfo.get("width"):
        w = int(fileinfo["width"])
        if w >= 3840:
            video_specs["resolution"] = "4K"
        elif w >= 1920:
            video_specs["resolution"] = "1080p"
        elif w >= 1280:
            video_specs["resolution"] = "720p"
    if fileinfo.get("codec"):
        video_specs["video_codec"] = fileinfo["codec"]
    if fileinfo.get("audio_codec"):
        video_specs["audio"] = fileinfo["audio_codec"]

    # 提取完整技术信息（优先 ffprobe，回退到 NFO fileinfo）
    media_info = extract_media_info_ffprobe(video_path)
    if not media_info:
        # NFO 格式可能用不同标签路径
        nfo_media = parse_fileinfo(nfo_path) if nfo_path else {}
        if nfo_media:
            media_info = nfo_media
            media_info["file_path"] = video_path
            if os.path.isfile(video_path):
                media_info["file_size"] = os.path.getsize(video_path)

    movie_data = {
        "title": title,
        "original_title": nfo_data.get("original_title", ""),
        "year": nfo_data.get("year", ""),
        "plot": nfo_data.get("plot", "无简介"),
        "rating": nfo_data.get("rating", ""),
        "genre": nfo_data.get("genre", []),
        "director": nfo_data.get("director", []),
        "writer": nfo_data.get("writer", []),
        "actors": nfo_data.get("actors", []),
        "runtime": nfo_data.get("runtime", ""),
        "poster_path": poster_path,
        "fanart_path": fanart_path,
        "video_path": video_path,
        "video_specs": json.dumps(video_specs, ensure_ascii=True) if video_specs else "",
        "media_info": json.dumps(media_info, ensure_ascii=True) if media_info else "",
    }

    movie_id = database.upsert_movie(folder_path, movie_data)
    movie_data["id"] = movie_id
    return movie_data


def _get_movie_by_folder(folder_path):
    """查询数据库是否已存在该文件夹的记录。"""
    conn = database.get_connection()
    row = conn.execute(
        "SELECT id FROM movies WHERE folder_path = ?", (folder_path,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


# =============================================================================
# 电视剧扫描
# =============================================================================

# 季文件夹名匹配模式 (不区分大小写)
SEASON_FOLDER_PATTERNS = [
    re.compile(r'^Season\s*(\d{1,2})$', re.IGNORECASE),
    re.compile(r'^S(\d{1,2})$', re.IGNORECASE),
]
SPECIAL_SEASON_FOLDER_PATTERN = re.compile(r'^(?:Specials?|Season\s*0|S0{1,2})$', re.IGNORECASE)

# 从文件名提取 SxxExx 的模式（要求前面是边界或分隔符）
EPISODE_SXE_PATTERN = re.compile(r'(?:^|[_.\s\-])[Ss](\d{1,2})\s*[Ee](\d{1,2})(?!\d)')
EPISODE_CODE_FRAGMENT_PATTERN = re.compile(r'^[Ss]\d{1,2}\s*[Ee]\d{1,4}$')


def get_season_number_from_folder(folder_name):
    if SPECIAL_SEASON_FOLDER_PATTERN.match(folder_name):
        return 0
    for pattern in SEASON_FOLDER_PATTERNS:
        m = pattern.match(folder_name)
        if m:
            return int(m.group(1))
    return None


def get_episode_sxe_match(name):
    return EPISODE_SXE_PATTERN.search(name)

# 缩略图关键词
THUMB_KEYWORDS = ["thumb", "thumbnail"]


def clean_episode_title(filename, season_num=None):
    """
    从剧集文件名中提取干净的标题。
    三阶段策略：
    1. SxxExx 之后有含义的文本 → 取最前段
    2. SxxExx 之前以分隔符切分 → 取最后一段（"剧名 - 集标题 - S01E02"）
    3. 回退：\"第 N 集\"
    """
    name = os.path.splitext(filename)[0]
    sxe_match = get_episode_sxe_match(name)
    if not sxe_match:
        cleaned = clean_title(name)
        logger.debug("clean_episode_title(无SxxExx): name=%s → %s", filename, cleaned)
        return cleaned

    ep_number = int(sxe_match.group(2))

    # === 策略 1: SxxExx 之后的内容 ===
    after = name[sxe_match.end():].strip()
    if after:
        # 去掉前导分隔符和数字（年份等）
        after = re.sub(r'^[\s.\-_–—]+', '', after)
        after = re.sub(r'^[Ss]\d{1,2}\s*[Ee]\d{1,4}\s*', '', after)
        after = re.sub(r'^[\s.\-_–—]+', '', after)
        after = re.sub(r'^((?:19|20)\d{2})\s*', '', after)
        after = re.sub(r'^[\s.\-_–—]+', '', after)

        parts = re.split(r'\s*[-–—]\s*|\s{2,}', after.strip())
        for part in parts:
            part = part.strip()
            if not part or re.match(r'^[\d.]+$', part):
                continue
            if EPISODE_CODE_FRAGMENT_PATTERN.match(part):
                continue
            cleaned = clean_title(part)
            if cleaned and len(cleaned) >= 2 and not cleaned.isdigit():
                logger.debug("clean_episode_title(策略1-after): %s → %s", filename, cleaned)
                return cleaned
        # after 整体清理
        cleaned = clean_title(after)
        if cleaned and len(cleaned) >= 2 and not cleaned.isdigit():
            logger.debug("clean_episode_title(策略1-after-full): %s → %s", filename, cleaned)
            return cleaned

    # === 策略 2: SxxExx 之前的内容，取以分隔符切分的最后一段 ===
    before = name[:sxe_match.start()].strip()
    before = re.sub(r'[\s.\-_–—]+$', '', before)
    if before:
        parts = re.split(r'\s*[-–—]\s*', before)
        for part in reversed(parts):
            candidate = clean_title(part.strip())
            if candidate and len(candidate) >= 2 and not candidate.isdigit():
                if not re.match(r'^(?:19|20)\d{2}$', candidate):
                    logger.debug("clean_episode_title(策略2-before): %s → %s", filename, candidate)
                    return candidate

    # === 策略 3: 回退 ===
    fallback = f"第 {ep_number} 集"
    logger.debug("clean_episode_title(策略3-fallback): %s → %s", filename, fallback)
    return fallback


def is_tv_show_folder(folder_path):
    """检查文件夹是否包含 tvshow.nfo，有则为电视剧。"""
    tvshow_nfo = os.path.join(folder_path, "tvshow.nfo")
    return os.path.isfile(tvshow_nfo)


def parse_tvshow_nfo(nfo_path):
    """
    解析 Kodi 格式的 tvshow.nfo 文件。
    返回 dict: title, original_title, year, plot, rating, genre, director, writer, actors
    """
    try:
        tree = ET.parse(nfo_path)
        root = tree.getroot()
    except (ET.ParseError, FileNotFoundError):
        return {}

    result = {}
    tvshow_elem = root if root.tag == "tvshow" else root

    simple_tags = {
        "title": "title",
        "originaltitle": "original_title",
        "year": "year",
        "plot": "plot",
    }
    for tag, key in simple_tags.items():
        elem = tvshow_elem.find(tag)
        if elem is not None and elem.text:
            result[key] = elem.text.strip()

    # 导演：支持多个 <director> 标签
    directors = []
    for elem in tvshow_elem.findall("director"):
        if elem is not None and elem.text and elem.text.strip():
            directors.append(elem.text.strip())
    if not directors:
        elem = tvshow_elem.find("director")
        if elem is not None and elem.text and elem.text.strip():
            directors = [d.strip() for d in re.split(r'[,/&]|\band\b', elem.text.strip()) if d.strip()]
    result["director"] = directors

    # 编剧：拆分为列表
    writer_str = ""
    for tag in ("credits", "writer"):
        elem = tvshow_elem.find(tag)
        if elem is not None and elem.text and elem.text.strip():
            writer_str = elem.text.strip()
            break
    result["writer"] = [w.strip() for w in re.split(r'[,/&]|\band\b', writer_str) if w.strip()] if writer_str else []

    # 演员
    actors = []
    for actor_elem in tvshow_elem.findall("actor"):
        name_elem = actor_elem.find("name")
        role_elem = actor_elem.find("role")
        if name_elem is not None and name_elem.text and name_elem.text.strip():
            actor = {"name": name_elem.text.strip()}
            if role_elem is not None and role_elem.text and role_elem.text.strip():
                actor["role"] = role_elem.text.strip()
            actors.append(actor)
    result["actors"] = actors

    # 评分
    rating = ""
    ratings_elem = tvshow_elem.find("ratings")
    if ratings_elem is not None:
        rating_elem = ratings_elem.find("rating")
        if rating_elem is not None:
            value_elem = rating_elem.find("value")
            if value_elem is not None and value_elem.text:
                rating = value_elem.text.strip()
    if not rating:
        elem = tvshow_elem.find("rating")
        if elem is not None and elem.text:
            rating = elem.text.strip()
    result["rating"] = rating

    # 类型：返回列表
    genres = []
    for elem in tvshow_elem.findall("genre"):
        if elem.text and elem.text.strip():
            genres.append(elem.text.strip())
    result["genre"] = genres

    return result


def _read_episode_nfo_root(nfo_path):
    try:
        tree = ET.parse(nfo_path)
        return tree.getroot()
    except FileNotFoundError:
        return None
    except ET.ParseError:
        try:
            with open(nfo_path, "r", encoding="utf-8-sig") as f:
                text = f.read()
        except OSError:
            return None
        text = re.sub(r'^\s*<\?xml[^>]*\?>', '', text)
        try:
            return ET.fromstring(f"<episodes>{text}</episodes>")
        except ET.ParseError:
            logger.debug("parse_episode_nfo: 无法解析 NFO, path=%s", nfo_path)
            return None


def _episode_nfo_to_dict(ep_elem):
    result = {}

    simple_tags = {
        "title": "title",
        "plot": "plot",
        "season": "season",
        "episode": "episode",
        "runtime": "runtime",
    }
    for tag, key in simple_tags.items():
        elem = ep_elem.find(tag)
        if elem is not None and elem.text:
            val = elem.text.strip()
            if key in ("season", "episode"):
                try:
                    val = int(val)
                except ValueError:
                    val = 0
            result[key] = val

    rating = ""
    ratings_elem = ep_elem.find("ratings")
    if ratings_elem is not None:
        rating_elem = ratings_elem.find("rating")
        if rating_elem is not None:
            value_elem = rating_elem.find("value")
            if value_elem is not None and value_elem.text:
                rating = value_elem.text.strip()
    if not rating:
        elem = ep_elem.find("rating")
        if elem is not None and elem.text:
            rating = elem.text.strip()
    result["rating"] = rating

    return result


def parse_episode_nfo(nfo_path, expected_season=None, expected_episode=None):
    """
    解析 Kodi 格式的单集 NFO 文件 (<episodedetails>)。
    返回 dict: title, plot, rating, season, episode, runtime
    """
    root = _read_episode_nfo_root(nfo_path)
    if root is None:
        return {}

    candidates = [root] if root.tag == "episodedetails" else root.findall("episodedetails")
    if not candidates:
        candidates = [root]

    result = {}
    if expected_season is not None and expected_episode is not None:
        for ep_elem in candidates:
            candidate = _episode_nfo_to_dict(ep_elem)
            if (candidate.get("season") == expected_season and
                    candidate.get("episode") == expected_episode):
                result = candidate
                break

    if not result:
        result = _episode_nfo_to_dict(candidates[0])

    if not result.get("title"):
        logger.debug("parse_episode_nfo: 无title字段, path=%s", nfo_path)
    if not result.get("plot"):
        logger.debug("parse_episode_nfo: 无plot字段, path=%s", nfo_path)

    return result


def find_season_folders(tv_show_path):
    """
    在电视剧根目录下查找所有季文件夹。
    支持: Season 1, Season 01, S01, S1 等命名。
    返回: [(season_number, folder_path), ...] 按 season_number 排序。
    """
    seasons = []
    try:
        for entry in os.scandir(tv_show_path):
            if not entry.is_dir():
                continue
            season_number = get_season_number_from_folder(entry.name)
            if season_number is not None:
                seasons.append((season_number, entry.path))
    except OSError:
        pass
    seasons.sort(key=lambda x: x[0])
    return seasons


def find_thumb_in_folder(folder_path, episode_basename=None):
    """
    在文件夹中查找缩略图。
    1. 如果提供了 episode_basename，优先匹配同名 -thumb 文件
    2. 模糊匹配包含 thumb/thumbnail 关键词的文件
    3. 如果没有 thumb 图，返回第一个非海报/非 fanart 的图片
    """
    image_exts = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}

    # 如果有 episode 基础名，精准匹配
    if episode_basename:
        for ext in image_exts:
            # 匹配 pattern: basename-thumb.ext 或 basename_thumb.ext
            for sep in ("-thumb", "_thumb", "-thumbnail", "_thumbnail"):
                candidate = os.path.join(folder_path, f"{episode_basename}{sep}{ext}")
                if os.path.isfile(candidate):
                    return candidate
            # 匹配 basename 包含 thumb 关键词的情况
            try:
                for entry in os.scandir(folder_path):
                    if entry.is_file():
                        entry_ext = os.path.splitext(entry.name)[1].lower()
                        if entry_ext not in image_exts:
                            continue
                        name_no_ext = os.path.splitext(entry.name)[0].lower()
                        if episode_basename.lower() in name_no_ext:
                            for kw in THUMB_KEYWORDS:
                                if kw in name_no_ext:
                                    return entry.path
            except OSError:
                pass

    # 模糊匹配任何包含 thumb 的图片
    try:
        for entry in os.scandir(folder_path):
            if entry.is_file():
                ext = os.path.splitext(entry.name)[1].lower()
                if ext in image_exts:
                    name_lower = entry.name.lower()
                    for kw in THUMB_KEYWORDS:
                        if kw in name_lower:
                            return entry.path
    except OSError:
        pass

    return ""


def find_nfo_for_episode(folder_path, episode_basename):
    """查找与视频文件同名的 .nfo 文件。"""
    nfo_path = os.path.join(folder_path, f"{episode_basename}.nfo")
    if os.path.isfile(nfo_path):
        return nfo_path
    # 模糊匹配：在文件夹里找与 episode_basename 开头的 nfo
    try:
        for entry in os.scandir(folder_path):
            if entry.is_file() and entry.name.lower().endswith(".nfo"):
                name_no_ext = os.path.splitext(entry.name)[0]
                if name_no_ext == episode_basename:
                    return entry.path
    except OSError:
        pass
    return ""


def scan_tv_show(folder_path):
    """
    扫描单个电视剧目录：解析 tvshow.nfo、遍历季文件夹扫描单集。
    返回: (show_data_dict, [episode_data_dict, ...])
    """
    if not os.path.isdir(folder_path):
        return None, []

    # 解析 tvshow.nfo
    nfo_path = os.path.join(folder_path, "tvshow.nfo")
    nfo_data = parse_tvshow_nfo(nfo_path) if os.path.isfile(nfo_path) else {}

    # 标题来源：nfo.title > 文件夹名
    title = nfo_data.get("title") or os.path.basename(folder_path)

    # 查找海报和 fanart
    poster_path = find_poster(folder_path)
    fanart_path = find_fanart(folder_path)

    # 查找季文件夹
    season_folders = find_season_folders(folder_path)

    # 扫描所有单集
    episodes = []
    for season_num, season_path in season_folders:
        try:
            for entry in os.scandir(season_path):
                if not entry.is_file():
                    continue
                ext = os.path.splitext(entry.name)[1].lower()
                if ext not in VIDEO_EXTENSIONS:
                    continue

                video_path = entry.path
                video_basename = os.path.splitext(entry.name)[0]

                # 尝试从文件名提取 SxxExx
                sxe_match = get_episode_sxe_match(entry.name)
                ep_season = season_num
                ep_number = 0
                if sxe_match:
                    ep_season = int(sxe_match.group(1))
                    ep_number = int(sxe_match.group(2))
                else:
                    # 分配序号（取该季已有最大序号 + 1）
                    existing_numbers = [e["episode"] for e in episodes if e["season"] == season_num]
                    ep_number = max(existing_numbers) + 1 if existing_numbers else 1

                # 查找配套文件
                nfo_path_ep = find_nfo_for_episode(season_path, video_basename)
                ep_nfo = parse_episode_nfo(nfo_path_ep, ep_season, ep_number) if nfo_path_ep else {}

                # 标题优先级：NFO title > 从文件名智能提取 > 清理后的文件名
                if ep_nfo.get("title"):
                    ep_title = ep_nfo["title"]
                else:
                    ep_title = clean_episode_title(entry.name, season_num)

                # 缩略图
                thumb_path = find_thumb_in_folder(season_path, video_basename)

                ep_data = {
                    "season": ep_season if isinstance(ep_season, int) else season_num,
                    "episode": ep_number if isinstance(ep_number, int) else 0,
                    "title": str(ep_title) if not isinstance(ep_title, str) else ep_title,
                    "plot": ep_nfo.get("plot") or "",
                    "rating": str(ep_nfo.get("rating", "")) if ep_nfo.get("rating") else "",
                    "thumb_path": thumb_path,
                    "video_path": video_path,
                    "media_info": "",
                }
                # 尝试提取技术信息
                ep_media_info = extract_media_info_ffprobe(video_path)
                if not ep_media_info:
                    nfo_ep_info = parse_fileinfo(nfo_path_ep) if nfo_path_ep else {}
                    if nfo_ep_info:
                        ep_media_info = nfo_ep_info
                        ep_media_info["file_path"] = video_path
                        if os.path.isfile(video_path):
                            ep_media_info["file_size"] = os.path.getsize(video_path)
                if ep_media_info:
                    ep_data["media_info"] = json.dumps(ep_media_info, ensure_ascii=True)
                episodes.append(ep_data)

        except OSError:
            continue

    # 提取视频技术规格：从文件夹名 + 第一个单集文件名
    video_specs = extract_video_specs(os.path.basename(folder_path))
    if episodes:
        ep_name = os.path.splitext(os.path.basename(episodes[0]["video_path"]))[0]
        ep_specs = extract_video_specs(ep_name)
        for k, v in ep_specs.items():
            if v and (not video_specs.get(k)):
                video_specs[k] = v
    # NFO fileinfo 补充
    fileinfo = parse_fileinfo(nfo_path) if os.path.isfile(nfo_path) else {}
    if fileinfo.get("width"):
        w = int(fileinfo["width"])
        if w >= 3840:
            video_specs["resolution"] = "4K"
        elif w >= 1920:
            video_specs["resolution"] = "1080p"
        elif w >= 1280:
            video_specs["resolution"] = "720p"
    if fileinfo.get("codec"):
        video_specs["video_codec"] = fileinfo["codec"]
    if fileinfo.get("audio_codec"):
        video_specs["audio"] = fileinfo["audio_codec"]

    show_data = {
        "title": title,
        "original_title": nfo_data.get("original_title", ""),
        "year": nfo_data.get("year", ""),
        "plot": nfo_data.get("plot", "无简介"),
        "rating": nfo_data.get("rating", ""),
        "genre": nfo_data.get("genre", []),
        "director": nfo_data.get("director", []),
        "writer": nfo_data.get("writer", []),
        "actors": nfo_data.get("actors", []),
        "poster_path": poster_path,
        "fanart_path": fanart_path,
        "season_count": len(season_folders),
        "video_specs": json.dumps(video_specs, ensure_ascii=True) if video_specs else "",
    }

    return show_data, episodes


# =============================================================================
# 更新后的全量扫描（电影 + 电视剧）
# =============================================================================


def scan_all_roots(progress_callback=None, full_refresh=True, incremental=False):
    """
    扫描所有配置的媒体库根目录，包括电影和电视剧。

    扫描逻辑：
    1. 先扫描根目录的直接子文件夹（电影）
    2. 再扫描子文件夹中是否有 tvshow.nfo（电视剧）
    3. 全量刷新时清理数据库中不存在的过期记录
    4. 增量模式：跳过数据库中已存在的文件夹，仅扫描新增目录

    Returns:
        dict: {"total_movies", "total_shows", "total_episodes", "added", "updated", "deleted", "errors"}
    """
    media_roots = database.get_setting("media_roots")
    if not media_roots:
        logger.warning("未配置媒体库根目录")
        if progress_callback:
            progress_callback("complete", "未配置媒体库根目录")
        return {"total_movies": 0, "total_shows": 0, "total_episodes": 0,
                "added": 0, "updated": 0, "deleted": 0, "errors": []}

    stats = {"total_movies": 0, "total_shows": 0, "total_episodes": 0,
             "added": 0, "updated": 0, "deleted": 0, "errors": []}
    on_disk_movie_paths = set()
    on_disk_show_paths = set()

    # 增量模式：加载已存在的文件夹路径，跳过已有条目
    skip_paths = set()
    if incremental:
        skip_paths = database.get_all_folder_paths()
        logger.info("增量扫描模式：跳过 %d 个已有文件夹", len(skip_paths))
        if progress_callback:
            progress_callback("info", f"增量扫描模式：跳过 {len(skip_paths)} 个已有文件夹")

    # 收集所有需要扫描的目录
    all_dirs = []
    for root_dir in media_roots:
        if not os.path.isdir(root_dir):
            logger.warning("目录不存在: %s", root_dir)
            stats["errors"].append(f"目录不存在: {root_dir}")
            continue
        for dirpath, _dirnames, filenames in os.walk(root_dir):
            has_video = any(
                os.path.splitext(f)[1].lower() in VIDEO_EXTENSIONS
                for f in filenames
            )
            if has_video or os.path.isfile(os.path.join(dirpath, "tvshow.nfo")):
                all_dirs.append(dirpath)

    # 第一遍：识别电视剧根目录（有 tvshow.nfo 的）
    tv_show_roots = set()
    for dirpath in all_dirs:
        if is_tv_show_folder(dirpath):
            tv_show_roots.add(dirpath)

    # 第二遍：排除电视剧子文件夹（这些由 scan_tv_show 统一处理）
    movie_dirs = []
    for dirpath in all_dirs:
        # 检查这个目录是否在某个电视剧根目录的子路径下
        is_tv_child = False
        for tv_root in tv_show_roots:
            if dirpath == tv_root:
                is_tv_child = True  # 电视剧根目录本身，由 TV 扫描处理
                break
            if os.path.commonpath([dirpath, tv_root]) == tv_root and dirpath != tv_root:
                is_tv_child = True
                break
        if not is_tv_child:
            movie_dirs.append(dirpath)

    # 扫描电视剧
    for show_root in sorted(tv_show_roots):
        if incremental and show_root in skip_paths:
            continue
        if progress_callback:
            progress_callback("scanning", f"[电视剧] {show_root}")

        try:
            conn = database.get_connection()
            existing = conn.execute(
                "SELECT id FROM shows WHERE folder_path = ?", (show_root,)
            ).fetchone()
            conn.close()
            is_new = existing is None
        except Exception:
            is_new = True

        try:
            show_data, episodes = scan_tv_show(show_root)
            if show_data:
                show_id = database.upsert_show(show_root, show_data)
                on_disk_show_paths.add(show_root)
                stats["total_shows"] += 1
                if is_new:
                    stats["added"] += 1
                else:
                    stats["updated"] += 1

                # 写入单集（upsert 保留 is_watched 状态）
                on_disk_ep_keys = set()
                for ep in episodes:
                    database.upsert_episode(show_id, ep["season"], ep["episode"], ep)
                    on_disk_ep_keys.add((ep["season"], ep["episode"]))
                    stats["total_episodes"] += 1

                # 清理磁盘上已不存在的单集
                database.delete_stale_episodes(show_id, on_disk_ep_keys)

                if progress_callback:
                    label = "新增" if is_new else "更新"
                    progress_callback("found", f"[{label} 电视剧] {show_data['title']} ({len(episodes)} 集)")
                logger.info("[%s] 电视剧: %s (%d 集)", label, show_data['title'], len(episodes))
        except Exception as e:
            logger.error("扫描电视剧失败 %s: %s", show_root, e, exc_info=True)
            stats["errors"].append(f"{show_root}: {str(e)}")

    # 扫描电影
    for dirpath in sorted(movie_dirs):
        if incremental and dirpath in skip_paths:
            continue
        if progress_callback:
            progress_callback("scanning", dirpath)

        try:
            conn = database.get_connection()
            existing = conn.execute(
                "SELECT id FROM movies WHERE folder_path = ?", (dirpath,)
            ).fetchone()
            conn.close()
            is_new = existing is None
        except Exception:
            is_new = True

        try:
            result = scan_folder(dirpath)
            if result:
                on_disk_movie_paths.add(dirpath)
                stats["total_movies"] += 1
                if is_new:
                    stats["added"] += 1
                else:
                    stats["updated"] += 1

                if progress_callback:
                    label = "新增" if is_new else "更新"
                    progress_callback("found", f"[{label} 电影] {result['title']}")
                logger.info("[%s] 电影: %s", label, result['title'])
        except Exception as e:
            logger.error("扫描电影失败 %s: %s", dirpath, e, exc_info=True)
            stats["errors"].append(f"{dirpath}: {str(e)}")

    # 全量刷新：删除磁盘上已不存在的记录
    if full_refresh:
        if progress_callback:
            progress_callback("cleanup", "正在清理过期记录...")
        deleted_count = database.delete_stale_media(on_disk_movie_paths, on_disk_show_paths)
        stats["deleted"] = deleted_count
        if deleted_count > 0:
            logger.info("清理过期记录: %d 条", deleted_count)
        if progress_callback and deleted_count > 0:
            progress_callback("cleanup", f"已清理 {deleted_count} 条过期记录")

    if progress_callback:
        parts = [
            f"扫描完成：电影 {stats['total_movies']} 部，电视剧 {stats['total_shows']} 部，单集 {stats['total_episodes']} 集",
        ]
        if stats["added"] > 0:
            parts.append(f"新增 {stats['added']}")
        if stats["updated"] > 0:
            parts.append(f"更新 {stats['updated']}")
        if stats["deleted"] > 0:
            parts.append(f"清理 {stats['deleted']}")
        parts.append(f"错误 {len(stats['errors'])}")
        progress_callback("complete", "，".join(parts))

    return stats
