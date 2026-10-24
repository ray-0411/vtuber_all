# VTuber 專案遷移與 Codex 交接文件

更新日期：2026-09-28（Asia/Taipei）

這份文件是給下一個 Codex 與未來維護者的快速入口。它記錄目前架構、資料流、重要檔案、這段對話完成的工作、已知風險，以及搬到新資料夾後的接手方式。

## 1. 先讀這裡

- Git repository 根目錄是 `api_version/`，不是 `yt_dlp/`。
- repository 目前包含兩個主要子專案：
  - `yt_dlp/`：本機 YouTube／Twitch 採集器與 SQLite 資料來源。
  - `live_dashboard/`：靜態網站、本機 dashboard、Supabase schema/RPC 與部署工具。
- 時區以 `Asia/Taipei`（UTC+8）為主。
- 不可因測試而啟動長時間採集、排程、Supabase 上傳或部署。
- 不可提交 cookie、API key、Supabase DB URL、`.env.supabase.local`、備份、新產生的 DB、`.migration-backup/` 或 `.migration-work/`。
- 外層 `yt_dlp/live_data.db` 是正式持續寫入的採集 DB。Supabase 發布流程只能唯讀它並建立副本，絕對不可覆寫它。
- 目前工作樹已追蹤的 `yt_dlp/live_data.db` 有修改。這是正式運行資料，不要擅自回復、覆蓋或提交。

## 2. 整體資料流

```text
streamer_config.db
  └─ streamer_<group> 名單
       ↓ src/sync_streamers.py（每輪 collect_all 開始時自動執行）
live_data.db.streamer
       ↓
YouTube collector + Twitch collector
       ↓
live_data.db
  ├─ stream
  ├─ stream_snapshot
  ├─ current_live_status
  ├─ stream_title / stream_category / stream_tags
  └─ working

streamer_audience.db
  └─ 訂閱數、追隨數、頭像等較低頻補充資料

live_data.db（唯讀） + streamer_audience.db（唯讀）
       ↓ collector_supabase_tool/scripts/prepare_current_database.py
collector_supabase_tool/data/merged_live_data.db
       ↓ build_analytics_cache.py
collector_supabase_tool/data/merged_analytics_cache.db
       ↓ sync_merged_to_postgres.py（transaction + COPY）
Supabase PostgreSQL
  ├─ dashboard schema
  └─ analytics schema
       ↓ 受控 read-only RPC
live_dashboard/static（GitHub Pages）
```

## 3. 正常執行行為

### 採集

- `.main_catcher.bat` 啟動本機採集排程。
- 預設每 5 分鐘採集一次。
- `collect_all.py` 每輪先執行 `sync_streamers()`，所以在表單新增人員後，下一輪會自動同步到 `live_data.db`。
- `run_collect_once.bat` 只跑一輪。
- 採集期間會建立 `live_data.db.collect.lock`，避免重複採集或發布讀到不適合的時機。

### Supabase 定期發布

- 實際使用入口：`tools/publish/.supabase_update.bat`。
- 程式啟動後會先立即嘗試一次發布，不必等排程時間。
- 後續固定每小時 `03` 分與 `33` 分檢查，即每 30 分鐘一次，刻意避開採集器的 `00/05/10/...`。
- 若遇到 collector lock，該輪延後到下一個 `minute ≡ 3 (mod 5)`，例如 `03 → 08 → 13`。
- 只有 `live_data.db` 或 `streamer_audience.db` 的 size/mtime 改變才會再次上傳；`--force` 可強制。
- 視窗時間只顯示 `HH:MM:SS`。
- `streamer_audience.db` 只被讀取，不會在發布流程中重新抓資料。
- SQLite 發布副本使用 backup API 和 `.tmp` 完成後原子替換。
- Supabase 上傳使用單一 PostgreSQL transaction；中途停止會 rollback，不會留下半套資料。

## 4. 重要資料庫

