# 專案檔案指南

這份文件用來快速辨認每個檔案的用途，方便整理專案。標記說明：

- **核心**：正式收集流程會使用，不建議移動或刪除。
- **工具**：需要時手動執行，建議保留。
- **資料**：正式資料庫或人工整理結果，刪除前務必確認與備份。
- **可重建**：由安裝或執行流程產生，通常可刪除後重建。
- **舊版／暫存**：不參與目前正式流程，可考慮封存或清除。

## 最常用的入口

| 檔案 | 用途 | 分類 |
| --- | --- | --- |
| `start_local_scheduler.bat` | 啟動本機排程器，每 5 分鐘執行一次完整收集。 | 核心 |
| `run_collect_once.bat` | 使用與 scheduler 相同的抓取方式，只執行一輪後結束。 | 核心 |
| `open_streamer_form.bat` | 開啟新增／修改 VTuber 的圖形表單。 | 工具 |
| `open_youtube_websub_control.bat` | 開啟 WebSub + 官方 API 本機瀏覽器控制台。 | 第二套驗證管線 |
| `list_working.bat` | 顯示最近 30 筆收集工作紀錄，可接額外參數。 | 工具 |
| `working_calendar.bat` | 以日曆視窗查看收集成功、失敗與錯誤紀錄。 | 工具 |

## 根目錄

| 檔案／目錄 | 用途 | 分類與整理建議 |
| --- | --- | --- |
| `README.md` | 完整專案說明、資料表結構與指令範例。 | 文件，保留 |
| `CHANGELOG.md` | 各版本新增、變更與修正紀錄。 | 文件，保留 |
| `YOUTUBE_WEBSUB_SETUP.md` | 第二套 WebSub + YouTube Data API collector 的設定與部署說明。 | 文件，保留 |
| `FILE_GUIDE.md` | 本文件；以整理檔案為目的的精簡索引。 | 文件，保留 |
| `requirements.txt` | Python 相依套件，目前主要是 `yt-dlp`。 | 核心，保留 |
| `package.json` | Node.js 相依套件設定，目前使用 `youtubei.js`。 | 核心，保留 |
| `package-lock.json` | 鎖定 Node.js 套件的確切版本，讓不同環境安裝結果一致。 | 核心，保留 |
| `.gitignore` | Git 忽略規則，例如虛擬環境、快取與 `node_modules`。 | 核心，保留 |
| `streamer_config.db` | VTuber 設定來源；依團體分成多個 `streamer_*` 表。 | **正式資料，不要隨意刪除** |
| `live_data.db` | 正式直播資料；保存 streamer、直播、快照、目前狀態與工作紀錄。 | **正式資料，不要隨意刪除** |
| `youtube_api_data.db` | WebSub + 官方 YouTube API 第二套管線的獨立資料庫。 | 執行後產生，不影響 `live_data.db` |
| `streamer_audience.db` | 目前啟用 streamer 的 YouTube 訂閱數與 Twitch 追隨數；提供 `audience_merge_export` 給網頁端依 `vtuber_id` 合併。 | 資料，可由 `src/build_streamer_audience_db.py` 重建 |
| `live_data.db.collect.lock` | 收集期間臨時產生，防止兩個 collector 同時寫入；正常結束會移除。 | 可重建；只有確認 PID 已不存在時才能清除殘留檔 |
| `node_modules/` | `npm install` 產生的 Node.js 套件。 | 可重建；需要時可刪除後執行 `npm install` |
| `__pycache__/`、`*.pyc` | Python 執行快取。 | 可重建，可安全清除 |
| `.git/` | Git 版本歷史與目前工作樹狀態。 | 不要移動或刪除 |
| `.agents/` | 開發工具使用的專案 metadata。 | 非執行核心；不確定工具用途前先保留 |

## `src/`：Python 與 Node.js 程式

### 收集主流程

