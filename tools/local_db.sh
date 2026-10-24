#!/bin/bash
# 在這個 repo 的 .localdb/ 開一個本機 Postgres(port 5433),給開發與測試用。
# 不註冊成系統服務,關掉電腦或執行 `tools/local_db.sh stop` 就停了。
#
#   tools/local_db.sh start    # 第一次會先建資料庫叢集與 mff_dev、mff_test 兩個資料庫
#   tools/local_db.sh stop
#
# 需要 PostgreSQL 18(和正式環境 Neon 同一個主版本):brew install postgresql@18
set -euo pipefail
# macOS 的 bash 3.2 遇到「$變數」後面緊接中文字會誤判。
export LC_ALL=C
cd "$(dirname "$0")/.."
PGBIN="${PGBIN:-$(brew --prefix postgresql@18)/bin}"
DATA=.localdb
PORT=5433

case "${1:-start}" in
  start)
    if [ ! -d "$DATA" ]; then
      "$PGBIN/initdb" -D "$DATA" -U postgres --auth=trust --encoding=UTF8 --locale=C >/dev/null
    fi
    "$PGBIN/pg_ctl" -D "$DATA" -o "-p $PORT -k /tmp" -l "$DATA/server.log" -w start
    for db in mff_dev mff_test; do
      "$PGBIN/psql" -h localhost -p "$PORT" -U postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$db'" | grep -q 1 \
        || "$PGBIN/createdb" -h localhost -p "$PORT" -U postgres "$db"
    done
    echo "DATABASE_URL=postgresql://postgres@localhost:$PORT/mff_dev"
    echo "TEST_DATABASE_URL=postgresql://postgres@localhost:$PORT/mff_test"
    ;;
  stop)
    "$PGBIN/pg_ctl" -D "$DATA" stop
    ;;
  *)
    echo "用法:tools/local_db.sh start|stop" >&2
    exit 1
    ;;
esac
