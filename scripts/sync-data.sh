#!/usr/bin/env bash
# =============================================================================
# sync-data.sh — Global Product Scout 本地数据同步工具
#
# 设计：代码用 Git 同步；运行期数据（products.db / cache）用本脚本在
#       「项目目录」与「同步目录（U盘 或 Syncthing 共享文件夹）」之间搬运。
#
# 用法:
#   bash scripts/sync-data.sh status   # 查看两边新旧 / 大小 / 是否占用
#   bash scripts/sync-data.sh pull     # 同步目录 → 项目（早晨切到本机时用）
#   bash scripts/sync-data.sh push     # 项目 → 同步目录（收工离开机器前用）
#   bash scripts/sync-data.sh backup   # 单独把本地 DB 备份一份
#
# 覆盖保护: 任何覆盖前都会先把被覆盖方存到 .../backups/（带时间戳）。
# 可用 FORCE=1 跳过所有确认：
#   FORCE=1 bash scripts/sync-data.sh push
#
# 配置: 把 .sync-config.example 复制为 .sync-config 并填好 SYNC_DIR；
#       或直接  export SYNC_DIR=/your/path  后运行。
# =============================================================================
set -u

# 无参 / -h / help：先打印用法即退出，不要求 SYNC_DIR
case "${1:-}" in
  -h|--help|help|"") sed -n '2,16p' "$0"; exit 0 ;;
esac

# ---------- 加载配置 ----------
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_DIR="$( cd "$SCRIPT_DIR/.." && pwd )"
CONFIG_FILE="$PROJECT_DIR/.sync-config"
[ -f "$CONFIG_FILE" ] && source "$CONFIG_FILE"

: "${SYNC_CACHE:=yes}"   # yes/no：是否同步 data/cache
# 同步文件夹名（跨机器用盘符不同但文件夹名一致来识别）
: "${SYNC_FOLDER_NAME:=GPS-Sync}"

# ---------- 自动探测同步目录（解决U盘盘符不一致：家E盘/公司H盘） ----------
# SYNC_DIR=auto 或未设置时，扫描所有盘符找 SYNC_FOLDER_NAME 文件夹
if [ -z "${SYNC_DIR:-}" ] || [ "${SYNC_DIR:-}" = "auto" ]; then
  DETECTED=""
  # 扫描 C-Z 所有盘符（Git Bash 风格 /c /d ... /z）
  for drive in {c..z}; do
    candidate="/$drive/$SYNC_FOLDER_NAME"
    if [ -d "$candidate" ]; then
      DETECTED="$candidate"
      break
    fi
  done
  if [ -n "$DETECTED" ]; then
    SYNC_DIR="$DETECTED"
    export SYNC_DIR
  else
    red "未找到同步文件夹 $SYNC_FOLDER_NAME（已扫描所有盘符）"
    yellow "请检查U盘是否插入，或手动设置 SYNC_DIR"
    exit 1
  fi
fi

DATA_DIR="$PROJECT_DIR/data"
REMOTE_DIR="$SYNC_DIR"   # 同步目录直接当作远端 data 根
TS="$(date +%Y%m%d-%H%M%S)"

# ---------- 待同步文件清单（主库 + 可能的 sidecar / 自适应库） ----------
DB_FILES=("products.db")
for s in products.db-journal products.db-wal products.db-shm adaptive_elements.db; do
  [ -f "$DATA_DIR/$s" ] && DB_FILES+=("$s")
done

# ---------- 工具函数 ----------
red()    { printf "\033[31m%s\033[0m\n" "$*"; }
green()  { printf "\033[32m%s\033[0m\n" "$*"; }
yellow() { printf "\033[33m%s\033[0m\n" "$*"; }
bold()   { printf "\033[1m%s\033[0m\n" "$*"; }

mtime()   { [ -f "$1" ] && stat -c %Y "$1" 2>/dev/null || echo 0; }
fmt_date(){ local e="$1"; [ "$e" = 0 ] && { echo "-"; return; }; date -d @"$e" '+%Y-%m-%d %H:%M' 2>/dev/null || echo "@$e"; }

# 有 journal/wal 文件 = 有未完成事务（或上次崩溃残留），此时复制可能不一致
db_busy() {
  [ -f "$DATA_DIR/products.db-journal" ] && return 0
  [ -f "$DATA_DIR/products.db-wal" ] && return 0
  return 1
}
ensure_dirs(){ mkdir -p "$DATA_DIR" "$REMOTE_DIR"; }

