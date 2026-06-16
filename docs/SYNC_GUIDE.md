# 双机协同维护操作清单（公司机 ⇄ 家用机）

> 目标：用 Git 同步**代码**，用外部通道（U盘 或 Syncthing）同步**运行期数据**。不使用云存储、不远程登录。
> 核心纪律：**任一时刻只认一台机器为“当前活跃机”**，因为 `products.db` 是二进制 SQLite，无法合并。

---

## 0. 一句话总览

| 内容 | 同步方式 | 频率 |
|------|----------|------|
| 代码 / 文档 / 配置模板 / Scrapling 源码 / `data/products.json` | **Git** push/pull | 每次改动 |
| `data/products.db`（含 sidecar）、`data/cache/` | **U盘 或 Syncthing**（见下） | 每次切换机器 |
| `.env`、`.streamlit/secrets.toml`、`.sync-config` | 手动复制一次 | 仅初始化 / 改密钥时 |
| `.venv/`、`__pycache__/`、浏览器二进制 | 每台机器各自重建 | 不同步 |
| Python 3.12 / Playwright / Git / VS Code | 每台机器各装一次 | 仅初始化 |

---

## 一、首次设置（两台机器各做一次）

### 1.1 环境与软件（一次性）

- [ ] 安装 **Python 3.12**（见 [runtime.txt](runtime.txt)）
- [ ] 安装 **Git**，并配置与本仓库一致的提交身份：
  ```bash
  git config --global user.name  "hiiio9898"
  git config --global user.email "yuhuichan98@163.com"
  ```
- [ ] 配好 GitHub SSH key（两台各自的 key，添加到 GitHub 账号）
- [ ] 安装 **Playwright / Chromium** 浏览器内核（见 [packages.txt](packages.txt)）：
  ```bash
  # Scrapling 依赖，装一次即可
  python -m patchright install chromium
  # （或）python -m playwright install chromium
  ```
- [ ] 安装 **VS Code**（+ 扩展）、**Claude Code** CLI（+ 登录）
- [ ] （可选）安装 **Syncthing**（仅“方案 B”需要）

### 1.2 拉取代码 + 重建虚拟环境

```bash
git clone git@github.com:hiiio9898/global-product-scout.git
cd global-product-scout

python -m venv .venv
source .venv/Scripts/activate     # Git Bash 激活（Windows）
pip install -r requirements.txt
pip install -e Scrapling-main     # 本地可编辑安装 Scrapling
```

### 1.3 填写本机配置（手动，一次性）

- [ ] 复制并填写密钥：
  ```bash
  cp .env.example .env
  # 把 .env 里的 your-*-key-here 换成真实 key；对照 .env.example 补齐新增变量
  cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # 若无 example，从另一台机器拷过来
  ```
- [ ] 复制并填写同步目录配置：
  ```bash
  cp .sync-config.example .sync-config
  # 编辑 .sync-config，把 SYNC_DIR 指向你的 U盘 或 Syncthing 文件夹
  ```

> `.env`、`secrets.toml`、`.sync-config` 都在 `.gitignore` 里，**不会提交**，两台机器各填一份。

---

## 二、选一个数据同步通道

### 方案 A — U盘 + 脚本（**离线首选**，公司/家不在同一网络时唯一可行）

- 把 U盘 根目录建一个文件夹，例如 `E:\GPS-Sync`
- 两台机器的 `.sync-config` 里 `SYNC_DIR` 都指向它（Git Bash 路径 `/e/GPS-Sync`）
- 切换机器时插上 U盘，跑 `pull` / `push`（见第四节）
- **优点**：完全离线，零网络依赖
- **缺点**：要记得插拔、拷贝

### 方案 B — Syncthing（两台机器**能联网**时最省心）

> ⚠️ 注意：Syncthing 在不同网络（公司⇄家）间默认走**全球中继**（经 Syncthing 官方服务器转发，但数据端到端加密）。若你严格要求“完全不碰外网”，请用方案 A。
> 若两台机器在同一局域网，Syncthing 走**纯局域网直连**，不经过任何外部服务器。

详细配置见 **第五节**。

> 建议：**主用方案 A（U盘）保底**，Syncthing 作为同局域网时的省力补充。两者共享同一个 `sync-data.sh`。

---

## 三、`sync-data.sh` 速查

> 脚本位置：[scripts/sync-data.sh](scripts/sync-data.sh)。运行前先填好 `.sync-config`。

| 命令 | 作用 | 何时用 |
|------|------|--------|
| `bash scripts/sync-data.sh status` | 对比两边新旧、检查是否占用 | 切机器第一步，决定 pull 还是 push |
| `bash scripts/sync-data.sh pull`   | 同步目录 → 项目 | **早晨**切到本机，开干前 |
| `bash scripts/sync-data.sh push`   | 项目 → 同步目录 | **收工**离开本机前 |
| `bash scripts/sync-data.sh backup` | 单独备份本地 DB | 做危险操作（迁移/删数据）前 |

