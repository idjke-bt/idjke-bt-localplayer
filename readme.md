<!-- markdownlint-disable MD033 -->
<p align="center">
  <img src="https://img.shields.io/badge/python-3.8+-blue.svg" alt="Python 3.8+">
  <img src="https://img.shields.io/badge/flask-2.x-green.svg" alt="Flask 2.x">
  <img src="https://img.shields.io/badge/license-MIT-orange.svg" alt="License MIT">
  <img src="https://img.shields.io/badge/platform-Windows-lightgrey.svg" alt="Platform Windows">
</p>

<p align="center">
  <h1 align="center">🎬 LocalPlayer</h1>
  <p align="center">本地媒体库管理工具 · 基于 Flask + SQLite 的轻量级媒体中心</p>
</p>

---

## 预览

深色主题、Emby 风格界面，支持海报墙浏览、媒体详情、电视剧季/集管理。

- **海报墙** — 响应式网格布局，hover 播放按钮覆盖层，侧边栏按类型/收藏筛选，fanart 动态背景
- **电影详情** — 左海报 + 右信息布局，fanart 全屏背景渐变遮罩，技术规格标签（分辨率/编码/HDR/音频）
- **电视剧详情** — 季标签切换，单集横向滚动卡片，缩略图预览，整季/整剧批量标记已看
- **技术信息** — ffprobe 提取完整视频/音频/字幕流详情，三列网格卡片展示
- **外部播放器** — 一键调用 mpv / VLC / PotPlayer 播放，自动检测安装路径

---

## 功能

### 媒体扫描

- 递归扫描配置的媒体库根目录，自动识别**电影**和**电视剧**（通过 `tvshow.nfo` 区分）
- 电视剧季目录识别：`Season 1` / `S01` 等命名格式
- 解析 Kodi XBMC 格式的 `movie.nfo`、`tvshow.nfo`、单集 NFO，提取完整元数据（标题、导演、演员、评分、简介、时长等）
- 海报自动发现：精确匹配 `poster.jpg` → 模糊匹配含 `poster`/`folder`/`cover` 关键词的图片
- 背景图自动发现：精确匹配 `fanart.jpg` → 模糊匹配含 `fanart`/`backdrop`/`background` 关键词的图片
- 视频文件名智能清理：去除分辨率、编码、音轨、压制组等标签，提取干净标题
- 视频规格提取：从文件名识别分辨率、编码、HDR 类型、音频格式、来源版本
- 支持 **ffprobe**（可选）提取详细技术信息：视频/音频/字幕流、比特率、色域、帧率等
- **全量扫描** 自动清理过期记录；**增量扫描** 仅扫描新增文件夹

### 媒体管理

- 电影/电视剧分开管理，侧边栏快速筛选（全部 / 电影 / 电视剧 / 收藏）
- 按标题、年份、评分排序；按类型标签筛选；全文搜索（标题/原名/简介）
- **已看/未看** 状态管理（电影、单集、整季、整剧批量操作）
- **收藏**功能 — 侧边栏收藏入口，导航栏心形按钮快速切换
- 删除媒体记录（不影响实际文件）

### 外部播放器

- 自动检测系统中已安装的播放器：mpv / VLC / PotPlayer
- 播放时设置全屏+窗口置顶参数
- 播放后自动标记为已看

### 技术信息展示

- 视频流：编解码器、配置/等级、分辨率、宽高比、帧率、比特率、色域、位深度
- 音频流：编解码器、声道布局、语言、声道数、采样率
- 字幕流：格式、语言、默认/强制标记

---

## 技术栈

| 层级   | 技术                                      |
| ------ | ----------------------------------------- |
| 后端   | Flask (仅监听 127.0.0.1)                  |
| 数据库 | SQLite (WAL 模式, 外键约束)               |
| 前端   | 原生 HTML/CSS/JS (零外部依赖)              |
| 元数据 | ElementTree 解析 Kodi NFO XML             |
| 媒体信息 | ffprobe (可选, JSON 输出)               |
| 扫描进度 | Server-Sent Events (SSE)                |
| 文件夹选择 | PowerShell 调用 Windows.Forms         |

---

## 快速开始

### 环境要求