| 檔案 | 用途 | 搬移注意事項 |
| --- | --- | --- |
| `yt_dlp/streamer_config.db` | VTuber 名單與各 Group 設定，資料表為 `streamer_<group>` | 重要正式資料；新增人員主要寫這裡 |
| `yt_dlp/live_data.db` | 持續寫入的直播主資料庫 | 絕不可被 merge/upload 工具覆寫；搬移前停止 scheduler 並備份 |
| `yt_dlp/streamer_audience.db` | 訂閱、追隨、頭像資料 | 更新頻率低；發布時合併進副本 |
| `yt_dlp/youtube_api_data.db` | WebSub + YouTube Data API 的獨立工作 DB | 與主要 collector 並行，部分結果會同步至 `live_data.db` |
| `collector_supabase_tool/data/merged_live_data.db` | 發布專用 DB | 可重建，不是 collector 主 DB，不提交 Git |
| `collector_supabase_tool/data/merged_analytics_cache.db` | 預先計算的網站分析資料 | 可重建，不提交 Git |
| `collector_supabase_tool/data/periodic_upload_state.json` | 上次成功上傳的來源 fingerprint | 可重建，不提交 Git；搬路徑後首次可能視為已變更 |
| `collector_supabase_tool/data/temp/*.db` | 曾從另一邊帶回的舊 DB／復原來源 | 本機資料；不可提交，整理前確認是否仍需保留 |

### `live_data.db` 核心表

- `streamer`：供 collector 使用的統一人員名單。
- `stream`：每場直播的身份與開始／結束資訊。
- `stream_snapshot`：定期觀看人數快照。
- `current_live_status`：每位成員每平台目前狀態。
- `stream_title`、`stream_category`、`stream_tags`：正規化 lookup 表。
- `working`：每輪 collector 的成功、失敗、耗時與錯誤紀錄。
- YouTube WebSub/API 表：由 `sql_init/014_youtube_websub.sql` 建立。

## 5. Group 與新增人員規則

目前新增表單只顯示 5 個可選 Group：

```text
other
meridian
squarelive
envision
thebox
```

目前 Supabase `dashboard.group_settings` 已復原的顯示順序：

```text
1 other
2 meridian
3 squarelive
4 envision
5 thebox
```

其他舊 Group 名稱仍可能存在於歷史資料或 `streamer_config.db`，不要在未確認歷史引用前直接刪表或改名。

`open_streamer_form.bat` 開啟中文表單：

- 基本資料寫入 `streamer_config.db`。
- 可輸入 VTuber ID、顯示名稱、YouTube URL/channel ID、Twitch URL/login、成員顯示順序、備註與 enabled。
- 可選填 YouTube 訂閱數、Twitch 追隨數、YouTube/Twitch 頭像 URL；這些寫入 `streamer_audience.db`。
- audience 選填欄位留空時，不會清除既有值。
- 「儲存後立即同步」會寫入 `live_data.db`；不勾選也會在下一輪 `collect_all` 自動同步。

## 6. `yt_dlp/` 檔案用途

### 根目錄入口與文件

| 檔案 | 用途 |
| --- | --- |
| `README.md` | 採集器整體說明、schema 與操作方式；目前部分中文可能顯示 mojibake，遷移時應統一 UTF-8 |
| `CHANGELOG.md` | 採集器版本與變更紀錄，必須保留 |
| `FILE_GUIDE.md` | 現有檔案分類說明；可用交接文件更新它，但不要無故刪除 |
| `YOUTUBE_COOKIE_SETUP.md` | YouTube cookie 設定方式 |
| `YOUTUBE_WEBSUB_SETUP.md` | WebSub + YouTube Data API 設定方式 |
| `requirements.txt` | Python 依賴（主要為 `yt-dlp`） |
| `package.json`, `package-lock.json` | Node.js / youtubei.js 依賴 |
| `.main_catcher.bat` | 啟動每 5 分鐘本機採集 |
| `run_collect_once.bat` | 執行單輪採集 |
| `open_streamer_form.bat` | 開啟中文人員新增／更新表單 |
| `open_youtube_websub_control.bat` | 開啟 WebSub/API 控制視窗 |
| `list_working.bat` | 查看最近工作紀錄 |
| `working_calendar.bat` | 以日曆檢視採集成功／失敗 |

### 主要採集程式

| 檔案 | 用途 |
| --- | --- |
| `src/run_local_scheduler.py` | 本機採集排程、timeout、process 管理與 `.collect.lock` |
| `src/collect_all.py` | 一輪總流程：同步人員 → Twitch → YouTube → 寫 working summary |
| `src/youtube_collector.py` | YouTube 直播狀態與快照寫入 |
| `src/youtube_live_ytjs.mjs` | youtubei.js 查詢 YouTube live 的 Node helper |
| `src/twitch_collector.py` | Twitch Helix live 狀態與快照寫入 |
| `src/youtube_utils.py` | YouTube channel ID 等共用功能 |
| `src/twitch_utils.py` | Twitch URL/login 解析與 API 共用功能 |
| `src/time_utils.py` | Asia/Taipei 時間格式共用功能 |
| `src/working_log.py` | 建立／完成／失敗 working job |