内置保护：
- 覆盖前自动把**被覆盖方**存到 `backups/`（带时间戳）
- 检测到 DB 占用（存在 `-journal`）会拦下，需 `FORCE=1` 才放行
- `pull` 时若发现**本地比同步目录还新**，会要求确认（防误覆盖较新数据）

---

## 四、每日操作清单（打印贴屏用）

### 🌅 早晨 · 切到某一台机器开干

- [ ] **拉代码**：`git pull`
- [ ] 插上 U盘（方案 A）/ 确认 Syncthing 已连（方案 B）
- [ ] **看状态**：`bash scripts/sync-data.sh status`
  - 提示“同步目录更新” → 继续 pull；提示“本地更新” → 说明上次没 push 干净，先确认数据归属
- [ ] **拉数据**：`bash scripts/sync-data.sh pull`
  - （含 `products.db` + `cache/`；若有 `-journal` 先关掉应用）
- [ ] 启动应用：`streamlit run app.py`
- [ ] 干活。提交代码：`git add . && git commit -m "..." && git push`

### 🌙 收工 · 离开这台机器前

- [ ] **关闭应用**（`Ctrl+C` 停掉 streamlit，确保 DB 正常落盘、无 `-journal`）
- [ ] **推数据**：`bash scripts/sync-data.sh push`
  - 拔 U盘 / 等 Syncthing 同步完成（图标静止）
- [ ] **推代码**：`git push`
- [ ] （可选）`bash scripts/sync-data.sh status` 复核“本地/同步目录”时间一致

> 💡 记忆口诀：**开机 pull、关机 push，先停应用再搬数据**。

---

## 五、Syncthing 详细配置（方案 B）

### 5.1 安装并共享一个文件夹

1. 两台机器各安装 [Syncthing](https://syncthing.net/)，启动后访问 `http://127.0.0.1:8384`
2. 在 **机器 A**：“Add Folder” → 路径填 `项目/data`（直接共享项目的 data 目录）→ 记下 Folder ID
3. 在 **机器 A**：“Add Device” → 填机器 B 的 Device ID（在 B 的界面上看）
4. 在 **机器 B**：弹出共享请求 → 接受设备 → 接受文件夹，路径也填**本机的** `项目/data`
5. 文件夹类型两台都设为 **Send & Receive**

### 5.2 放置忽略规则（关键）

把 [scripts/stignore](scripts/stignore) 复制到项目的 `data/` 目录，重命名为 `.stignore`：

```bash
cp scripts/stignore data/.stignore
```

作用：让 Syncthing **只同步 `products.db` / `cache/` / `adaptive_elements.db`**，排除：
- `products.json`（Git 管，避免两边打架）
- `backups/`、`-journal`、`-shm`（本地/临时物）

### 5.3 注意点

- Syncthing 共享的是 `data/` 本身 → **数据是实时自动同步的，日常不需要跑 `sync-data.sh`**（但 push/pull/backup 仍可用于 U盘场景和备份）
- 若两台**同时都在写** DB，Syncthing 会生成 `products.sync-conflict-YYYYMMDD-*.db`，**不会静默丢数据**。出现冲突文件时，按第六节处理
- 想走**纯局域网**：在 Settings → Connections 关掉“Global Discovery”和“Relaying”，仅保留 LAN

---

## 六、故障与冲突处理

### 6.1 “本地比同步目录还新” / pull 被拦
说明这台机器上有更新的数据没推出去。先确认这份本地数据是不是你想要的：
- 是 → 先 `push` 把它送出去，再到另一台 `pull`
- 不是（本地是废弃的）→ `FORCE=1 bash scripts/sync-data.sh pull` 强制覆盖（会自动备份本地）

### 6.2 Syncthing 冲突文件 `*.sync-conflict-*.db`
两台同时改了 DB。挑一个保留：
1. 用 `sqlite3` 或 DB 工具打开两个文件，对比记录数 / 最新数据
2. 保留正确那份为 `products.db`，删除另一个和 `products.db` 的旧临时文件
3. 等 Syncthing 同步静止

> 预防：遵守“单机活跃”纪律，不两台同时开应用写数据。

### 6.3 数据库看起来损坏 / 启动报错
从 `data/backups/` 里找最近一次时间戳备份还原：
```bash
cp data/backups/products.db.<时间戳> data/products.db
```

### 6.4 忘了 push 就在另一台改了
Git 代码：可 `git stash` / 回滚解决；DB：只能靠 `data/backups/` 或 Syncthing 冲突文件抢救。**所以收工 push 是最高优先级**。

---

## 七、安全提醒

- `.env`、`.streamlit/secrets.toml` 含**真实 API Key**，已确认在 `.gitignore` 中，**切勿** `git add -f` 提交
- 若曾误提交过密钥：先从 GitHub 历史删除（`git filter-repo` / BFG），再到各供应商后台**轮换 key**
- U盘建议加密（BitLocker），丢失时不致泄露密钥与业务数据
