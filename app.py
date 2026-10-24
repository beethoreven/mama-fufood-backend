"""媽媽記副食品的後端。

    本機:   .venv/bin/python app.py                  (http://localhost:5003)
    正式:   gunicorn app:app --workers 1 --threads 8 --timeout 120

★ 一定要單一 worker:每人每天的次數放在記憶體裡,多個 worker 會各算各的
  (SPEC 第 3 節第 3 項)。

★ 不開 gunicorn 的 access log:那會把每個請求的 IP 寫進日誌,而我們承諾不保存 IP
  (隱私權政策第二條)。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import psycopg
from flask import Flask, jsonify
from flask_cors import CORS
from werkzeug.exceptions import HTTPException

import config
from db import connection
from db.connection import DatabaseBusy, DatabaseNotConfigured
from routes import admin, public
from services import public_cache

# 最大的請求是舊格式轉換(壓縮後 8 MiB);各支 API 另有自己更小的上限。
MAX_CONTENT_LENGTH = 9 * 1024 * 1024


def create_app(start_loader: bool = True) -> Flask:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH
    app.json.ensure_ascii = False

    if config.ALLOWED_ORIGINS:
        # 只有管理後台需要跨來源(網頁在 GitHub Pages);App 的請求不是瀏覽器發的,不受 CORS 影響。
        CORS(app, resources={r"/api/admin/*": {"origins": config.ALLOWED_ORIGINS}},
             allow_headers=["Authorization", "Content-Type"], methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
             max_age=600)

    app.register_blueprint(public.bp)
    app.register_blueprint(admin.bp)

    @app.get("/health")
    def health():
        """保活與健康檢查。**不碰資料庫**,cron-job.org 每 10 分鐘打一次也不會叫醒資料庫。"""
        return jsonify({"ok": True, "commit": config.COMMIT})

    @app.get("/ready")
    def ready():
        """快取載入了沒(部署後確認用)。快取是從資料庫載入的,載入成功就代表資料庫連得上。

        ★ 這支不需要登入,所以**不碰資料庫**:否則任何人每 5 分鐘打一次,就能讓 Neon
          一直醒著、把免費額度用完。最後一次連上資料庫的
          時間取自 db/connection.py 記下的值。
        """
        cache = public_cache.status()
        last = connection.last_ok
        return jsonify({
            "ok": cache["loaded"],
            "cache": cache,
            "database_last_ok": datetime.fromtimestamp(last, timezone.utc).isoformat() if last else None,
            "commit": config.COMMIT,
        }), 200 if cache["loaded"] else 503

    @app.errorhandler(DatabaseNotConfigured)
    def _db_not_configured(_exc):
        return jsonify({"error": "後端還沒設定資料庫", "code": "db_not_configured"}), 503

    @app.errorhandler(DatabaseBusy)
    def _db_busy(_exc):
        return jsonify({"error": "資料庫忙碌中,請稍後再試", "code": "db_busy"}), 503

    @app.errorhandler(psycopg.OperationalError)
    def _db_unavailable(_exc):
        return jsonify({"error": "資料庫暫時連不上,請稍後再試", "code": "db_unavailable"}), 503

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        messages = {404: "找不到這個網址", 405: "不支援這個操作", 413: "內容太大"}
        return jsonify({"error": messages.get(exc.code, exc.name), "code": f"http_{exc.code}"}), exc.code

    @app.errorhandler(Exception)
    def _unexpected(exc):
        # 只記型別與位置(堆疊),不記請求內容。
        logging.getLogger(__name__).exception("未預期的錯誤:%s", type(exc).__name__)
        return jsonify({"error": "伺服器發生錯誤", "code": "server_error"}), 500

    if start_loader:
        public_cache.start_background_loader()
    return app


app = create_app(start_loader=config.START_CACHE_LOADER)

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=config.PORT, debug=False)