### 人員管理

| 檔案 | 用途 |
| --- | --- |
| `src/streamer_form.py` | 中文 Tkinter 新增／更新表單；固定 5 Group；可補 audience 欄位 |
| `src/add_streamer.py` | 命令列新增／更新單一人員 |
| `src/create_streamer_group.py` | 建立新的 `streamer_<group>` 表；表單目前不提供此功能 |
| `src/init_streamer_config.py` | 初始化名單 DB 與預設 Group |
| `src/streamer_tables.py` | Group table 名稱驗證、資料模型與讀取 |
| `src/sync_streamers.py` | 將所有 config group 合併覆寫至 `live_data.db.streamer` |
| `src/list_streamers.py` | 列出人員 |
| `src/backfill_youtube_channel_ids.py` | 補齊缺少的 YouTube channel ID |

### Audience

| 檔案 | 用途 |
| --- | --- |
| `src/build_streamer_audience_db.py` | 建立／重建 audience DB，來源可含既有 preview 與平台查詢 |
| `src/fetch_audience_avatars.py` | 抓取與更新平台頭像 |
| `src/youtube_audience_ytjs.mjs` | YouTube 公開訂閱數 helper |
| `src/youtube_avatar_ytjs.mjs` | YouTube 頭像 helper |

### WebSub + YouTube API 新流程

| 檔案 | 用途 |
| --- | --- |
| `src/youtube_webhook_server.py` | 接收 YouTube WebSub webhook |
| `src/youtube_websub_subscribe.py` | 建立／續訂 WebSub subscription |
| `src/youtube_websub_common.py` | WebSub 共用邏輯 |
| `src/youtube_websub_settings.py` | 本機設定與 Windows DPAPI 保護 |
| `src/youtube_websub_dashboard.py` | 本機控制 GUI、tunnel/webhook/API scheduler 管理 |
| `src/youtube_api_collector.py` | 使用 YouTube Data API `videos.list` 查候選直播 |
| `src/run_youtube_api_scheduler.py` | YouTube API collector 排程 |
| `src/youtube_api_db.py` | `youtube_api_data.db` schema 與存取 |
| `src/init_youtube_api_db.py` | 初始化 API DB |
| `src/migrate_youtube_api_data.py` | API/WebSub 資料 migration |
| `src/compare_youtube_collectors.py` | 比較舊 collector 與 API collector 結果 |
| `src/youtube_cookie.mjs` | YouTube cookie 相關 Node helper |
| `src/audit_youtube_channels.mjs` | 稽核 YouTube channel ID |

### Schema 與 migration

| 檔案 | 用途 |
| --- | --- |
| `src/init_db.py` | 依 `sql_init/` 初始化／升級 `live_data.db` |
| `sql_init/001_streamer_template.sql` | config group table 範本 |
| `sql_init/002_streamer.sql` | 統一 streamer 表 |
| `sql_init/009_stream_title.sql` | title lookup |
| `sql_init/009_stream_category.sql` | category lookup |
| `sql_init/009_stream_tags.sql` | tags lookup |
| `sql_init/010_stream.sql` | stream 表 |
| `sql_init/011_stream_snapshot.sql` | snapshot 表 |
| `sql_init/012_current_live_status.sql` | current status 表 |
| `sql_init/013_working.sql` | working 表 |
| `sql_init/014_youtube_websub.sql` | WebSub/API 相關表 |
| `src/migrate_stream_titles.py` | 舊 title 欄位正規化 migration |
| `src/migrate_stream_categories.py` | category 正規化 migration |
| `src/migrate_stream_tags.py` | tags 正規化 migration |
| `src/stream_titles.py` | title lookup helper |
| `src/stream_categories.py` | category lookup helper |
| `src/stream_tags.py` | tags lookup helper |

### 診斷與測試

| 檔案 | 用途 |
| --- | --- |
| `src/list_working.py` | 命令列查看 working 紀錄 |
| `src/working_calendar.py` | working 日曆 GUI |
| `tests/test_youtube_api_database.py` | API DB 測試 |
| `tests/test_youtube_websub.py` | WebSub 測試 |
| `tests/test_youtube_websub_dashboard.py` | 控制 GUI 邏輯測試 |
| `tests/test_youtube_websub_settings.py` | 設定保護測試 |
| `tests/test_streamer_form_audience.py` | 表單 Group 限制、數值驗證與 audience 不覆寫測試 |