- Python 3.8+
- Windows 操作系统
- （可选）[ffprobe](https://ffmpeg.org/download.html) — 获取详细技术信息

### 安装与启动

```bash
# 克隆仓库
git clone <your-repo-url>
cd localplayer

# 创建 conda 环境
conda create -n localplayer python=3.10
conda activate localplayer

# 安装依赖
pip install flask

# 启动应用
python app.py
```

启动后自动打开浏览器访问 `http://127.0.0.1:5000`。

### 初始配置

1. 进入**设置**页 → 添加媒体库根目录（存放电影/电视剧的文件夹路径）
2. 点击**立即扫描**，等待扫描完成
3. 回到海报墙，即可浏览和管理媒体库

---

## 项目结构

```
localplayer/
├── app.py              # Flask 主应用, REST API 路由
├── database.py         # SQLite 数据库模块, CRUD 操作
├── scanner.py          # 媒体扫描器, NFO 解析, 文件查找
├── templates/
│   └── index.html      # 单页应用 HTML
├── static/
│   ├── app.js          # 前端逻辑 (海报墙/详情/设置/扫描)
│   └── style.css       # Emby 风格深色主题, 响应式布局
├── logs/               # 运行日志 (app.log / error.log)
├── localplayer.db      # SQLite 数据库文件
└── README.md
```

---

## API 概览

| 方法   | 路径                              | 说明                   |
| ------ | --------------------------------- | ---------------------- |
| GET    | `/api/movies`                     | 电影列表 (sort/genre/favorite/search) |
| GET    | `/api/movies/<id>`                | 电影详情               |
| POST   | `/api/movies/<id>/play`           | 调用外部播放器播放     |
| POST   | `/api/movies/<id>/watched`        | 切换已看状态           |
| POST   | `/api/movies/<id>/favorite`       | 切换收藏状态           |
| DELETE | `/api/movies/<id>`                | 删除电影记录           |
| GET    | `/api/shows`                      | 电视剧列表             |
| GET    | `/api/shows/<id>`                 | 电视剧详情             |
| GET    | `/api/shows/<id>/episodes`        | 单集列表（按季分组）   |
| POST   | `/api/shows/<id>/favorite`        | 切换电视剧收藏         |
| POST   | `/api/shows/<id>/watched`         | 整剧批量标记已看       |
| DELETE | `/api/shows/<id>`                 | 删除电视剧及单集       |
| POST   | `/api/episodes/<id>/play`         | 播放单集               |
| POST   | `/api/episodes/<id>/watched`      | 单集已看切换           |
| GET    | `/api/all_media`                  | 电影+电视剧统一查询    |
| GET    | `/api/genres`                     | 所有类型标签           |
| POST   | `/api/scan`                       | 触发扫描 (mode=full/incremental) |
| GET    | `/api/scan/progress`              | SSE 扫描进度推送       |
| POST   | `/api/reset`                      | 重置数据库             |
| GET    | `/api/settings`                   | 读取设置               |
| POST   | `/api/settings`                   | 更新设置               |
| POST   | `/api/browse-folder`              | 系统文件夹选择对话框   |

---

## 数据目录规范

扫描器按以下规范识别文件夹内的媒体资源：

```
电影/
├── Avatar (2009)/
│   ├── Avatar.2009.2160p.BluRay.x265.mkv    # 视频文件
│   ├── movie.nfo                             # Kodi 元数据 (可选)
│   ├── poster.jpg                            # 海报
│   └── fanart.jpg                            # 背景图 (可选)

电视剧/
├── Breaking Bad/
│   ├── tvshow.nfo                            # 电视剧元数据
│   ├── poster.jpg                            # 海报
│   ├── fanart.jpg                            # 背景图
│   ├── Season 1/
│   │   ├── Breaking.Bad.S01E01.mkv
│   │   ├── Breaking.Bad.S01E01-thumb.jpg     # 缩略图 (可选)
│   │   └── Breaking.Bad.S01E01.nfo           # 单集元数据 (可选)
│   └── Season 2/
│       └── ...
```

- 支持的视频格式：`.mkv` `.mp4` `.avi` `.mov` `.wmv` `.flv` `.webm` `.m4v` `.mpg` `.mpeg`
- 海报匹配优先级：`poster.jpg/png` > `folder.jpg/png` > `cover.jpg/png` > 含关键词模糊匹配
- 背景图匹配优先级：`fanart.jpg/png` > `backdrop.jpg` > `background.jpg` > 含关键词模糊匹配
- 视频文件名自动清理：移除分辨率、编码、音轨、压制组等标签，提取干净的媒体标题

---

## License

MIT
