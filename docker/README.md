# Docker 部署指南

## 首次部署

### 1. 获取登录态

Docker 容器以 headless 模式运行，无法手动登录。需要先在本地有头模式下登录一次：

```bash
# 本地执行（打开浏览器窗口，手动登录京东）
uv run jd-tracker
```

登录成功后，`data/auth.json` 会自动保存。

### 2. 复制登录态

```bash
# 将 auth.json 复制到项目根目录（或部署服务器的 docker-compose 所在目录）
cp data/auth.json /path/to/deploy/data/
```

### 3. 启动容器

```bash
cd docker
docker compose up -d
```

### 4. 查看日志

```bash
docker compose logs -f
```

### 5. 查看监控数据

```bash
# 最新快照
cat ../data/cart_snapshot.jsonl

# 运行日志
tail -f ../logs/jd_tracker.log
```

## 配置

通过修改 `docker-compose.yml` 中的环境变量覆盖默认配置：

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `JD_TRACKER_INTERVAL` | `1800` | 执行间隔（秒），建议 ≥ 900（15分钟） |
| `JD_TRACKER_HEADLESS` | `true` | 无头模式（必须） |
| `JD_TRACKER_CHROME_CHANNEL` | (空) | 浏览器 channel，空=Playwright Chromium |
| `JD_TRACKER_LOGIN_MAX_RETRIES` | `5` | 登录检测最大重试次数 |
| `JD_TRACKER_JITTER_RATIO` | `0.3` | 随机抖动比例 |

## 构建并推送到 Docker Hub

```bash
# 构建
docker build -t yourusername/jd-tracker:latest -f docker/Dockerfile .

# 推送
docker push yourusername/jd-tracker:latest
```

然后在 `docker-compose.yml` 中将 `build` 替换为 `image`：

```yaml
services:
  jd-tracker:
    image: yourusername/jd-tracker:latest
    # build: ...   # 注释掉
```

## 登录态过期

当 `auth.json` 中的 cookie 过期（通常 1-2 周），容器日志会显示登录检测失败。

解决方法：在本机重新有头模式运行一次，将新的 `auth.json` 复制到容器挂载的 `data/` 目录，然后重启容器：

```bash
docker compose restart
```