## 7. `yt_dlp/collector_supabase_tool/` 檔案用途

這是目前實際使用的 collector-side 發布工具。

| 檔案 | 用途 |
| --- | --- |
| `.supabase_update.bat` | 啟動立即一次 + 每 30 分鐘定期發布 |
| `update_and_upload.bat` | 舊的完整 merge legacy + analytics + upload 流程 |
| `update_one_time.bat` | 使用已存在的 merged DB 直接上傳 |
| `setup.bat` | 安裝 `psycopg[binary]` |
| `settings.bat` | 舊 merge 流程來源路徑設定，假設工具位於 collector 下層 |
| `.env.supabase.local` | 私密 `SUPABASE_DB_URL`；不得提交或放入交接文件 |
| `.gitignore` | 排除 env、產生 DB、state、report |
| `scripts/run_periodic_upload.py` | 排程、來源 fingerprint、避開 collector lock、顯示狀態 |
| `scripts/prepare_current_database.py` | 唯讀 backup `live_data.db`，合併 audience，保留本機 group settings |
| `scripts/build_analytics_cache.py` | 產生 stream stats、30 分鐘活躍區間、以中午切日的 calendar day |
| `scripts/sync_merged_to_postgres.py` | 驗證來源、轉換時間、transactional TRUNCATE/COPY 至 Supabase |
| `scripts/merge_live_databases.py` | 舊 current + legacy + audience 合併；處理重疊 stream/snapshot |
| `scripts/create_group_settings.py` | 建立 group_settings，也可按成員數或平均觀看數排序 |
| `scripts/restore_group_settings.py` | 從備份 DB 復原有設定的 group rows 至本機與 Supabase |

### Group settings 的重要修正

- 曾經因完整 `TRUNCATE` 把 Supabase `dashboard.group_settings.display_order` 清成 NULL。
- 已從 `collector_supabase_tool/data/temp/live_data.db` 復原前述 5 筆順序並正式上傳驗證。
- 現在 `sync_merged_to_postgres.py` 不再 TRUNCATE `dashboard.group_settings`。
- 上傳時對 group settings 使用 `INSERT ... ON CONFLICT DO NOTHING`：只補新 Group，不覆寫遠端既有 `display_order/note`。
- `prepare_current_database.py` 與 `merge_live_databases.py` 也會保留既有設定。
- 遷移或重構時不可把這個保護退回舊的完整替換行為。

## 8. `live_dashboard/` 檔案用途

### 入口與本機服務

| 檔案 | 用途 |
| --- | --- |
| `README.md` | 網站架構、Supabase 與維護流程 |
| `CHANGELOG.md` | 網站版本與變更紀錄，必須保留 |
| `app.py` | 本機 Python dashboard/API fallback |
| `start_dashboard.bat` | 啟動本機網站 |
| `refresh_merged_data.bat` | 建立／更新本機 merged data |
| `upload_to_supabase.bat` | 網站側手動 Supabase 上傳入口 |
| `.env.example` | 非秘密的環境設定範本 |
| `requirements-sync.txt` | DB 同步所需 Python 依賴 |

### 靜態網站

| 檔案 | 用途 |
| --- | --- |
| `static/index.html`, `app.js`, `styles.css` | 首頁與即時資料 |
| `static/group.html`, `group.js` | Group 詳情 |
| `static/member.html`, `member.js` | 成員詳情 |
| `static/history.html`, `history.js` | 歷史直播與圖表 |
| `static/rankings.html`, `rankings.js`, `rankings.css` | 排名頁 |
| `static/about.html`, `about.css` | About 頁 |
| `static/api-client.js` | Supabase RPC／本機 API adapter |
| `static/supabase-config.js` | 瀏覽器可公開的 Supabase URL/publishable key；不可放 DB secret/service key |
| `static/navigation.js`, `navigation.css` | 共用導覽 |
| `static/dashboard-theme.css`, `site.js` | 共用主題與網站行為 |
| `static/build-version.js` | Pages workflow 產生的部署 commit 資訊 |
| `static/404.html` | GitHub Pages 子路由 fallback |

### Supabase 與資料工具

