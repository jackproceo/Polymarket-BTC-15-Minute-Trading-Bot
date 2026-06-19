# Ubuntu + Docker 安装说明

> **适用系统**: Ubuntu 20.04 / 22.04 / 24.04（LTS）  
> **更新时间**: 2026-06-18  
> **前置条件**: 一台可以访问互联网的 Linux 服务器或 VPS

---

## 目录

1. [Ubuntu 安装 Docker](#1-ubuntu-安装-docker)
2. [项目文件说明](#2-项目文件说明)
3. [快速启动（推荐）](#3-快速启动推荐)
4. [手动构建与运行](#4-手动构建与运行)
5. [多容器生产部署](#5-多容器生产部署)
6. [配置详解](#6-配置详解)
7. [运行模式](#7-运行模式)
8. [监控与访问](#8-监控与访问)
9. [维护管理](#9-维护管理)
10. [常见问题排查](#10-常见问题排查)
11. [命令速查表](#11-命令速查表)

---

## 1. Ubuntu 安装 Docker

### 1.1 一键安装（推荐）

```bash
# 安装 Docker（官方脚本）
curl -fsSL https://get.docker.com | sudo bash

# 将当前用户加入 docker 组（避免每次 sudo）
sudo usermod -aG docker $USER

# 退出重新登录，或刷新组
newgrp docker

# 验证安装
docker --version
docker compose version
```

### 1.2 分步安装（如需自定义）

```bash
# 卸载旧版本
sudo apt remove docker docker-engine docker.io containerd runc

# 安装依赖
sudo apt update
sudo apt install -y ca-certificates curl gnupg

# 添加 Docker 官方 GPG 密钥
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | \
    sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

# 添加 Docker 仓库
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# 安装 Docker Engine + Compose
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

# 启动并设置开机自启
sudo systemctl enable docker
sudo systemctl start docker
```

### 1.3 验证安装

```bash
docker run --rm hello-world
# 输出 Hello from Docker! 表示成功

docker compose version
# 输出 Docker Compose version v2.x.x
```

---

## 2. 项目文件说明

项目根目录下与 Docker 相关的文件：

```text
polymarket-btc-15m-bot/
├── Dockerfile               # 镜像构建文件（多阶段构建）
├── docker-compose.yml       # Docker Compose 编排（bot + Redis）
├── .dockerignore            # 构建上下文排除列表
├── entrypoint.sh            # 容器入口脚本（等待 Redis + 启动 bot）
│
├── .env                     # 你的环境变量配置（需手动创建）
├── .env.example             # 配置模板
├── bot.py                   # 主程序入口
├── requirements.txt         # Python 依赖
│
├── data/                    # 交易数据（Docker 卷挂载）
├── logs/                    # 日志文件（Docker 卷挂载）
│
└── docs/
    └── Docker安装说明.md     # 本文档
```

### 各文件作用

| 文件 | 作用 |
|------|------|
| `Dockerfile` | 两阶段构建：第一阶段安装 Rust 编译 nautilus_trader，第二阶段运行 |
| `docker-compose.yml` | 定义 bot + Redis 两个服务，网络连通，端口映射 |
| `.dockerignore` | 排除 `.env`、`venv/`、`__pycache__/` 等不需要的文件 |
| `entrypoint.sh` | 等待 Redis 就绪 → 创建目录 → 校验配置 → 启动 bot |

---

## 3. 快速启动（推荐）

### 3.1 下载项目

```bash
git clone https://github.com/yourusername/polymarket-btc-15m-bot.git
cd polymarket-btc-15m-bot
```

### 3.2 配置环境变量

```bash
cp .env.example .env
nano .env   # 用你喜欢的编辑器填写配置
```

最小配置（模拟模式只需要钱包地址）：
```ini
POLYMARKET_FUNDER=0x你的Polygon钱包地址
```

完整配置（如需实盘交易）：
```ini
POLYMARKET_PK=你的钱包私钥
POLYMARKET_API_KEY=你的API Key
POLYMARKET_API_SECRET=你的API Secret
POLYMARKET_PASSPHRASE=你的Passphrase
POLYMARKET_FUNDER=0x你的钱包地址
```

### 3.3 启动（模拟模式）

```bash
# 后台启动 bot + Redis
docker compose up -d

# 查看启动日志
docker compose logs -f bot

# 看到如下输出表示启动成功：
# [ENTRYPOINT] Starting bot...
# SIMULATION MODE — paper trading only
# ✓ Trading dashboard started at http://0.0.0.0:3000
```

### 3.4 打开监控面板

浏览器访问 **http://你的服务器IP:3000** 查看实时交易面板。

### 3.5 停止

```bash
docker compose down
```

> 💡 `docker compose down` 停止容器但保留数据。加 `-v` 会删除数据卷：
> ```bash
> docker compose down -v   # ⚠️ 会清空交易记录和日志
> ```

---

## 4. 手动构建与运行

如果不使用 docker-compose，也可以单独构建运行：

### 4.1 构建镜像

```bash
# 构建镜像（首次约 5-15 分钟，取决于网络和 CPU）
docker build -t polymarket-bot .

# 查看构建好的镜像
docker images | grep polymarket-bot
```

### 4.2 运行容器

```bash
# 模拟模式（默认）
docker run -d \
  --name polymarket-bot \
  --restart unless-stopped \
  --env-file .env \
  -e REDIS_HOST=host.docker.internal \
  -p 3000:3000 \
  -p 8000:8000 \
  -v bot-data:/app/data \
  -v bot-logs:/app/logs \
  polymarket-bot

# 测试模式（1 分钟周期）
docker run -d \
  --name polymarket-bot-test \
  --env-file .env \
  -e REDIS_HOST=host.docker.internal \
  -p 3001:3000 \
  polymarket-bot \
  python bot.py --test-mode

# 实盘模式（真金白银 ⚠️）
docker run -d \
  --name polymarket-bot-live \
  --restart unless-stopped \
  --env-file .env \
  -e REDIS_HOST=host.docker.internal \
  -p 3000:3000 \
  -p 8000:8000 \
  -v bot-data:/app/data \
  -v bot-logs:/app/logs \
  polymarket-bot \
  python bot.py --live
```

### 4.3 查看日志

```bash
docker logs -f polymarket-bot
```

### 4.4 停止并删除

```bash
docker stop polymarket-bot
docker rm polymarket-bot
```

---

## 5. 多容器生产部署

### 5.1 标准部署（2 个容器）

`docker-compose.yml` 定义了两个服务：

```
┌──────────────────────────────────────────────────┐
│                    bot-net                        │
│                                                    │
│  ┌──────────────────────┐  ┌────────────────────┐  │
│  │   polymarket-bot     │  │   polymarket-redis  │  │
│  │                      │  │                      │  │
│  │  python bot.py       │◄─┤  redis-server        │  │
│  │                      │  │                      │  │
│  │  Ports:              │  │  Port: 6379          │  │
│  │   :3000 → Dashboard  │  │  (仅内部网络)        │  │
│  │   :8000 → Metrics    │  │                      │  │
│  └──────────────────────┘  └────────────────────┘  │
└──────────────────────────────────────────────────┘
```

### 5.2 启动完整部署

```bash
# 第一次构建并启动
docker compose up -d --build

# 查看所有服务状态
docker compose ps

# 查看实时日志
docker compose logs -f

# 只查看 bot 日志
docker compose logs -f bot

# 只查看 Redis 日志
docker compose logs -f redis
```

### 5.3 指定运行模式

```bash
# 默认模拟模式（已在 docker-compose.yml 中设定）
docker compose up -d

# 测试模式（覆盖默认 command）
docker compose run --rm bot python bot.py --test-mode

# 实盘模式
# 方法1：修改 docker-compose.yml 中的 command
# 方法2：停止并重新运行
docker compose down
docker compose run --rm bot python bot.py --live
```

### 5.4 重启策略

两个服务都设置了 `restart: unless-stopped`，意味着：
- 容器崩溃时自动重启
- 服务器重启后自动启动
- 只有 `docker compose down` 或 `docker compose stop` 才会停止

### 5.5 网络说明

- Redis 端口 `6379` **没有映射到宿主机**，只能被 bot 容器通过内部 DNS 名称 `redis` 访问
- 这比在 `.env` 中写 `REDIS_HOST=localhost` 更安全

---

## 6. 配置详解

### 6.1 环境变量注入方式

bot 容器从三个来源获取环境变量：

```
1. docker-compose.yml 的 environment: 块（硬编码默认值）
2. docker-compose.yml 的 env_file: .env（从 .env 文件读取）
3. entrypoint.sh 中的 ${VAR:-default} 语法（脚本级默认值）
```

优先级：`environment:` > `env_file:` > Dockerfile 默认值

### 6.2 Redis 连接配置

在 docker-compose 环境下，**不需要修改 `.env` 中的 Redis 配置**。

`docker-compose.yml` 已自动注入正确的值：
```yaml
environment:
  - REDIS_HOST=redis          # Docker 内部 DNS，指向 Redis 容器
  - REDIS_PORT=6379
  - REDIS_DB=2
```

如果你**单独运行** `docker run`，需要将 `REDIS_HOST` 设置为外部 Redis 地址：
```bash
# 宿主机有 Redis
docker run ... -e REDIS_HOST=host.docker.internal ...

# 或直接使用宿主机 IP
docker run ... -e REDIS_HOST=192.168.1.100 ...
```

### 6.3 持久化数据卷

```yaml
volumes:
  bot-data:/app/data    # 交易数据库 (trades.db)
  bot-logs:/app/logs    # 日志文件
  redis-data:/data      # Redis 持久化
```

数据存放在 Docker 管理的卷中：

```bash
# 查看数据卷列表
docker volume ls

# 查看数据卷详情
docker volume inspect polymarket-btc-15m-bot_bot-data

# 备份数据卷
docker run --rm -v polymarket-btc-15m-bot_bot-data:/source \
  -v $(pwd)/backup:/backup alpine \
  tar czf /backup/bot-data-$(date +%Y%m%d).tar.gz -C /source .

# 恢复数据卷
docker run --rm -v polymarket-btc-15m-bot_bot-data:/target \
  -v $(pwd)/backup:/backup alpine \
  tar xzf /backup/bot-data-20260618.tar.gz -C /target
```

### 6.4 Grafana 配置（可选）

如果需要在 Docker 中运行 Grafana：

```yaml
# 在 docker-compose.yml 中添加：
grafana:
  image: grafana/grafana:latest
  container_name: polymarket-grafana
  restart: unless-stopped
  ports:
    - "3001:3000"    # Grafana 用 3001 避免与 Dashboard 冲突
  environment:
    - GF_SECURITY_ADMIN_PASSWORD=admin
  volumes:
    - grafana-data:/var/lib/grafana
    - ./grafana/dashboard.json:/etc/grafana/provisioning/dashboards/dashboard.json

volumes:
  grafana-data:
```

启动后访问 `http://服务器IP:3001`（admin/admin），
添加 Prometheus 数据源 `http://bot:8000`。

---

## 7. 运行模式

### 7.1 模式切换

| 模式 | docker-compose 命令 | docker run 命令 |
|------|---------------------|-----------------|
| **模拟模式**（默认） | `docker compose up -d` | `docker run ... polymarket-bot` |
| **测试模式** | `docker compose run --rm bot python bot.py --test-mode` | `docker run ... polymarket-bot python bot.py --test-mode` |
| **实盘模式** | 修改 command 或 `docker compose run --rm bot python bot.py --live` | `docker run ... polymarket-bot python bot.py --live` |
| **禁用监控** | `docker compose run --rm bot python bot.py --no-grafana` | `docker run ... polymarket-bot python bot.py --no-grafana` |

### 7.2 热切换（通过 Redis）

如果使用 docker-compose 部署，可以在不重启容器的情况下切换模式：

```bash
# 进入 Redis 容器
docker compose exec redis redis-cli

# 在 Redis CLI 中执行：
# 切换到模拟模式
SET btc_trading:simulation_mode 1

# 切换到实盘模式
SET btc_trading:simulation_mode 0

# 查看当前模式
GET btc_trading:simulation_mode
```

或在宿主机上（如果 Redis 端口已暴露）：
```bash
redis-cli -h 服务器IP -p 6379 SET btc_trading:simulation_mode 1
```

### 7.3 运行多条命令

```bash
# 启动后进入容器执行临时命令
docker compose exec bot python view_trades.py --stats
docker compose exec bot python view_paper_trades.py
docker compose exec bot /bin/sh

# 一次性的命令（不干扰正在运行的容器）
docker compose run --rm bot python view_trades.py --all
```

---

## 8. 监控与访问

### 8.1 端口映射总览

| 端口 | 服务 | 说明 | 安全建议 |
|------|------|------|----------|
| `3000` | Web Dashboard | 实时交易面板 + REST API | 建议绑 `127.0.0.1:3000` 或加反向代理认证 |
| `8000` | Prometheus 指标 | 供 Grafana 拉取 | 建议绑 `127.0.0.1:8000` |
| `6379` | Redis | 未映射到宿主机（安全） | 仅内部网络访问 |

### 8.2 安全绑定到 localhost

编辑 `docker-compose.yml`，将端口改为只绑定本地：

```yaml
ports:
  - "127.0.0.1:3000:3000"    # 只能本机访问
  - "127.0.0.1:8000:8000"    # 只能本机访问
```

然后通过 Nginx 反向代理对外暴露：

```nginx
# /etc/nginx/sites-available/bot-dashboard
server {
    listen 443 ssl;
    server_name bot.yourdomain.com;

    ssl_certificate /etc/letsencrypt/live/bot.yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/bot.yourdomain.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;

        # 添加基础认证
        auth_basic "Bot Dashboard";
        auth_basic_user_file /etc/nginx/.htpasswd;
    }
}
```

### 8.3 健康检查

```bash
# Dashboard API
curl http://localhost:3000/api/status

# Prometheus 指标
curl http://localhost:8000/metrics

# 容器健康状态
docker compose ps

# 容器资源使用
docker stats polymarket-bot
```

---

## 9. 维护管理

### 9.1 更新 bot

```bash
# 1. 拉取最新代码
git pull

# 2. 重新构建并启动（--build 强制重新构建）
docker compose up -d --build

# 3. 查看更新日志
docker compose logs -f bot
```

### 9.2 查看日志

```bash
# 实时跟踪
docker compose logs -f bot

# 最近 100 行
docker compose logs --tail=100 bot

# 某个时间点之后
docker compose logs --since="2026-06-18T10:00:00" bot

# 保存到文件
docker compose logs bot > bot-logs-$(date +%Y%m%d).txt
```

### 9.3 数据备份

```bash
# 备份交易数据
docker run --rm \
  -v polymarket-btc-15m-bot_bot-data:/data \
  -v $(pwd)/backup:/backup \
  alpine tar czf /backup/trades-$(date +%Y%m%d-%H%M%S).tar.gz -C /data .

# 备份 Redis 数据
docker run --rm \
  -v polymarket-btc-15m-bot_redis-data:/data \
  -v $(pwd)/backup:/backup \
  alpine tar czf /backup/redis-$(date +%Y%m%d-%H%M%S).tar.gz -C /data .
```

### 9.4 清理

```bash
# 查看磁盘占用
docker system df

# 清理未使用的镜像、容器、卷
docker system prune -f

# 清理所有未使用的卷（⚠️ 会删除未挂载的数据）
docker volume prune -f

# 完全清理（包括构建缓存）
docker system prune -a -f
```

### 9.5 重置交易数据

```bash
# 方法1：通过 bot 命令清除（推荐）
docker compose exec bot rm -f /app/data/trades.db

# 方法2：重建数据卷（会删除所有数据）
docker compose down -v
docker compose up -d
```

---

## 10. 常见问题排查

### 10.1 构建失败

**Q: `pip install nautilus_trader` 编译失败**

```text
error: failed to run custom build command for 'nautilus_trader'
```

A: 多阶段构建已处理此问题。如果还是失败：
- 检查网络：确保能访问 crates.io 和 PyPI
- 增加 Docker 构建内存限制：
  ```bash
  # 不要用 --memory 限制构建容器，nautilus_trader 需要 ~4GB
  docker build -t polymarket-bot . --memory=4g
  ```
- 使用代理（国内服务器）：
  ```bash
  docker build -t polymarket-bot . \
    --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
  ```

**Q: `ERROR: failed to solve: process "/bin/sh -c pip install ..."`**

A: 通常是网络超时。重新构建即可：
```bash
# 使用缓存重新构建
docker build -t polymarket-bot . --no-cache
```

### 10.2 启动失败

**Q: 容器启动后立即退出**

```bash
# 查看退出原因
docker compose logs bot
```

常见原因：
```
Error: Environment variable 'POLYMARKET_FUNDER' not set
```
→ `.env` 文件中缺少 `POLYMARKET_FUNDER`。

```
Error: Redis connection failed
```
→ Redis 容器还没就绪，但 entrypoint.sh 会自动等待最多 30 秒。

**Q: Redis 健康检查失败**

```bash
# 单独检查 Redis
docker compose exec redis redis-cli ping
# 应输出 PONG

# 如果 Redis 有问题，重启它
docker compose restart redis
```

### 10.3 运行时问题

**Q: Dashboard 显示 "Connection refused"**

A: Dashboard 在 bot 内部启动，需要 bot 完全就绪后才能访问。
等 10-15 秒刷新即可。或者检查：
```bash
docker compose logs bot | grep "dashboard"
# 应看到: Trading dashboard started at http://0.0.0.0:3000
```

**Q: 没有交易发生**

A: 正常行为。Bot 每 15 分钟一个周期，只在价格偏离 0.60 以上或 0.40 以下时交易。
检查策略状态：
```bash
curl http://localhost:3000/api/status
```

**Q: 如何确认 bot 在正常工作？**

A: 检查以下几点：
1. 容器运行中：`docker compose ps` → `Up` 状态
2. 日志有输出：`docker compose logs --tail=20 bot`
3. Dashboard 可访问：`curl http://localhost:3000/api/status`
4. 有交易记录：`docker compose exec bot python view_trades.py --stats`

### 10.4 性能问题

**Q: CPU 使用率高**

```bash
docker stats polymarket-bot
```

正常情况：空闲时 < 5%，交易窗口时短暂升至 20-30%。

如果持续高负载：
- 检查是否开启了过多的调试日志
- 检查网络连接稳定性（WebSocket 重连会消耗 CPU）
- 考虑限制 CPU：
  ```yaml
  # docker-compose.yml
  services:
    bot:
      deploy:
        resources:
          limits:
            cpus: '1.0'
            memory: 2G
  ```

**Q: 内存使用持续增长**

A: bot 每 90 分钟自动重启一次（内置机制），防止内存泄漏。
```logs
AUTO-RESTART TIME - Loading fresh filters
```
这是正常行为。`restart: unless-stopped` 确保重启后自动恢复。

---

## 11. 命令速查表

### 构建与启动

| 命令 | 说明 |
|------|------|
| `docker compose up -d` | 后台启动（模拟模式） |
| `docker compose up -d --build` | 重新构建并启动 |
| `docker compose down` | 停止（保留数据） |
| `docker compose down -v` | 停止并清空数据 ⚠️ |
| `docker compose restart bot` | 重启 bot 容器 |
| `docker compose restart redis` | 重启 Redis |
| `docker compose ps` | 查看运行状态 |

### 查看数据

| 命令 | 说明 |
|------|------|
| `docker compose exec bot python view_trades.py --stats` | 交易统计 |
| `docker compose exec bot python view_trades.py --all` | 所有交易 |
| `docker compose exec bot python view_paper_trades.py` | JSON 交易记录 |

### 日志

| 命令 | 说明 |
|------|------|
| `docker compose logs -f bot` | 实时跟踪 bot 日志 |
| `docker compose logs -f redis` | 实时跟踪 Redis 日志 |
| `docker compose logs --tail=100 bot` | 最近 100 行 |
| `docker compose logs --since=10m bot` | 最近 10 分钟 |

### 监控

| 命令/地址 | 说明 |
|-----------|------|
| `http://服务器IP:3000` | Web Dashboard |
| `http://服务器IP:8000/metrics` | Prometheus 指标 |
| `curl http://localhost:3000/api/stats` | 统计 API |
| `docker stats polymarket-bot` | 容器资源监控 |

### 维护

| 命令 | 说明 |
|------|------|
| `docker compose exec bot python redis_control.py status` | 查看当前模式 |
| `docker compose exec bot /bin/sh` | 进入容器 Shell |
| `docker system df` | 查看磁盘占用 |
| `docker system prune -f` | 清理未使用的资源 |
| `docker compose logs bot > bot.log` | 导出日志到文件 |

### 数据备份

| 命令 | 说明 |
|------|------|
| `docker run --rm -v polymarket-btc-15m-bot_bot-data:/data -v $(pwd)/backup:/backup alpine tar czf /backup/bot-data.tar.gz -C /data .` | 备份交易数据 |
| `docker run --rm -v polymarket-btc-15m-bot_redis-data:/data -v $(pwd)/backup:/backup alpine tar czf /backup/redis-data.tar.gz -C /data .` | 备份 Redis 数据 |

---

## 附录 A：生产环境检查清单

部署到生产环境前，请逐项确认：

- [ ] 已使用 `docker compose down -v` 清空测试数据
- [ ] `.env` 文件权限设为 600：`chmod 600 .env`
- [ ] Dashboard 端口已绑定到 `127.0.0.1` 或使用 Nginx 反向代理 + 认证
- [ ] 已配置 `restart: unless-stopped`（默认已配置）
- [ ] 已设置日志轮转（Docker 默认 json-file 驱动，建议限制大小）
  ```yaml
  # docker-compose.yml 添加：
  logging:
    driver: "json-file"
    options:
      max-size: "10m"
      max-file: "3"
  ```
- [ ] 已测试模拟模式至少运行数小时
- [ ] 已备份私钥（离线存储，不要放在服务器上）
- [ ] 已配置系统防火墙（UFW）开放必要端口
  ```bash
  sudo ufw allow ssh
  sudo ufw allow 443/tcp   # 如果使用 HTTPS
  sudo ufw enable
  ```

## 附录 B：系统架构图

```
┌─────────────────────────────────────────────────────────┐
│                     宿主机 (Ubuntu)                        │
│                                                           │
│  ┌─────────────────────────────────────────────────────┐  │
│  │              Docker 网络 (bot-net)                    │  │
│  │                                                       │  │
│  │  ┌──────────────────┐    ┌──────────────────┐       │  │
│  │  │  polymarket-bot  │    │ polymarket-redis │       │  │
│  │  │                  │    │                  │       │  │
│  │  │  ┌────────────┐  │    │  ┌────────────┐  │       │  │
│  │  │  │ 策略大脑    │  │    │  │ 模式状态   │  │       │  │
│  │  │  │ 6个信号处理器│──┼────┼─►│ sim/live   │  │       │  │
│  │  │  │ 融合引擎    │  │    │  └────────────┘  │       │  │
│  │  │  └────────────┘  │    └──────────────────┘       │  │
│  │  │  ┌────────────┐  │                                │  │
│  │  │  │ 执行引擎    │  │    ┌──────────────────┐       │  │
│  │  │  │ 风控引擎    │  │    │ (可选) Grafana    │       │  │
│  │  │  └────────────┘  │    │ port 3001         │       │  │
│  │  │  ┌────────────┐  │    └──────────────────┘       │  │
│  │  │  │ 监控层      │  │                                │  │
│  │  │  │ port 3000   │  │                                │  │
│  │  │  │ port 8000   │  │                                │  │
│  │  │  └────────────┘  │                                │  │
│  │  └──────────────────┘                                │  │
│  │                                                       │  │
│  │  数据卷: bot-data  │  bot-logs  │  redis-data         │  │
│  └─────────────────────────────────────────────────────┘  │
│                                                           │
│  外部网络 ─── Polymarket(CLOB) ─── Coinbase ─── Binance   │
│                                                           │
└─────────────────────────────────────────────────────────┘
```

---

*如有问题，请提交 GitHub Issue 或联系项目维护者。*
