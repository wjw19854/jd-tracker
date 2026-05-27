# Docker 部署指南

## 快速启动（本地测试）

### 1. 获取登录态

Docker 容器以 headless 模式运行，无法手动登录。需要先在本地有头模式下登录一次：

```bash
uv run jd-tracker
```

登录成功后，`data/auth.json` 会自动保存。

### 2. 复制登录态到 compose 目录

```bash
cp data/auth.json docker/data/
```

### 3. 启动

```bash
cd docker
docker compose up -d
```

### 4. 查看日志

```bash
docker compose logs -f
```

## 服务器部署

### 1. 本地构建并推送镜像

```bash
# 编辑 docker/push.sh，将 IMAGE 改为你的 Docker Hub 用户名
# IMAGE="yourusername/jd-tracker"

chmod +x docker/push.sh
./docker/push.sh 0.2.1
```

### 2. 上传到服务器

```bash
# 上传 compose 文件
scp docker/docker-compose.yml user@server:~/jd-tracker/

# 上传登录态（首次）
scp data/auth.json user@server:~/jd-tracker/data/
```

### 3. 服务器端操作

```bash
# SSH 登录服务器
ssh user@server

# 创建目录结构
mkdir -p ~/jd-tracker/data ~/jd-tracker/logs

# 如果已推送 Docker Hub，将 compose 中的 build 替换为 image
# sed -i '' 's/build:/# build:/' docker-compose.yml  # 或手动编辑

# 拉取镜像并启动
cd ~/jd-tracker
docker compose up -d

# 验证
docker compose logs -f
```

### 4. 后续更新

```bash
# 本地构建新版本
./docker/push.sh 0.2.2

# 服务器拉取并重启
ssh user@server "cd ~/jd-tracker && docker compose pull && docker compose up -d"
```

## 数据持久化

卷挂载在 compose 同级目录下：

```
docker/
├── data/           ← auth.json + cart_snapshot.jsonl（挂载到容器 /app/data）
├── logs/           ← jd_tracker.log + 截图（挂载到容器 /app/logs）
├── docker-compose.yml
├── Dockerfile
├── entrypoint.sh
├── push.sh
└── README.md
```

容器更新/替换不会影响这两个目录中的数据。

## 配置

通过修改 `docker-compose.yml` 中的环境变量覆盖默认配置：

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `JD_TRACKER_INTERVAL` | `1800` | 执行间隔（秒），建议 ≥ 900（15 分钟） |
| `JD_TRACKER_ACTIVE_HOURS` | (空=全天) | 活跃时间段，如 `8-23` 仅 08:00-22:59 运行 |
| `JD_TRACKER_HEADLESS` | `true` | 无头模式（必须） |
| `JD_TRACKER_CHROME_CHANNEL` | (空) | 浏览器 channel，空=Playwright Chromium |
| `JD_TRACKER_LOGIN_MAX_RETRIES` | `5` | 登录检测最大重试次数 |
| `JD_TRACKER_JITTER_RATIO` | `0.3` | 随机抖动比例 |

## 登录态过期

当 `auth.json` 中的 cookie 过期（通常 1-2 周），容器日志会显示登录检测失败。

解决方法：

在本机重新有头模式运行一次，将新的 `auth.json` 复制到服务器：

```bash
# 本地
uv run jd-tracker

# 上传新登录态
scp data/auth.json user@server:~/jd-tracker/data/

# 服务器重启
ssh user@server "cd ~/jd-tracker && docker compose restart"
```
