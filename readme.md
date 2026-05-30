# LocalPlayer

本地媒体库管理工具，通过 Web 界面浏览和播放存储在本地硬盘上的电影和电视剧。

基于 Flask + SQLite，纯离线运行，通过外部播放器（mpv/VLC/PotPlayer）播放视频文件。

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端 | Flask (仅监听 127.0.0.1:5000) |
| 数据库 | SQLite |
| 前端 | HTML + vanilla JS + CSS（无外部依赖） |
| NFO 解析 | Python ElementTree |
| 媒体信息 | ffprobe（可选） |

## 环境要求

- Python 3.8+
- Windows
- （可选）ffprobe

## 启动

```bash
conda create -n localplayer python=3.10
conda activate localplayer
pip install flask
python app.py
```

浏览器自动打开 `http://127.0.0.1:5000`。首次使用需在设置页添加媒体库根目录并执行扫描。

## 项目结构

```
localplayer/
├── app.py              # Flask 主应用、API 路由
├── database.py         # SQLite 数据库 CRUD
├── scanner.py          # 媒体扫描、NFO 解析、文件查找
├── templates/
│   └── index.html      # 前端页面
├── static/
│   ├── app.js          # 前端逻辑
│   └── style.css       # 样式
├── localplayer.db      # 数据库文件
└── logs/               # 运行日志
```

## API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/movies` | 电影列表 |
| GET | `/api/movies/<id>` | 电影详情 |
| POST | `/api/movies/<id>/play` | 调用外部播放器播放 |
| POST | `/api/movies/<id>/watched` | 切换已看 |
| POST | `/api/movies/<id>/favorite` | 切换收藏 |
| DELETE | `/api/movies/<id>` | 删除记录 |
| GET | `/api/shows` | 电视剧列表 |
| GET | `/api/shows/<id>` | 电视剧详情 |
| GET | `/api/shows/<id>/episodes` | 单集列表 |
| POST | `/api/episodes/<id>/play` | 播放单集 |
| POST | `/api/episodes/<id>/watched` | 单集已看切换 |
| POST | `/api/shows/<id>/watched` | 整剧标记已看 |
| GET | `/api/all_media` | 电影+电视剧统一查询 |
| GET | `/api/genres` | 类型标签列表 |
| POST | `/api/scan` | 触发扫描 |
| GET | `/api/scan/progress` | SSE 扫描进度 |
| POST | `/api/reset` | 重置数据库 |
| GET/POST | `/api/settings` | 读取/更新设置 |
| POST | `/api/browse-folder` | 文件夹选择对话框 |

## 目录规范

扫描器按以下结构识别媒体文件：

```
电影/
├── Avatar (2009)/
│   ├── Avatar.2009.2160p.mkv
│   ├── movie.nfo
│   ├── poster.jpg
│   └── fanart.jpg

电视剧/
├── Breaking Bad/
│   ├── tvshow.nfo
│   ├── poster.jpg
│   ├── fanart.jpg
│   └── Season 1/
│       ├── S01E01.mkv
│       ├── S01E01-thumb.jpg
│       └── S01E01.nfo
```