# 把 base 下现有的待同步文件备份到 base/backups（覆盖前保护）
backup_side() {
  local base="$1"
  local bdir="$base/backups"
  local any=0
  for f in "${DB_FILES[@]}"; do
    [ -f "$base/$f" ] || continue
    mkdir -p "$bdir"; cp -p "$base/$f" "$bdir/$f.$TS"; any=1
  done
  [ "$any" = 1 ] && yellow "  已把被覆盖方备份到 $bdir（$TS）"
}
copy_db(){
  local src="$1" dst="$2"
  for f in "${DB_FILES[@]}"; do
    [ -f "$src/$f" ] && cp -p "$src/$f" "$dst/$f" && green "  ✓ $f"
  done
}
copy_cache(){
  [ "$SYNC_CACHE" = "yes" ] || { yellow "  (SYNC_CACHE=no，跳过 cache/)"; return; }
  if [ -d "$1/cache" ]; then
    mkdir -p "$2/cache"
    cp -pr "$1/cache/." "$2/cache/" && green "  ✓ cache/（$(ls "$1/cache" | wc -l) 个文件）"
  fi
}
confirm(){ [ "${FORCE:-0}" = 1 ] && return 0; read -r -p "$1 [y/N] " ans; [[ "$ans" =~ ^[Yy]$ ]]; }

# ---------- 子命令 ----------
cmd_status(){
  bold "== 数据库新旧对比 =="
  db_busy && red "⚠ 存在 products.db-journal/wal，DB 可能正被占用或上次未正常关闭。"
  printf "%-26s %-20s %-20s\n" "文件" "本地(项目)" "同步目录"
  for f in "${DB_FILES[@]}"; do
    printf "%-26s %-20s %-20s\n" "$f" "$(fmt_date "$(mtime "$DATA_DIR/$f")")" "$(fmt_date "$(mtime "$REMOTE_DIR/$f")")"
  done
  local ldb rdb; ldb="$(mtime "$DATA_DIR/products.db")"; rdb="$(mtime "$REMOTE_DIR/products.db")"
  echo ""
  if   [ "$ldb" = 0 ] && [ "$rdb" = 0 ]; then yellow "→ 两边都没有 products.db。"
  elif [ "$ldb" -gt "$rdb" ]; then bold "→ 本地更新：收工时应执行  push"
  elif [ "$rdb" -gt "$ldb" ]; then bold "→ 同步目录更新：切到本机后应执行  pull"
  else green "→ 两边时间一致。"
  fi
}

cmd_push(){
  ensure_dirs
  if db_busy; then red "DB 处于占用状态，先正常关闭应用再 push。"; FORCE=1 confirm "强行继续？" || exit 1; fi
  bold "== push：项目 → 同步目录 =="
  backup_side "$REMOTE_DIR"
  copy_db   "$DATA_DIR" "$REMOTE_DIR"
  copy_cache "$DATA_DIR" "$REMOTE_DIR"
  green "完成。现在同步目录可以安全地交给另一台机器了。"
}

cmd_pull(){
  ensure_dirs
  if db_busy; then red "本地 DB 处于占用状态，先正常关闭应用再 pull。"; FORCE=1 confirm "强行继续？" || exit 1; fi
  [ -f "$REMOTE_DIR/products.db" ] || { red "同步目录里没有 products.db，无内容可拉。"; exit 1; }
  bold "== pull：同步目录 → 项目 =="
  local ldb rdb; ldb="$(mtime "$DATA_DIR/products.db")"; rdb="$(mtime "$REMOTE_DIR/products.db")"
  if [ "$ldb" -gt "$rdb" ]; then
    red "⚠ 本地 products.db 比同步目录还新！直接拉取会覆盖本地较新的数据。"
    confirm "确认覆盖本地较新版本吗？" || { yellow "已取消。"; exit 0; }
  fi
  backup_side "$DATA_DIR"
  copy_db    "$REMOTE_DIR" "$DATA_DIR"
  copy_cache "$REMOTE_DIR" "$DATA_DIR"
  green "完成。可以启动应用干活了。"
}

cmd_backup(){ bold "== backup：本地 DB 备份 =="; backup_side "$DATA_DIR"; green "完成。"; }

usage(){ sed -n '2,16p' "$0"; }

case "${1:-}" in
  status) cmd_status ;;
  push)   cmd_push ;;
  pull)   cmd_pull ;;
  backup) cmd_backup ;;
  *)      usage; exit 1 ;;
esac
