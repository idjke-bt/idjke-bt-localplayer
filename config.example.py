"""
config.example.py — 应用配置模板
复制为 config.py 并根据本地环境修改
"""

import os

# 项目根目录
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 日志目录
LOG_DIR = os.path.join(BASE_DIR, "logs")

# 数据库路径
DB_PATH = os.path.join(BASE_DIR, "localplayer.db")

# Flask 服务配置
FLASK_HOST = "127.0.0.1"
FLASK_PORT = 5000

# 播放器默认路径
DEFAULT_PLAYER_PATH = r"D:\tools\mpv-lazy\mpv-lazy.exe"

# 常见播放器安装路径（用于自动检测）
PLAYER_CANDIDATES = [
    r"D:\tools\mpv-lazy\mpv-lazy.exe",
    r"C:\tools\mpv-lazy\mpv-lazy.exe",
    r"C:\Program Files\mpv\mpv.exe",
    r"C:\Program Files (x86)\mpv\mpv.exe",
    # VLC
    r"C:\Program Files\VideoLAN\VLC\vlc.exe",
    r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe",
    # PotPlayer
    r"C:\Program Files\DAUM\PotPlayer\PotPlayerMini64.exe",
    r"C:\Program Files (x86)\DAUM\PotPlayer\PotPlayerMini.exe",
]