| 檔案 | 用途 |
| --- | --- |
| `supabase/migrations/001_initial_schema.sql` | dashboard/analytics 基礎 schema、RLS |
| `002_public_home_api.sql` | 首頁公開 RPC |
| `003_public_detail_api.sql` | Group/member/history/detail RPC |
| `004_period_average_rankings.sql` | 時段平均排名 |
| `005_stream_ranking_periods.sql` | 直播排名時段 |
| `006_effective_groups.sql` | effective Group；無 display_order 的 Group 視為 other |
| `007_member_rankings.sql` | 成員排名 materialized view/RPC |
| `scripts/apply_supabase_migration.py` | 套用 PostgreSQL migration |
| `scripts/check_supabase_public_api.py` | 檢查公開 RPC |
| `scripts/check_supabase_rest_api.py` | 檢查 REST 存取與安全 |
| `scripts/merge_live_databases.py` | dashboard 側 DB merge |
| `scripts/build_analytics_cache.py` | dashboard 側 analytics builder |
| `scripts/sync_merged_to_postgres.py` | dashboard 側 Supabase sync |
| `scripts/create_group_settings.py` | dashboard 側 Group 設定 |
| `scripts/migrate_legacy_data.py` | legacy 資料 migration |

## 9. 重複工具與 canonical source 風險

目前至少有三組相似的 Supabase 工具：

1. `yt_dlp/collector_supabase_tool/`：本次對話實際修改並運行的版本。
2. `live_dashboard/collector_supabase_tool/`：較舊的 dashboard 內副本。
3. `live_dashboard/update_sql_use/collector_supabase_tool/`：包含較新定期發布檔案的另一份副本。

重整目錄時應優先完成：

- 選定唯一 source of truth，建議放在 repository 共用的 `tools/` 或 `scripts/` 下。
- 其餘入口 BAT 只轉呼叫 canonical script，不再複製 Python 原始碼。
- 合併前以 diff 確認保留以下功能：
  - 外層 live DB 唯讀與 SQLite backup。
  - 30 分鐘排程與 `03/33` offset。
  - collector lock 延後重試。
  - Group settings 不被 TRUNCATE。
  - transaction/COPY/row-count validation。
  - analytics build 與網站最新 ranking materialized view refresh（以 dashboard 最新版為準）。

## 10. GitHub Actions

- workflows 統一在 repository 根目錄 `.github/workflows/`。
- `collect.yml`：collector workflow；目前 scheduled collection 曾因改成本機採集而停用，只保留手動觸發。搬路徑後要確認 working-directory/path。
- `pages.yml`：發布 `live_dashboard/static` 到 GitHub Pages，並產生部署 commit 資訊。
- 不要把 workflow 移回子專案 `.github/`。
- secrets 至少涉及 Twitch credentials；Supabase DB secret 不應暴露給 Pages/browser。

## 11. 已知問題與遷移風險

1. **相對路徑很多**：BAT 依賴 `cd /d "%~dp0"`；Python 多處用 `Path(__file__).parents[...]`。改資料夾深度後必須逐一修正。
2. **Supabase 工具重複**：見第 9 節，最容易造成改到錯誤副本。
3. **中文編碼**：部分 README/程式在目前 PowerShell 輸出呈 mojibake；BAT 內直接放 UTF-8 中文曾被 `cmd.exe` 當錯誤命令。穩妥做法是 BAT 保持 ASCII，中文由 Python UTF-8 輸出，並設定 `PYTHONUTF8=1`／`chcp 65001`。
4. **Group settings**：不可再次完整清空遠端表；它是可編輯設定，不是純衍生資料。
5. **正在運行的 DB**：搬移前停止 collector、WebSub/API scheduler、periodic uploader；確認 lock/process 結束後才複製 DB。
6. **SQLite 一致性**：不要用一般檔案 copy 搬正在寫入的 DB；停止服務後搬，或使用 SQLite backup API。
7. **正式 DB 與產生 DB 分離**：`live_data.db` 是來源；`merged_*.db` 是可重建輸出。
8. **不要相信資料夾名稱判斷最新版**：重複工具需用 diff 和實際入口確認。
9. **README/CHANGELOG 分開保留**：collector 與 dashboard 各有自己的歷史。

## 12. 建議的新目錄方向（尚未執行）

可考慮：

