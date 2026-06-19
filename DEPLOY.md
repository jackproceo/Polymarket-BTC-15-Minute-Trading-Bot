# Polymarket BTC 15-Minute Trading Bot — 部署文档

## 目录

- [一、上传到 GitHub](#一上传到-github)
- [二、服务器 Docker 部署](#二服务器-docker-部署)
- [三、日常运维](#三日常运维)
- [四、常见问题](#四常见问题)

---

## 一、上传到 GitHub

### 1.1 前提条件

- 已注册 [GitHub](https://github.com) 账号
- 本地已安装 Git（[下载](https://git-scm.com/downloads)）

### 1.2 在 GitHub 上创建仓库

1. 登录 GitHub，点击右上角 `+` → **New repository**
2. 填写仓库名（例如 `polymarket-btc-bot`）
3. **务必选 Private**（仓库包含交易策略逻辑，不应公开）
4. 不要勾选 "Add a README"、"Add .gitignore"（项目已有）
5. 点击 **Create repository**

### 1.3 推送本地代码

```bash
# 进入项目目录
cd E:\trade\polymarket\Polymarket-BTC-15-Minute-Trading-Bot

# 初始化 Git 仓库（如尚未初始化）
git init

# 添加所有文件（.gitignore 会自动排除敏感文件）
git add .

# 检查哪些文件会被提交（确认 .env 不在列表中）
git status --short

# 首次提交
git commit -m "Initial commit: Polymarket BTC 15-min trading bot"

# 关联远程仓库（替换 YOUR_USERNAME/REPO_NAME）
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO_NAME.git

# 推送到 GitHub
git push -u origin main
```

> **注意**：项目的 `.gitignore` 已配置排除 `.env`、`venv/`、`logs/`、`__pycache__/`、数据库文件等敏感内容。推送前请运行 `git status` 确认没有意外包含私密信息。

### 1.4 后续更新

```bash
git add .
git commit -m "描述本次变更"
git push
```

---

## 二、服务器 Docker 部署

### 2.1 服务器要求

| 项目       | 最低配置     | 推荐配置     |
| ---------- | ------------ | ------------ |
| 操作系统   | Ubuntu 22.04 | Ubuntu 24.04 |
| CPU        | 2 核         | 4 核         |
| 内存       | 4 GB         | 8 GB         |
| 磁盘       | 20 GB        | 40 GB        |
| Docker     | 24+          | 27+          |
| Docker Compose | v2       | v2.30+       |

### 2.2 安装 Docker

```bash
# 更新包索引
sudo apt update && sudo apt upgrade -y

# 安装 Docker
curl -fsSL https://get.docker.com | sudo sh

# 将当前用户加入 docker 组（避免每次 sudo）
sudo usermod -aG docker $USER

# 重新登录使组生效
exit
# 重新 SSH 登录后验证
docker --version
docker compose version
```

### 2.3 在 /opt 下部署项目

```bash
# 创建项目目录
sudo mkdir -p /opt/polymarket-bot

# 克隆代码（替换 YOUR_USERNAME/REPO_NAME）
git clone https://github.com/YOUR_USERNAME/YOUR_REPO_NAME.git /opt/polymarket-bot

# 进入项目目录
cd /opt/polymarket-bot

# 创建数据目录持久化挂载点
sudo mkdir -p /opt/polymarket-bot/data /opt/polymarket-bot/logs
```

### 2.4 配置环境变量

```bash
# 从模板创建 .env 文件
cp .env.example .env

# 编辑 .env 填入真实凭证
nano .env
```

必须配置的字段：

```ini
# Polymarket API Credentials（必填）
POLYMARKET_PK=your_private_key_here
POLYMARKET_API_KEY=your_api_key_here
POLYMARKET_API_SECRET=your_api_secret_here
POLYMARKET_PASSPHRASE=your_passphrase_here
POLYMARKET_FUNDER=your_polygon_wallet_address_here
```

> **安全提醒**：`.env` 包含私钥，服务器上应确保只有你自己能读取：
> ```bash
> chmod 600 .env
> ```

### 2.5 构建并启动

```bash
# 构建镜像（首次约 10-20 分钟，主要编译 nautilus_trader 原生扩展）
docker compose build

# 后台启动（默认模拟交易模式）
docker compose up -d

# 查看启动日志
docker compose logs -f bot

# 确认服务正常运行
docker compose ps
```

### 2.6 运行模式

**模拟交易（默认）**：
```bash
docker compose up -d
```

**测试模式（每分钟交易一次，用于快速验证）**：
```bash
docker compose run --rm bot --test-mode
```
或覆盖已有容器的命令：
```bash
docker compose stop bot && docker compose run --rm --service-ports bot python bot.py --test-mode
```

**实盘交易（真金白银）**：
```bash
# 先确保 .env 中所有凭证配置正确
docker compose stop bot
docker compose run --rm --service-ports bot --live
```

### 2.7 端口说明

| 端口 | 用途                  | 建议暴露范围       |
| ---- | --------------------- | ------------------ |
| 3000 | Web Dashboard（监控面板） | 仅内网或 Nginx 反代 |
| 8000 | Prometheus 指标        | 仅内网             |
| 6379 | Redis（内部通信）       | 仅容器内网（默认）   |

如需通过域名访问 Dashboard，建议用 Nginx 反代：

```nginx
# /etc/nginx/sites-available/polymarket
server {
    listen 80;
    server_name bot.yourdomain.com;

    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

> **安全建议**：Dashboard 没有身份验证，请勿直接暴露到公网。使用 Nginx 基本认证或 Cloudflare Tunnel 保护。

---

## 三、日常运维

### 3.1 查看状态

```bash
# 容器状态
docker compose ps

# 实时日志
docker compose logs -f --tail=100 bot

# 资源占用
docker stats polymarket-bot

# 查看交易记录（容器内）
docker compose exec bot python view_paper_trades.py
```

### 3.2 重启

```bash
docker compose restart bot
```

### 3.3 更新代码

```bash
cd /opt/polymarket-bot

# 拉取最新代码
git pull

# 重新构建并启动
docker compose build bot
docker compose up -d
```

### 3.4 备份数据

```bash
# 备份交易数据
tar czf backup-$(date +%Y%m%d).tar.gz \
  /opt/polymarket-bot/data \
  /opt/polymarket-bot/logs

# 下载到本地
scp user@your-server:/opt/polymarket-bot/backup-*.tar.gz ./
```

### 3.5 停止与清理

```bash
# 停止服务（保留数据）
docker compose down

# 完全清理（删除所有数据卷）
docker compose down -v
```

---

## 四、常见问题

### Q: 构建时提示 Rust 编译错误？

A: 确保服务器有足够内存（至少 4GB）。如内存不足，可临时增加 swap：

```bash
sudo fallocate -l 4G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
```

### Q: 容器启动后马上退出？

A: 查看日志定位原因：

```bash
docker compose logs bot
```

常见原因：
- `.env` 文件缺失或格式错误
- Redis 连接超时（healthcheck 失败加重启间隔）
- Polymarket API 凭证无效

### Q: 如何切换模拟/实盘模式而不重启？

A: 通过 Redis 动态切换（需要容器正常运行且 Redis 正常）：

```bash
docker compose exec bot python redis_control.py sim    # 切到模拟
docker compose exec bot python redis_control.py live   # 切到实盘
```

### Q: 磁盘空间会不断增加吗？

A: 日志默认保留 30 天，会自动轮转。数据文件和 SQLite 数据库体积很小（预计 <100MB/月）。建议每月检查：

```bash
du -sh /opt/polymarket-bot/data /opt/polymarket-bot/logs
```

### Q: `.env` 文件包含私钥，推送到 GitHub 安全吗？

A: 安全。`.gitignore` 已明确排除 `.env` 文件，`git add .` 不会包含它。但请在提交前用 `git status` 再次确认。
