# 中文

## 媽媽記副食品 — 後端 API

寶寶副食品紀錄 App「媽媽記副食品」的後端 API(Flask)。這份文件分成兩個獨立的部分,請依需求閱讀:

- **[專案報告](#專案報告)**:後端負責什麼、刻意不做什麼、為什麼這樣設計、踩過哪些坑 —— 給想了解「這是什麼」的人看。
- **[架設 SOP](#架設-sop)**:在自己電腦上跑起來、跑測試、部署時要填的設定 —— 給想「動手把它跑起來」的人看。

這兩部分刻意分開,不要交叉閱讀;報告是背景知識,SOP 是操作手冊。

程式註解裡的「SPEC 第 N 節」、`SPEC_DRAFT.md`、`EXPORT_FORMAT_DRAFT.md`、`tools/*.py` 等,是只留在開發者本機的規格文件與工具,不在 repo 裡。

---

## 專案報告

### 這是什麼

「媽媽記副食品」是給新手爸媽記錄寶寶副食品的 Android App:每次吃了什麼、吃多少、有沒有過敏狀況、寶寶喜不喜歡。紀錄只存在手機與使用者自己的 Google 雲端硬碟,**後端完全不碰寶寶的資料**。後端只做四件事:

1. **公用資料**:食材清單(11 組、105 種)與單位。管理員在後台編輯草稿、按「發布」才產生新版本;App 每天檢查一次有沒有新版。
2. **每日檢查** `POST /api/v1/check`:回傳最低可用 App 版本(強制更新門檻)與各資料集的版本與內容。
3. **意見回饋** `POST /api/v1/feedback`:使用者按了送出才收,只存 Email 這一項個人資料,最長保留 90 天。
4. **舊格式轉換** `POST /api/v1/convert`:匯入舊版 App 的匯出檔、遇到格式衝突時才用,轉完就丟,不保存、不記錄內容。

另外有給管理後台網頁(`mama-fufood-web`)用的 `/api/admin/*`。

### 系統架構

整個專案是一個 git meta-repo(`mama-fufood`)透過 submodule 掛載三個獨立 repo:

```
mama-fufood/                     ← meta-repo,本機開發統一入口,本身不部署
├── mama-fufood-app/             ← Flutter Android App,本機打包、用 adb 安裝
├── mama-fufood-backend/         ← 本 repo,部署到 Render(Flask + gunicorn)
└── mama-fufood-web/             ← 網站與管理後台,部署到 GitHub Pages
```

資料的流向:

```
手機 App ──(每日檢查、意見回饋、舊格式轉換)──▶ 本後端(Render,新加坡)──▶ Neon Postgres(新加坡)
   │                                                ▲
   └──(紀錄同步、照片、匯出檔,直接連 Google)──▶ 使用者自己的 Google 雲端硬碟
                                                    │
管理後台網頁(GitHub Pages)────────────────────────┘
```

Render 與 Neon 都開在新加坡(ap-southeast-1)。這不是微調而是前提:姊妹專案 zh-cn-to-tw 實測,兩邊跨區時單次查詢 1.76 秒,同區 0.03 秒。Neon 的區域建好之後不能改。

### 為什麼寶寶的資料不上我們的伺服器

這是一個健康類 App,寶寶的名稱、吃了什麼、過敏狀況都是敏感資料。把它們放在使用者自己的手機與 Google 雲端硬碟,我們就沒有外洩、被要求調閱或刪除的責任,隱私權政策也能寫得很短很誠實。所以資料庫裡只有這些表:

| 表 | 內容 |
|---|---|
| `food_groups`、`foods`、`units` | 公用資料的草稿(後台編輯) |
| `dataset_releases` | 每次發布的版本與完整內容(App 下載的就是這個) |
| `app_config` | 強制更新門檻、提示文字 |
| `formats` | 各版匯出格式的欄位定義(啟動時從 `export_formats/v{N}.json` 寫入,後台只能看) |
| `feedback` | 意見回饋(Email、描述、App 版本、機型、診斷快照與記錄檔) |
| `admins`、`sessions` | 管理員白名單與後台登入的 session |

唯一的例外是「舊格式轉換」:匯出檔的格式改版後,舊檔裡的紀錄要送上來轉成新格式。這支 API 刻意設計成**無狀態**:驗證登入 → 讀完上傳的內容 → 轉換 → 壓縮後回傳,過程中不寫資料庫、不寫檔案、不記錄內容,而且一次只處理一份(`_convert_slot`,同時只有一個名額)。這個例外寫在使用者條款與隱私權政策裡。

意見回饋附上的診斷資料(記錄檔、logcat、當機摘要)在**手機上送出前**就遮蔽:Email、登入憑證、檔名、寶寶名稱、帳號的顯示名稱、電話、IP、裝置識別碼、雲端硬碟的檔案編號;記錄檔本身也只收事件代碼與數字,不寫備註與紀錄內容。使用者自己打的描述原樣保留,欄位的提示文字會提醒不要填寶寶姓名等個人資料。

### 每日檢查為什麼完全不碰資料庫

App 每天開啟時打一次 `/api/v1/check`。如果每次都查資料庫,Neon 就會一直被叫醒:Neon 免費方案每月 100 CU-hours(Neon 的方案頁另有「50」的寫法,兩處不一致),閒置 5 分鐘才會暫停。做法是:

- **公用資料放在記憶體快取**(`services/public_cache.py`)。資料庫才是唯一的來源,記憶體只是副本:收到第一個請求時(保活的 `/health` 也算)在背景開始載入,失敗就每 30 秒重試;**刻意不在 import 時開執行緒**:那個版本部署到 Render 後,背景載入一行記錄都沒有、資料庫一次都沒連上,`/ready` 一直是 503(本機跑不出這個問題);後台按下「發布」後重新載入。
- **每人每天 10 次的計數也只放記憶體**(`services/quota.py`),依 Google 帳號的 `sub` 計,台北時間午夜清空。重啟後計數歸零,代價只是當天多給幾次,可以接受。
- **不記 IP、不存裝置資訊**:gunicorn 的 access log 在程式裡直接關掉(`gunicorn.access` 這個 logger):啟動指令沒開,Render 上卻照樣印出每個請求,所以不依賴啟動參數;每日檢查只收 Google 的登入憑證、App 版本、平台(android),以及 App 手上各資料集的版本與它支援的格式版本。

`/health` 與 `/ready` 也都不碰資料庫:

- `/health` 給 cron-job.org 每 10 分鐘打一次保活(Render 免費方案閒置 15 分鐘會休眠,喚醒約 1 分鐘),只叫醒 Render、不叫醒 Neon。
- `/ready` 不需要登入,所以**一開始的版本會查資料庫是錯的**:任何人每 5 分鐘打一次就能讓 Neon 一直醒著、把免費額度用完。現在它只回報快取有沒有載入,以及最後一次成功連上資料庫的時間(`db/connection.py` 連線成功時記下)。

### 為什麼一定要單一 gunicorn worker

快取與「每人每天幾次」的計數都在 process 的記憶體裡。開兩個 worker,就會有兩份互不相干的計數,每天 10 次的上限實際上變成 20 次;快取也要各自載入、各自更新。所以啟動指令固定 `--workers 1 --threads 8`,用執行緒處理同時進來的請求。Render 免費方案只有 0.1 CPU、512 MB RAM,多開 worker 本來也沒有好處。

這是**刻意的**,不是漏設。啟動時的建表(`db/schema.py`)與發布都包在 Postgres 的 advisory lock 裡,所以就算之後改成多個 worker,也不會兩個同時建表而互卡(實測 3 個 worker 同時啟動沒有卡住)。

### 管理後台的登入:Google 憑證只用一次

Google 的 ID token 大約一小時就過期,不能拿來當長期憑證(否則後台開著超過一小時就會在操作中途失效)。做法沿用姊妹專案 group-judge:

- 後台登入時(`POST /api/admin/login`)驗證一次 Google ID token,換成我們自己簽發的 session token:前 40 個字是亂數,後 24 個字是 HMAC 簽章(金鑰從 `SESSION_SECRET` 衍生)。
- **滑動式有效期**:只要還在用就不會過期,連續 90 天沒用才過期。
- 簽章對不上的 token 直接拒絕,連資料庫都不碰;ID token 也會先檢查長度與形狀(最長 8192 字、三段式),亂打的請求不會讓後端去向 Google 要公開金鑰。
- 撤銷不靠 session:每次請求都會確認「這個 Email 現在還是不是管理員」(快取 30 秒),所以拿掉權限最慢 30 秒生效。

App 那邊則相反:每次打後端都帶一張**新的** ID token(快過期就先換),因為 App 不需要登入狀態,只需要證明「是一個真的 Google 帳號」來計算每人每天的次數。

### 防止被灌爆

第一版刻意**不做 IP 限流**(後端看不到真正的 IP,也不想記)。防護改成:

| 端點 | 防護 |
|---|---|
| `/api/v1/check` | 每個帳號每天 10 次;請求內容最大 16 KB |
| `/api/v1/feedback` | 每個帳號每天 3 則(存在資料庫);**在碰資料庫之前**先用記憶體擋掉每天第 20 次以後的嘗試;同一個 Email 用 advisory lock 排隊,避免同時送出時重複計數;整份最大約 1.6 MB,附件壓縮後 1 MiB、解壓後 4 MiB |
| `/api/v1/convert` | 每個帳號每天 5 次;壓縮後 8 MiB、解壓後 32 MiB;同時只處理一份 |
| `/api/admin/login` | 每個帳號每天 30 次嘗試(記憶體),擋在資料庫之前 |

另外,資料庫連線同時最多 5 條(`db/connection.py`),每句查詢最多 20 秒(`SET LOCAL statement_timeout`),連線逾時 8 秒,超過就回 503「資料庫忙碌中」,不會讓請求無限期地排隊。

意見回饋的資料表超過 150 MB 時就不再收附件(記錄檔),並在後台顯示警告;Neon 免費方案的儲存空間有限。

### 匯出格式的版本與轉換

App 的匯出檔(`.mff`)整份加密,後端看不到內容;但格式的「欄位定義」放在這裡:

- `export_formats/v{N}.json`:第 N 版的欄位定義,啟動時寫進 `formats` 表,後台可以看。
- `export_formats/__init__.py`:通用的檢查器,加上逐版轉換(`CONVERTERS[N]` = 第 N 版轉第 N+1 版)。
- `export_formats/samples/v{N}.json`:每一版保留一份樣本檔;測試會把所有舊樣本一路轉到最新版,並通過最新版的檢查。App 的測試也用同一份樣本,確認兩邊對格式的理解一致。

### 踩過的坑

- **psycopg 3 的 `with conn:` 結束時會關掉連線**,不只是 commit。建表的程式原本這樣寫,同一條連線接著要做的事就全部失敗;改成 `with conn.transaction():`。
- **Python 的預設參數在定義函式時就決定了**:`validate(data, version=CURRENT)` 讓「目前版本」永遠停在載入當下的值,轉換的測試因此回 500;改成 `version=None`、呼叫時才解析。
- **轉換的名額原本在讀上傳內容之前就先佔住**:一個上傳很慢的人就能讓其他人全部等 30 秒後失敗。改成先讀完內容、再佔名額。
- **快取的「還沒載入就載入」原本沒有上鎖**:兩個請求同時進來會各自載入一次。改成拿不到鎖的那個直接用現有狀態。
- **本機資料庫腳本在 macOS 內建的 bash 3.2 上出錯**:`$變數` 後面緊接中文字時會被誤判成變數名稱的一部分;腳本開頭加 `export LC_ALL=C`。

### 檔案結構

```
app.py                  路由入口(gunicorn 的啟動目標)、/health、/ready、錯誤處理
config.py               所有環境變數的唯一讀取點(先載入 .env 再讀,避免載入順序出錯)
auth_utils/
  ├── google_auth.py     Google ID token 驗證(含形狀檢查、公開金鑰快取)
  ├── sessions.py        管理後台的 session token(HMAC 簽章、滑動式有效期)
  └── access.py          管理員權限的檢查(每次確認還是不是管理員,快取 30 秒)
db/
  ├── connection.py      每個請求一條連線、同時最多 5 條、查詢逾時
  ├── schema.py          啟動時建表、放入第一版公用資料(advisory lock)
  ├── datasets.py        公用資料的草稿、發布與版本
  ├── app_config.py      強制更新門檻
  ├── feedback.py        意見回饋
  └── admins.py          管理員白名單
routes/
  ├── public.py          App 用的 API:每日檢查、意見回饋、舊格式轉換
  └── admin.py           管理後台的 API
services/
  ├── public_cache.py    公用資料的記憶體快取
  ├── quota.py           每人每天的計數(記憶體、台北時間午夜清空)
  ├── payload.py         讀取請求內容、限制大小、安全地解壓縮
  └── rejections.py      被拒絕的請求每分鐘統計(只記次數)
export_formats/          各版匯出格式的欄位定義、轉換與樣本檔
seed/                    第一版公用資料(和 App 內建的是同一份)
tests/                   pytest
tools/local_db.sh        本機開一個 Postgres 18(開發與測試用)
tools/read_feedback.py   用唯讀帳號讀正式環境的意見回饋(Part E)
textutil.py、timeutil.py 字數計算(一個 emoji 算一個字)、台北時間
```

### 已知限制

- **還沒有實際部署過**:Render、Neon、Google Cloud 的設定步驟寫在 meta repo 的 README(上線 SOP),還沒有照著跑過一次。
- Python 釘在 3.15.1(`.python-version`)。如果 Render 的部署 log 顯示它還沒有這個版本,要降到 Render 有的最新版,並在 `.python-version` 旁邊寫下原因。
- 計數與快取在記憶體,所以**重啟後當天的次數歸零**;Render 免費方案休眠再喚醒也算重啟。
- 只有一個 worker,同時能處理的請求數受限於 8 條執行緒與 5 條資料庫連線;以目前的使用規模綽綽有餘。
- 第一版沒有 IP 限流;如果真的被濫用,要在 Render 前面另外處理。

---

# 架設 SOP / Setup Guide

## Part A. 在你的 Mac 上跑起來

### 1. 確認 Python 版本

這個 repo 用 Python **3.15.1**(寫在 `.python-version`,本機與 Render 用同一版)。用 pyenv 安裝:

```bash
brew install pyenv
pyenv install 3.15.1
```

在這個資料夾裡執行 `python --version`,應該顯示 `Python 3.15.1`(pyenv 會自動讀 `.python-version`)。

### 2. 建立「虛擬環境」並安裝套件

虛擬環境是什麼:幫這個專案獨立準備一個「乾淨房間」,裝的套件不會跟電腦上其他 Python 專案打架。**這個專案一律在虛擬環境裡開發。**

```bash
cd mama-fufood-backend
python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
```

`requirements-dev.txt` 會一起裝好 `requirements.txt` 的套件和 pytest。之後的指令都直接寫 `.venv/bin/python`,不需要先 `activate`。

### 3. 開一個本機資料庫

後端一定要有資料庫才能啟動(沒有設定時不會退回任何預設的資料庫,是刻意的)。本機用 Postgres 18,和正式環境 Neon 同一個主版本:

```bash
brew install postgresql@18
tools/local_db.sh start
```

第一次會在 `.localdb/`(不進 git)建立資料庫,並建好 `mff_dev`(開發用)與 `mff_test`(測試用)兩個資料庫,最後印出兩行連線字串。用完執行 `tools/local_db.sh stop`;關機也會停,下次再 `start` 就好。

### 4. 設定 `.env`

`.env` 是放本機設定的檔案,**不進 git**。從範本複製一份:

```bash
cp .env.example .env
```

本機只要 `DATABASE_URL` 就能啟動(範本已經填好本機資料庫);要試管理後台的登入,再填 `GOOGLE_CLIENT_ID`、`FIRST_ADMIN_EMAIL`、`SESSION_SECRET`(見 Part C)。

### 5. 啟動

```bash
.venv/bin/python app.py
```

跑在 **5003**(同一台電腦常同時開著 group-judge 的 5002)。第一次啟動會自動建表、放入第一版的食材清單與單位。

### 6. 確認

瀏覽器打開:

- `http://localhost:5003/health` → `{"ok": true, "commit": ""}`(本機沒有 commit 資訊,是空的)
- `http://localhost:5003/ready` → `"ok": true`,`"cache"` 裡有食材清單與單位的版本(`20261023000000`)。剛啟動的頭一兩秒可能是 503(快取還在載入),重新整理即可。

要測需要登入的 API(`/api/v1/check` 等),要用真的 App 或管理後台網頁登入,因為它們需要 Google 的 ID token,瀏覽器網址列帶不了。

按 `Control + C` 停止。

---

## Part B. 跑測試

```bash
TEST_DATABASE_URL=postgresql://postgres@localhost:5433/mff_test .venv/bin/python -m pytest
```

目前 86 項。沒有設定 `TEST_DATABASE_URL` 時,需要資料庫的測試會跳過,其餘照跑。**測試會清空 `TEST_DATABASE_URL` 指向的資料庫,絕對不要指向正式的 Neon。**

---

## Part C. 部署到 Render

上線要和網站、App、Google Cloud 互相填網址與用戶端 ID,所以完整步驟集中寫在 meta repo [`mama-fufood`](https://github.com/beethoreven/mama-fufood) README 的「上線 SOP」,照那份的順序做。這裡只列 Render 上本身的設定:

| 欄位 | 值 |
|---|---|
| Region | **Singapore**(要和 Neon 同區) |
| Runtime | Python(版本讀 `.python-version`) |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `gunicorn app:app --workers 1 --threads 8 --timeout 120`(**一定要單一 worker**,原因見報告) |
| Instance Type | Free |

部署後用 `/health` 確認服務起來了、用 `/ready` 確認公用資料已從資料庫載入。

---

## Part D. 環境變數總覽

| 變數名稱 | 必填? | 說明 |
|---|---|---|
| `DATABASE_URL` | **必填** | Postgres 連線字串。正式環境用 Neon 的 pooled 連線(主機名稱有 `-pooler`)。沒設定時,需要資料庫的 API 一律回 503「後端還沒設定資料庫」。 |
| `GOOGLE_CLIENT_ID` | **必填** | Google Cloud「網頁應用程式」用戶端 ID。App 登入時的 serverClientId 也是它,所以 App 與後台送來的 ID token 都用它驗證。 |
| `ALLOWED_ORIGINS` | **必填**(要用管理後台時) | 允許呼叫 `/api/admin/*` 的網頁來源,逗號分隔、含 `https://`、**結尾不要斜線**,例如 `https://beethoreven.github.io`。App 的請求不是瀏覽器發的,不受影響。 |
| `FIRST_ADMIN_EMAIL` | **必填**(要用管理後台時) | 第一位管理員的 Google 帳號 Email。其他管理員在後台「管理員」頁新增。 |
| `SESSION_SECRET` | **必填**(要用管理後台時) | 後台 session 的簽章金鑰,一串夠長的亂數。沒設定時後台登入回 503,其他功能照常。換掉它,所有管理員要重新登入。 |
| `SESSION_IDLE_DAYS` | 選填 | 預設 90。後台 session 連續幾天沒用才過期。 |
| `AUTH_CACHE_TTL_SECONDS` | 選填 | 預設 30。拿掉管理員權限後,最慢幾秒生效。 |
| `DAILY_CHECK_LIMIT` | 選填 | 預設 10。每個帳號每天的檢查次數。 |
| `FEEDBACK_DAILY_LIMIT` | 選填 | 預設 3。每個帳號每天的意見回饋則數。 |
| `CONVERT_DAILY_LIMIT` | 選填 | 預設 5。每個帳號每天的舊格式轉換次數。 |
| `FEEDBACK_RETENTION_DAYS` | 選填 | 預設 90。意見回饋保留天數。 |
| `FEEDBACK_TABLE_LIMIT_MB` | 選填 | 預設 150。意見回饋資料表超過這個大小就不再收附件。 |
| `DB_TIMEOUT_SECONDS` | 選填 | 預設 20。一句查詢最多等幾秒。 |
| `CACHE_RETRY_SECONDS` | 選填 | 預設 30。快取載入失敗後隔幾秒重試。 |
| `PORT` | 選填 | 預設 5003。Render 會自己帶,不用設。 |

產生 `SESSION_SECRET`:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

## Part E. 在本機讀正式環境的意見回饋(唯讀)

除錯時想直接看意見回饋與記錄檔,不想開後台,可以用 `tools/read_feedback.py`。它用**只能讀 feedback 表**的帳號連正式資料庫,連線本身也設成唯讀;不要用 Render 上那組 `DATABASE_URL`(那組可以改、可以刪)。

**E1. 建立唯讀帳號(只做一次)。** Neon 控制台 → 專案 → 左側 **SQL Editor**,資料庫選 `neondb`,執行下面這段(密碼換成自己產生的一串,例如 `python3 -c "import secrets; print(secrets.token_urlsafe(24))"`):

```sql
CREATE ROLE mff_readonly WITH LOGIN PASSWORD '換成你的密碼';
GRANT CONNECT ON DATABASE neondb TO mff_readonly;
GRANT USAGE ON SCHEMA public TO mff_readonly;
GRANT SELECT ON feedback TO mff_readonly;
```

★ 一定要用 SQL 建,不要在 Neon 控制台的 **Roles** 頁面建:那裡建的帳號會自動加入 `neon_superuser`,權限很大([Neon 說明](https://neon.com/docs/manage/roles))。

**E2. 存連線字串(在 repo 外面,不會進 git)。** 把 Render 上 `DATABASE_URL` 的帳號密碼換成上面那組,其他(主機、資料庫名稱、`?sslmode=require`)不變,存成 `~/.config/mama-fufood/readonly.env`:

```bash
mkdir -p ~/.config/mama-fufood
nano ~/.config/mama-fufood/readonly.env
chmod 600 ~/.config/mama-fufood/readonly.env
```

檔案內容只有一行:`MFF_READONLY_DATABASE_URL=postgresql://mff_readonly:<密碼>@<主機>/neondb?sslmode=require`

**E3. 讀。**

```bash
.venv/bin/python tools/read_feedback.py
```

列出最近 10 則(編號前 8 碼、時間、類型、狀態、版本、機型、描述開頭)。看某一則的完整內容與記錄檔:

```bash
.venv/bin/python tools/read_feedback.py 編號前幾碼
```

程式不會印出連線字串;連不上時只印錯誤類型。要停用這個帳號:在 SQL Editor 執行 `DROP ROLE mff_readonly;`。

---

# English

## Mama's Baby Food Log — Backend API

The backend API (Flask) for *媽媽記副食品* ("Mama's Baby Food Log"), an app for logging a baby's complementary food. This document is split into two independent parts — read whichever fits what you need:

- **[Project Report](#project-report)**: what the backend is responsible for, what it deliberately does not do, why it is designed this way, and the pitfalls hit along the way — for anyone who wants to understand "what is this."
- **[Setup Guide](#setup-guide)**: running it on your own machine, running the tests, and the settings needed for deployment — for anyone who wants to "get it running."

These two parts are deliberately kept separate — don't read them interleaved; the report is background knowledge, the guide is an operating manual.

References in code comments such as "SPEC 第 N 節" (SPEC section N), `SPEC_DRAFT.md`, `EXPORT_FORMAT_DRAFT.md` and `tools/*.py` point to specs and tools that live only on the developer's machine; they are not in this repo.

## Project Report

### What This Is

*媽媽記副食品* is an Android app for new parents to log their baby's complementary food: what the baby ate each time, how much, whether there was an allergic reaction, and whether the baby liked it. Records live only on the phone and in the user's own Google Drive — **the backend never touches the baby's data**. The backend does exactly four things:

1. **Public data**: the food list (11 groups, 105 foods) and units. Admins edit a draft in the admin console; a new version only exists once they press "Publish". The app checks for a new version once a day.
2. **Daily check** `POST /api/v1/check`: returns the minimum usable app version (the force-update threshold) plus each dataset's version and content.
3. **Feedback** `POST /api/v1/feedback`: only received when the user presses send; the email address is the only personal data kept, for at most 90 days.
4. **Old-format conversion** `POST /api/v1/convert`: used only when importing an export file from an older app version runs into a format conflict; the result is discarded right after conversion — nothing is stored and the content is never logged.

There is also `/api/admin/*` for the admin console website (`mama-fufood-web`).

### System Architecture

The whole project is a git meta-repo (`mama-fufood`) that wraps three independent repos via submodules:

```
mama-fufood/                     ← meta-repo, unified local-dev entry point, never deployed itself
├── mama-fufood-app/             ← Flutter Android app, built locally and installed via adb
├── mama-fufood-backend/         ← this repo, deployed to Render (Flask + gunicorn)
└── mama-fufood-web/             ← website and admin console, deployed to GitHub Pages
```

How data flows:

```
Phone app ──(daily check, feedback, old-format conversion)──▶ this backend (Render, Singapore) ──▶ Neon Postgres (Singapore)
   │                                                ▲
   └──(record sync, photos, export files — straight to Google)──▶ the user's own Google Drive
                                                    │
Admin console website (GitHub Pages) ──────────────┘
```

Render and Neon are both in Singapore (ap-southeast-1). This is a prerequisite, not a tweak: in the sister project zh-cn-to-tw, a single query took 1.76 s across regions and 0.03 s within the same region. A Neon project's region cannot be changed after creation.

### Why the Baby's Data Never Reaches Our Server

This is a health-related app; the baby's name, what it ate and its allergic reactions are all sensitive data. Keeping them on the user's own phone and Google Drive means we carry no responsibility for leaks, disclosure requests or deletion requests, and the privacy policy can be short and honest. So the database only has these tables:

| Table | Contents |
|---|---|
| `food_groups`, `foods`, `units` | Drafts of the public data (edited in the admin console) |
| `dataset_releases` | Each published version with its full content (this is what the app downloads) |
| `app_config` | Force-update threshold and notice text |
| `formats` | Field definitions of each export format version (written at startup from `export_formats/v{N}.json`; read-only in the admin console) |
| `feedback` | Feedback (email, description, app version, device model, diagnostic snapshot and log file) |
| `admins`, `sessions` | Admin allowlist and admin-console login sessions |

The one exception is old-format conversion: after the export format changes, records in an old file must be sent up to be converted to the new format. This API is deliberately **stateless**: verify the login → read the uploaded content in full → convert → return it compressed, with no database writes, no files and no content logging along the way — and only one conversion at a time (`_convert_slot`, a single slot). This exception is spelled out in the terms of use and the privacy policy.

The diagnostics attached to feedback (log files, logcat, crash summaries) are masked **on the phone before sending**: emails, sign-in credentials, file names, baby names, the account's display name, phone numbers, IPs, device identifiers and Google Drive file IDs; the log files themselves only record event codes and numbers, never notes or record contents. The description the user types is kept as written; the field's hint text reminds them not to enter the baby's name or other personal data.

### Why the Daily Check Never Touches the Database

The app calls `/api/v1/check` once a day when it opens. If every call queried the database, Neon would keep being woken up: Neon's free plan gives 100 CU-hours per month (Neon's plans page also says "50" elsewhere — the two disagree), and it only suspends after 5 minutes idle. Instead:

- **Public data lives in an in-memory cache** (`services/public_cache.py`). The database is the only source of truth; memory is just a copy: it starts loading in the background on the first request (the keep-alive `/health` counts), retries every 30 seconds on failure; **it deliberately doesn't start a thread at import time**: that version, deployed to Render, never logged a single line from the background load and never reached the database, leaving `/ready` at 503 (the problem doesn't reproduce locally); it reloads after "Publish" is pressed in the admin console.
- **The 10-per-day count per person also lives only in memory** (`services/quota.py`), keyed by the Google account's `sub` and reset at midnight Taipei time. A restart resets the counts, which only means a few extra checks that day — acceptable.
- **No IPs, no device information stored**: gunicorn's access log is switched off in code (the `gunicorn.access` logger): the start command doesn't enable it, yet Render printed every request anyway, so this doesn't rely on start-up arguments; the daily check only receives the Google sign-in credential, the app version, the platform (android), and the version of each dataset the app holds plus the format versions it supports.

`/health` and `/ready` don't touch the database either:

- `/health` is pinged by cron-job.org every 10 minutes to keep the service awake (Render's free tier sleeps after 15 minutes idle and takes about a minute to wake), waking Render without waking Neon.
- `/ready` requires no login, so **the first version querying the database was a mistake**: anyone pinging it every 5 minutes could keep Neon awake and burn through the free quota. It now only reports whether the cache is loaded and when the database was last reached successfully (recorded by `db/connection.py` on each successful connection).

### Why There Must Be Exactly One gunicorn Worker

The cache and the per-person daily counts live in the process's memory. With two workers there would be two unrelated sets of counts, so the 10-per-day limit would effectively become 20; each worker would also load and refresh its own cache. So the start command is fixed at `--workers 1 --threads 8`, using threads for concurrent requests. Render's free tier has only 0.1 CPU and 512 MB RAM, so more workers wouldn't help anyway.

This is **deliberate**, not an oversight. Table creation at startup (`db/schema.py`) and publishing are both wrapped in Postgres advisory locks, so even if this later moves to multiple workers, two of them can't create tables at the same time and deadlock (tested: 3 workers starting at once did not hang).

### Admin Console Login: The Google Credential Is Used Once

Google ID tokens expire after roughly an hour, so they can't be used as a long-lived credential (otherwise the admin console would fail mid-task after an hour). The approach follows the sister project group-judge:

- At admin login (`POST /api/admin/login`) the Google ID token is verified once and exchanged for a session token we issue ourselves: 40 random hex characters followed by a 24-character HMAC signature (the key is derived from `SESSION_SECRET`).
- **Sliding expiry**: it never expires while in use; it only expires after 90 consecutive days without use.
- Tokens with a bad signature are rejected without touching the database; ID tokens are also checked for length and shape first (at most 8192 characters, three segments), so junk requests don't make the backend fetch Google's public keys.
- Revocation doesn't rely on the session: every request re-checks "is this email still an admin right now" (cached for 30 seconds), so removing someone takes effect within 30 seconds.

The app does the opposite: every call to the backend carries a **fresh** ID token (refreshed before it expires), because the app needs no login state — only proof that it is a real Google account, so the per-person daily counts can be applied.

### Protection Against Abuse

The first version deliberately has **no IP rate limiting** (the backend can't see the real IP, and we don't want to record it). Protection works like this instead:

| Endpoint | Protection |
|---|---|
| `/api/v1/check` | 10 per account per day; request body at most 16 KB |
| `/api/v1/feedback` | 3 per account per day (stored in the database); attempts beyond the 20th of the day are rejected in memory **before touching the database**; the same email is serialized with an advisory lock so concurrent sends can't double-count; whole request at most about 1.6 MB, attachment at most 1 MiB compressed and 4 MiB decompressed |
| `/api/v1/convert` | 5 per account per day; at most 8 MiB compressed and 32 MiB decompressed; one conversion at a time |
| `/api/admin/login` | 30 attempts per account per day (in memory), rejected before the database |

In addition, at most 5 database connections are open at once (`db/connection.py`), each statement may run at most 20 seconds (`SET LOCAL statement_timeout`), and connecting times out after 8 seconds; beyond that the API returns 503 "database busy" instead of queueing requests indefinitely.

Once the feedback table exceeds 150 MB, attachments (log files) are no longer accepted and the admin console shows a warning; storage on Neon's free plan is limited.

### Export Format Versions and Conversion

The app's export files (`.mff`) are fully encrypted, so the backend can't see their content; but the format's field definitions live here:

- `export_formats/v{N}.json`: the field definitions of version N, written into the `formats` table at startup and viewable in the admin console.
- `export_formats/__init__.py`: a generic validator plus step-by-step conversion (`CONVERTERS[N]` converts version N to N+1).
- `export_formats/samples/v{N}.json`: one sample file kept for every version; the tests convert every old sample all the way to the latest version and check it passes the latest validation. The app's tests use the same sample, confirming both sides understand the format the same way.

### Pitfalls Hit Along the Way

- **psycopg 3's `with conn:` closes the connection on exit**, not just commits. The table-creation code was originally written that way, so everything the same connection did next failed; it now uses `with conn.transaction():`.
- **Python default arguments are evaluated when the function is defined**: `validate(data, version=CURRENT)` froze "the current version" at import time, so the conversion tests returned 500; it is now `version=None`, resolved at call time.
- **The conversion slot used to be taken before reading the upload**: a single slow uploader could make everyone else wait 30 seconds and fail. It now reads the content first and takes the slot afterwards.
- **"Load the cache if not loaded yet" originally had no lock**: two requests arriving together each loaded it. Now whoever can't get the lock just uses the current state.
- **The local database script broke on macOS's built-in bash 3.2**: a `$variable` immediately followed by a Chinese character was treated as part of the variable name; the script now starts with `export LC_ALL=C`.

### File Layout

```
app.py                  routing entry point (gunicorn's target), /health, /ready, error handlers
config.py               the single place environment variables are read (loads .env first, so import order can't go wrong)
auth_utils/
  ├── google_auth.py     Google ID token verification (shape checks, public-key caching)
  ├── sessions.py        admin-console session tokens (HMAC signature, sliding expiry)
  └── access.py          admin permission checks (re-checks admin status on every request, cached 30 s)
db/
  ├── connection.py      one connection per request, at most 5 at once, statement timeout
  ├── schema.py          creates tables and seeds the first public data at startup (advisory lock)
  ├── datasets.py        public-data drafts, publishing and versions
  ├── app_config.py      force-update threshold
  ├── feedback.py        feedback
  └── admins.py          admin allowlist
routes/
  ├── public.py          APIs for the app: daily check, feedback, old-format conversion
  └── admin.py           APIs for the admin console
services/
  ├── public_cache.py    in-memory cache of the public data
  ├── quota.py           per-person daily counts (memory, reset at midnight Taipei time)
  ├── payload.py         reads request bodies with size limits and safe decompression
  └── rejections.py      per-minute statistics of rejected requests (counts only)
export_formats/          export format field definitions, conversions and sample files
seed/                    the first public data (identical to the copy built into the app)
tests/                   pytest
tools/local_db.sh        starts a local Postgres 18 (for development and tests)
tools/read_feedback.py   reads production feedback with a read-only account (Part E)
textutil.py, timeutil.py character counting (an emoji counts as one character), Taipei time
```

### Known Limitations

- **Not deployed yet**: the Render, Neon and Google Cloud setup steps are in the meta repo's README (Setup Guide) and have not been run end to end yet.
- Python is pinned to 3.15.1 (`.python-version`). If Render's deploy log says it doesn't offer that version yet, drop to the newest version Render has and note the reason next to `.python-version`.
- Counts and cache live in memory, so **a restart resets that day's counts**; Render's free tier waking up from sleep counts as a restart.
- With one worker, concurrency is bounded by 8 threads and 5 database connections — far more than enough at the current scale.
- The first version has no IP rate limiting; real abuse would have to be handled in front of Render.

---

# Setup Guide

## Part A. Run It on Your Mac

### 1. Check the Python Version

This repo uses Python **3.15.1** (written in `.python-version`; local and Render use the same version). Install it with pyenv:

```bash
brew install pyenv
pyenv install 3.15.1
```

Running `python --version` inside this folder should print `Python 3.15.1` (pyenv reads `.python-version` automatically).

### 2. Create a "Virtual Environment" and Install Packages

What a virtual environment is: it sets up an independent "clean room" for this project, so the packages it installs don't clash with other Python projects on your machine. **This project is always developed inside a virtual environment.**

```bash
cd mama-fufood-backend
python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
```

`requirements-dev.txt` installs everything in `requirements.txt` plus pytest. All later commands call `.venv/bin/python` directly, so there's no need to `activate` first.

### 3. Start a Local Database

The backend needs a database to work (when none is configured it does not fall back to any default database — deliberately). Locally we use Postgres 18, the same major version as Neon in production:

```bash
brew install postgresql@18
tools/local_db.sh start
```

The first run creates the database cluster in `.localdb/` (not in git) with two databases, `mff_dev` (development) and `mff_test` (tests), and prints two connection strings. Run `tools/local_db.sh stop` when you're done; shutting down the computer also stops it — just `start` again next time.

### 4. Set Up `.env`

`.env` holds local settings and **is not in git**. Copy it from the template:

```bash
cp .env.example .env
```

Locally only `DATABASE_URL` is needed to start (the template already points at the local database); to try the admin-console login, also fill in `GOOGLE_CLIENT_ID`, `FIRST_ADMIN_EMAIL` and `SESSION_SECRET` (see Part D).

### 5. Start the Server

```bash
.venv/bin/python app.py
```

It runs on **5003** (group-judge's 5002 is often running on the same machine). The first start creates the tables and seeds the first food list and units.

### 6. Check It

Open in your browser:

- `http://localhost:5003/health` → `{"ok": true, "commit": ""}` (there's no commit information locally, so it's empty)
- `http://localhost:5003/ready` → `"ok": true`, with the food list and unit versions (`20261023000000`) under `"cache"`. In the first second or two after starting it may return 503 (the cache is still loading); just refresh.

APIs that need a login (`/api/v1/check` etc.) need a Google ID token, which a browser address bar can't send, so test them through the real app or the admin console website.

Press `Control + C` to stop.

---

## Part B. Run the Tests

```bash
TEST_DATABASE_URL=postgresql://postgres@localhost:5433/mff_test .venv/bin/python -m pytest
```

86 tests at the moment. Without `TEST_DATABASE_URL`, the tests that need a database are skipped and the rest still run. **The tests wipe the database `TEST_DATABASE_URL` points at — never point it at the production Neon database.**

---

## Part C. Deploy to Render

Going live means filling URLs and client IDs back and forth between the website, the app and Google Cloud, so the complete steps live in the "Setup Guide" of the meta repo [`mama-fufood`](https://github.com/beethoreven/mama-fufood) README — follow that order. Only Render's own settings are listed here:

| Field | Value |
|---|---|
| Region | **Singapore** (must match Neon) |
| Runtime | Python (version read from `.python-version`) |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `gunicorn app:app --workers 1 --threads 8 --timeout 120` (**must be a single worker** — see the report) |
| Instance Type | Free |

After deploying, use `/health` to confirm the service is up and `/ready` to confirm the public data has loaded from the database.

---

## Part D. Environment Variables Overview

| Variable | Required? | Description |
|---|---|---|
| `DATABASE_URL` | **Required** | Postgres connection string. In production use Neon's pooled connection (its host name contains `-pooler`). Without it, every API that needs the database returns 503 "backend has no database configured". |
| `GOOGLE_CLIENT_ID` | **Required** | The Google Cloud "Web application" client ID. The app's serverClientId is the same value, so ID tokens from both the app and the admin console are verified against it. |
| `ALLOWED_ORIGINS` | **Required** (for the admin console) | Web origins allowed to call `/api/admin/*`, comma-separated, including `https://`, **no trailing slash**, e.g. `https://beethoreven.github.io`. Requests from the app aren't made by a browser and are unaffected. |
| `FIRST_ADMIN_EMAIL` | **Required** (for the admin console) | The Google account email of the first admin. Other admins are added on the console's "管理員" (Admins) page. |
| `SESSION_SECRET` | **Required** (for the admin console) | Signing key for admin sessions — a long random string. Without it the admin login returns 503 while everything else keeps working. Changing it signs every admin out. |
| `SESSION_IDLE_DAYS` | Optional | Default 90. Days of no use before an admin session expires. |
| `AUTH_CACHE_TTL_SECONDS` | Optional | Default 30. Seconds until removing an admin takes effect, at most. |
| `DAILY_CHECK_LIMIT` | Optional | Default 10. Daily checks per account per day. |
| `FEEDBACK_DAILY_LIMIT` | Optional | Default 3. Feedback messages per account per day. |
| `CONVERT_DAILY_LIMIT` | Optional | Default 5. Old-format conversions per account per day. |
| `FEEDBACK_RETENTION_DAYS` | Optional | Default 90. Days feedback is kept. |
| `FEEDBACK_TABLE_LIMIT_MB` | Optional | Default 150. Above this size the feedback table stops accepting attachments. |
| `DB_TIMEOUT_SECONDS` | Optional | Default 20. Maximum seconds a single statement may run. |
| `CACHE_RETRY_SECONDS` | Optional | Default 30. Seconds between retries after the cache fails to load. |
| `PORT` | Optional | Default 5003. Render sets it itself — no need to configure. |

Generating `SESSION_SECRET`:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

## Part E. Read Production Feedback Locally (Read-Only)

When debugging, to look at feedback and its logs without opening the admin console, use `tools/read_feedback.py`. It connects to the production database with an account that **can only read the feedback table**, and the connection itself is also set to read-only; don't use the `DATABASE_URL` from Render (that one can modify and delete).

**E1. Create the read-only account (once).** Neon console → project → **SQL Editor** on the left, database `neondb`, run the following (replace the password with one you generate, e.g. `python3 -c "import secrets; print(secrets.token_urlsafe(24))"`):

```sql
CREATE ROLE mff_readonly WITH LOGIN PASSWORD 'your password here';
GRANT CONNECT ON DATABASE neondb TO mff_readonly;
GRANT USAGE ON SCHEMA public TO mff_readonly;
GRANT SELECT ON feedback TO mff_readonly;
```

★ Create it with SQL, not on the Neon console's **Roles** page: accounts created there are automatically members of `neon_superuser` and have broad privileges ([Neon docs](https://neon.com/docs/manage/roles)).

**E2. Store the connection string (outside the repo, never in git).** Take Render's `DATABASE_URL`, replace the user and password with the account above, keep everything else (host, database name, `?sslmode=require`), and save it as `~/.config/mama-fufood/readonly.env`:

```bash
mkdir -p ~/.config/mama-fufood
nano ~/.config/mama-fufood/readonly.env
chmod 600 ~/.config/mama-fufood/readonly.env
```

The file has a single line: `MFF_READONLY_DATABASE_URL=postgresql://mff_readonly:<password>@<host>/neondb?sslmode=require`

**E3. Read.**

```bash
.venv/bin/python tools/read_feedback.py
```

lists the latest 10 (first 8 characters of the ID, time, kind, status, version, device model, start of the description). For one item's full content and logs:

```bash
.venv/bin/python tools/read_feedback.py first-few-characters-of-the-ID
```

The tool never prints the connection string; on a connection failure it only prints the error type. To disable the account, run `DROP ROLE mff_readonly;` in the SQL Editor.