```text
repo/
├─ AGENTS.md
├─ README.md
├─ .github/workflows/
├─ collector/
│  ├─ src/
│  ├─ sql/
│  ├─ tests/
│  ├─ scripts/
│  └─ runtime-data/          # gitignored DB/lock，或改由設定指定外部 data dir
├─ dashboard/
│  ├─ static/
│  ├─ app.py
│  ├─ supabase/migrations/
│  └─ tests/
├─ tools/
│  └─ publish/               # 唯一一份 merge/analytics/Supabase sync
└─ docs/
   ├─ collector.md
   ├─ dashboard.md
   ├─ operations.md
   └─ migration-handoff.md
```

更理想的做法是讓所有 DB 路徑可由 CLI/env/config 指定，而非依賴腳本相對位置。不要在沒有 migration plan、備份與離線驗證的情況下一次改全部路徑。

## 13. 搬移後的安全驗證順序

不啟動正式排程，依序做：

1. `git status --short`，記錄使用者原有變更。
2. `python -m py_compile` 檢查搬過的 Python。
3. `node --check` 檢查搬過的 `.mjs/.js`（瀏覽器 module 視情況處理）。
4. `python -m unittest discover -s collector/tests -q`（依新路徑調整）。
5. 對 DB 副本執行 `PRAGMA integrity_check`、`foreign_key_check`。
6. 對發布流程執行 `--once --dry-run`，不可連 Supabase。
7. 檢查所有 BAT 的 `cd`、Python 相對路徑與資料庫參數。
8. 檢查 `.github/workflows` 的 working-directory 與 artifact/Pages path。
9. 確認 `.gitignore` 不會納入 env、cookie、DB、backup、lock、node_modules。
10. 最後才由使用者決定是否執行一次正式採集／上傳／部署。

## 14. 如何交給新資料夾裡的另一個 Codex

### 推薦方式：先把完整 repository 複製／clone 到新位置

不要只建立空資料夾後要求 Codex 猜專案。應先讓新資料夾至少包含：

- 全部 Git-tracked 原始碼與 `.git`（最推薦用 `git clone` 或完整搬 repository）。
- repository 根目錄 `AGENTS.md`。
- 本文件 `PROJECT_MIGRATION_HANDOFF.md`（可移到新根目錄 `docs/`）。
- collector 與 dashboard 的 README、CHANGELOG。
- 若要搬正式 DB，另以安全方式複製，但不要提交 Git；先保留原始備份。
- 私密 `.env`／cookie 不要透過對話或 Git 傳遞；在新機器／新資料夾人工重設。

### 在新 Codex 對話貼這段

```text
請先不要修改檔案，也不要啟動採集、排程、上傳或部署。

先完整閱讀：
1. AGENTS.md
2. PROJECT_MIGRATION_HANDOFF.md（若移到 docs，讀對應路徑）
3. collector/README.md 與 CHANGELOG.md
4. dashboard/README.md 與 CHANGELOG.md

接著檢查 git status、列出實際目錄，對照交接文件找出路徑差異、重複的 Supabase 工具及所有跨目錄依賴。先回報你理解的架構、正式資料來源、不可修改的檔案、建議的新目錄樹與分階段搬移計畫；等我確認後再實作。務必保留 live_data.db，且不得因驗證連線 Supabase 或啟動任何長時間程序。
```

### 如果新資料夾目前真的完全空白

另一個 Codex 無法讀取舊資料夾或這段對話時，至少先人工複製：

1. `AGENTS.md`
2. 本交接文件
3. `README.md`、兩個子專案 README/CHANGELOG
4. Git-tracked 原始碼，或讓它執行 `git clone`（若你允許且 repository 可存取）

只有文字交接、沒有原始碼時，它可以規劃，但無法可靠地修改或驗證。最穩妥是讓新 Codex 在完整 clone 上工作，再把正式 DB 作為 Git 外部 runtime data 掛入。

## 15. 給下一個 Agent 的第一輪檢查清單

- [ ] 確認 Git root 與新目錄樹。
- [ ] 讀完 AGENTS 與本文件。
- [ ] 查看 `git status`，不覆蓋使用者變更。
- [ ] 找出所有 `.db`、`.env*`、cookie、lock，但不要輸出秘密內容。
- [ ] 找出所有硬編碼 `live_data.db`、`streamer_audience.db`、`Path.parents`、`cd /d`、`working-directory`。
- [ ] 比較三份 Supabase 工具，選 canonical source。
- [ ] 保留 group settings 的非覆寫規則。
- [ ] 提出分階段遷移與 rollback 方式。
- [ ] 使用副本／dry-run 驗證。
- [ ] 未經使用者明確要求，不執行正式上傳或部署。