| 檔案 | 用途 | 分類 |
| --- | --- | --- |
| `src/run_local_scheduler.py` | 本機排程器；處理固定間隔、單次模式、timeout、collection lock、即時報告與失敗工作收尾。 | 核心 |
| `src/collect_all.py` | 一輪完整工作入口；同步 streamer，依序執行 Twitch 與 YouTube collector。 | 核心 |
| `src/youtube_collector.py` | 偵測 YouTube 直播、更新直播主資料、目前狀態與觀看人數快照。 | 核心 |
| `src/youtube_live_ytjs.mjs` | 使用 `youtubei.js` 批次取得 YouTube 直播資訊，供 Python collector 呼叫。 | 核心 |
| `src/youtube_webhook_server.py` | 接收 YouTube WebSub 驗證與影片事件，不影響原 collector。 | 第二套驗證管線 |
| `src/youtube_websub_subscribe.py` | 訂閱／取消訂閱頻道並管理 WebSub lease。 | 第二套驗證管線 |
| `src/youtube_api_collector.py` | 使用官方 `videos.list` 批次確認候選影片與同接。 | 第二套驗證管線 |
| `src/run_youtube_api_scheduler.py` | 每 5 分鐘執行官方 API collector 的獨立 scheduler。 | 第二套驗證管線 |
| `src/compare_youtube_collectors.py` | 並排比較原 collector 與官方 API collector 結果。 | 驗證工具 |
| `src/youtube_websub_dashboard.py` | 管理 Quick Tunnel、webhook、訂閱、API scheduler 與比較的本機瀏覽器控制台。 | 第二套驗證管線 |
| `src/youtube_websub_settings.py` | 使用 Windows DPAPI 加解密控制台的本機密鑰設定。 | 第二套驗證管線 |
| `src/youtube_api_db.py` | 初始化第二套管線專用的 `youtube_api_data.db`。 | 第二套驗證管線 |
| `src/init_youtube_api_db.py` | 手動建立第二套管線資料庫並同步 streamer。 | 初始化工具 |
| `src/migrate_youtube_api_data.py` | 將先前誤放在舊資料庫的 WebSub/API 資料唯讀複製至新資料庫。 | 一次性 migration |
| `src/twitch_collector.py` | 使用 Twitch Helix API 查詢直播並寫入直播狀態與快照。 | 核心 |

### Streamer 設定管理

| 檔案 | 用途 | 分類 |
| --- | --- | --- |
| `src/streamer_form.py` | Tkinter 圖形表單；新增或更新 streamer、建立團體、自動抓 YouTube channel ID、測試重複 ID。 | 工具 |
| `src/add_streamer.py` | 命令列新增或更新單一 streamer。 | 工具 |
| `src/create_streamer_group.py` | 建立新的 `streamer_<group>` 設定表。 | 工具 |
| `src/init_streamer_config.py` | 初始化 `streamer_config.db` 與預設團體表。 | 核心／初始化 |
| `src/sync_streamers.py` | 將 `streamer_config.db` 的啟用資料同步到 `live_data.db` 的 `streamer` 表。 | 核心 |
| `src/list_streamers.py` | 在命令列列出所有啟用的 streamer 設定。 | 工具 |
| `src/backfill_youtube_channel_ids.py` | 為設定表中缺少 channel ID 的 YouTube URL 補抓 `UC...` ID。 | 維護工具 |
| `src/build_streamer_audience_db.py` | 由正式 streamer 清單與既存統計建立 `streamer_audience.db`，並透過 Twitch Helix API 補抓缺少的追隨數。 | 維護／匯出工具 |
| `src/fetch_audience_avatars.py` | 抓取 YouTube 頻道頭像 URL 並寫入 `streamer_audience.db`；預設只補空值，`--refresh` 可全部更新。 | 維護／匯出工具 |
| `src/streamer_tables.py` | 團體表名稱驗證、Streamer 資料模型與跨表讀取共用邏輯。 | 核心共用模組 |

### 資料庫初始化與 migration

| 檔案 | 用途 | 分類 |
| --- | --- | --- |
| `src/init_db.py` | 依 `sql_init/` 建立 `live_data.db` 核心表，並自動執行必要 migration。 | 核心／初始化 |
| `src/migrate_stream_titles.py` | 將快照與目前狀態的重複標題文字轉為 `title_id` mapping。 | 核心 migration，先保留 |
| `src/migrate_stream_categories.py` | 將重複分類文字轉為 `category_id` mapping，空分類維持空值。 | 核心 migration，先保留 |
| `src/migrate_stream_tags.py` | 將重複 tags JSON 轉為 `tags_id` mapping，空 tags 維持空值。 | 核心 migration，先保留 |
| `src/stream_titles.py` | 寫入時解析／重用 `title_id`；優先與目前直播狀態比較以減少搜尋。 | 核心共用模組 |
| `src/stream_categories.py` | 寫入時解析／重用 `category_id`。 | 核心共用模組 |
| `src/stream_tags.py` | 寫入時解析／重用 `tags_id`。 | 核心共用模組 |

### 共用與檢視工具

| 檔案 | 用途 | 分類 |
| --- | --- | --- |
| `src/youtube_utils.py` | YouTube channel ID 解析、yt-dlp 補抓與標準 channel URL 組合。 | 核心共用模組 |
| `src/twitch_utils.py` | 從 Twitch URL 驗證並解析 login 名稱。 | 核心共用模組 |
| `src/time_utils.py` | 統一使用 Asia/Taipei 時區與資料庫時間格式。 | 核心共用模組 |
| `src/working_log.py` | 建立、完成與標記失敗的 `working` 工作紀錄。 | 核心共用模組 |
| `src/list_working.py` | 文字模式查詢最近工作紀錄與錯誤。 | 工具 |
| `src/working_calendar.py` | 圖形化日曆檢視工作紀錄與錯誤詳情。 | 工具 |

