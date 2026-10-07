#!/usr/bin/env bash
# 在 systemd 机器上安装「每 5 分钟巡检一次」的定时任务。
#
#   sudo bash deploy/install.sh [项目目录]
#
# 项目目录默认 /projects/bilibili_helper（单元文件里的路径就是照它写的）；
# 装在别处会自动改写单元里的路径。重复执行是安全的。
set -euo pipefail

PROJECT_DIR="${1:-/projects/bilibili_helper}"
UNIT_DIR=/etc/systemd/system
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ $EUID -ne 0 ]]; then
  echo "需要 root：sudo bash $0 ${1:-}" >&2
  exit 1
fi

if [[ ! -f "$PROJECT_DIR/manage_asoul_heartbeat.py" ]]; then
  echo "在 $PROJECT_DIR 里找不到 manage_asoul_heartbeat.py——项目目录不对？" >&2
  exit 1
fi

# 没有 cookie 时 manage 会直接报错退出。现在提醒，省得装完了发现巡检一直在空转。
if [[ ! -f "$PROJECT_DIR/.cookies.json" ]]; then
  echo "⚠️  $PROJECT_DIR/.cookies.json 不存在：没有它 manage 每轮都会直接退出。" >&2
  echo "    先放好凭据再跑，否则日志里只会一直刷 'ERROR: .cookies.json not found'。" >&2
fi

install -m 644 "$HERE/asoul-heartbeat.service" "$UNIT_DIR/asoul-heartbeat.service"
install -m 644 "$HERE/asoul-heartbeat.timer" "$UNIT_DIR/asoul-heartbeat.timer"

if [[ "$PROJECT_DIR" != /projects/bilibili_helper ]]; then
  sed -i "s#/projects/bilibili_helper#$PROJECT_DIR#g" \
    "$UNIT_DIR/asoul-heartbeat.service" "$UNIT_DIR/asoul-heartbeat.timer"
fi

systemctl daemon-reload
systemctl enable --now asoul-heartbeat.timer

echo
echo "✅ 已启用，下一次触发："
systemctl list-timers asoul-heartbeat.timer --no-pager | head -2
echo
echo "手动跑一轮： systemctl start asoul-heartbeat.service"
echo "看巡检日志： tail -f $PROJECT_DIR/logs/manage.log"
echo "停用：       systemctl disable --now asoul-heartbeat.timer"