## `sql_init/`：資料表定義

這些 SQL 由初始化程式讀取。即使正式 DB 已建立，也應保留以便建立新資料庫。

| 檔案 | 建立內容 |
| --- | --- |
| `001_streamer_template.sql` | `streamer_config.db` 的團體表範本；`GROUP_NAME` 需替換。 |
| `002_streamer.sql` | `live_data.db` 中同步後的統一 streamer 表。 |
| `009_stream_title.sql` | 唯一直播標題 mapping 表。 |
| `009_stream_category.sql` | 唯一非空直播分類 mapping 表。 |
| `009_stream_tags.sql` | 唯一非空 tags JSON mapping 表。 |
| `010_stream.sql` | 每一場實際直播的主資料。 |
| `011_stream_snapshot.sql` | 定期觀看人數快照，透過 ID 連到標題／分類／tags。 |
| `012_current_live_status.sql` | 每位 VTuber、每平台目前最新直播狀態。 |
| `013_working.sql` | 每次 collector 的執行結果、耗時與錯誤紀錄。 |

## `.github/`

| 檔案 | 用途 | 分類 |
| --- | --- | --- |
| `.github/workflows/collect.yml` | GitHub Actions 手動收集流程；排程目前註解停用，因為改由本機 scheduler 收集。 | 保留；除非確定永遠不使用 GitHub Actions |

## `backups/`：正式資料庫備份

| 檔案 | 備份時點 |
| --- | --- |
| `streamer_config_before_envision_import_20260715_233033.db` | 匯入 EnVision streamer 前。 |
| `live_data_before_title_normalization_20260715_234724.db` | title mapping migration 前。 |
| `live_data_before_category_normalization_20260716_001339.db` | category mapping migration 前。 |
| `live_data_before_tags_normalization_20260716_012608.db` | tags mapping migration 前。 |

這些檔案不參與日常執行。確認正式資料穩定後，可以壓縮或移到專案外的備份位置；不建議和暫存檔混在一起刪除。

## `import_previews/`：人工確認用匯入預覽

| 檔案 | 用途 | 分類 |
| --- | --- | --- |
| `google_sheet_streamer_preview.db` | Google Sheet 前兩筆測試資料；後來決定不採用該來源。 | 舊版／暫存，可刪或封存 |
| `taiwan_vtuber_50k_preview.db` | TaiwanVtuberData：YouTube > 50K 或 Twitch > 50K 的舊門檻預覽。 | 舊版／暫存，可刪或封存 |
| `taiwan_vtuber_yt20k_tw10k_preview.db` | TaiwanVtuberData：YouTube > 20K 或 Twitch > 10K 的目前預覽；含獨立訂閱數、group 與 group_summary。 | 目前整理中的資料，保留 |

預覽資料庫不會被 scheduler 讀取。只有人工確認並執行匯入後，內容才會進入正式 `streamer_config.db`。

## `legacy_prototypes/`：舊實驗程式

| 檔案 | 用途 | 分類 |
| --- | --- | --- |
| `legacy_prototypes/find_live_stream.py` | 早期用 yt-dlp 尋找單一 YouTube 頻道直播的原型。 | 舊版，可封存 |
| `legacy_prototypes/twitch_api_test.py` | 早期 Twitch Helix API 連線與直播查詢測試。 | 舊版，可封存 |
| `legacy_prototypes/data.db` | 舊版原型資料庫，部分正式設定曾由此匯入。 | 舊資料；確認無需追溯後再封存或刪除 |

## `tmp_ytjs_speed/`：效能測試資料

| 檔案 | 用途 | 分類 |
| --- | --- | --- |
| `rei_basic_raw.json` | YouTube.js 基本回應測試資料。 | 暫存 |
| `rei_raw.json` | YouTube.js 大型原始回應測試資料。 | 暫存，體積較大 |

這個目錄不參與正式 collector，可在不再進行 YouTube.js 效能分析時清除。

## 建議的整理順序

1. **先不要動**：`src/`、`sql_init/`、所有 `.bat`、`live_data.db`、`streamer_config.db`、相依套件設定。
2. **可先清理**：`tmp_ytjs_speed/`、Python cache；`node_modules/` 只有需要節省空間時再刪。
3. **可封存**：`legacy_prototypes/` 與較舊的 import preview。
4. **備份另存**：把 `backups/` 複製到專案外或雲端後，再決定是否保留專案內副本。
5. **最後才移動核心檔案**：如果要重新分目錄，必須同步修改 batch、Python import、SQL 路徑與 GitHub Actions，不能只移檔案。
