# Codex 遷移交接附錄：目前狀態與未完成工作

更新日期：2026-09-28（Asia/Taipei）

本文件是 repository 根目錄 `PROJECT_MIGRATION_HANDOFF.md` 的補充。下一個
Codex 應先讀根目錄主文件，再讀本附錄；不要以本附錄取代主文件。

## 1. 目前 repository 狀態

- Git 根目錄目前是上一層 `api_version/`，不是本 `live_dashboard/` 目錄。
- 最新已提交 commit：`fa6d50b Adapt collection and Pages workflows for monorepo`。
- 目前已整合為單一 repository：
  - `yt_dlp/`：採集器及正式 SQLite 資料。
  - `live_dashboard/`：網站、資料整合工具、Supabase migration/RPC。
- 根目錄 `.github/workflows/` 是唯一 workflow 位置。
- 根目錄及 `yt_dlp/` 目前各有一份尚未追蹤的
  `PROJECT_MIGRATION_HANDOFF.md`，內容相同。整理時應只保留根目錄版本，避免日後
  兩份文件分岔。
- `yt_dlp/live_data.db` 目前有未提交修改。它是正式持續寫入資料，不可擅自還原、
  覆寫或加入 commit。
- `.migration-backup/`、`.migration-work/` 是本機遷移資料，不可提交。

接手後第一個動作必須是執行 `git status --short`，重新確認上述狀態；不可假設本
文件記錄的 dirty files 仍完全相同。

## 2. 最近完成的 Dashboard 功能

- Dashboard 最後一筆搬移前的功能 commit 是
  `44e2c78 Add group filter to rankings`。
- 排行榜提供：
  - 排序項目：平均觀眾數、觀眾小時。
  - 平台：綜合、YouTube、Twitch；綜合取兩平台較高者。
  - 時間：近 1、3、6 個月、近 1 年、全部。
  - 「更多」中的 Group 篩選；預設「全部人」，即不限制 Group。
- 排行榜 Group 篩選目前在前端對完整 RPC 結果篩選，篩選後會從第 1 名重新編號；
  尚未增加 RPC 的 Group 參數。
- 左側 Rankings 項目目前是白底黑字，不使用綠色特殊底色。
- 所有 Dashboard 頁面的頂部皆顯示：
  - 最近資料更新時間。
  - 實際部署的短 commit 版本；可連到 GitHub commit。
- Pages workflow 會在部署 artifact 中產生 `static/build-version.js`；repository 內的
  fallback 值為 `local`。
- 公開網址：<https://ray-0411.github.io/vtuber_website/>。

## 3. 不可意外改變的資料規則

- 所有畫面時間統一轉為 Asia/Taipei（UTC+8），格式為
  `YYYY-MM-DD HH:mm:ss`，畫面不另寫時區文字。
- 計算平均觀眾時，單場直播 `snapshot_count <= 3` 不納入平均。
- 首頁單場直播排名至少需要 5 筆快照。
- YouTube 缺少開始時間時，以第一筆 snapshot 時間作為分析開始時間。
- 觀眾小時依選取期間計算；Group 列表顯示總和，成員詳細頁另列 YouTube/Twitch。
- Group 是否公開獨立顯示由 `group_settings.display_order` 決定：
  - 有數字排序者獨立顯示。
  - 沒有排序的來源 Group 在網站查詢層歸入 `other`。
  - 原始資料庫仍保留真實 Group 名稱，不可為此直接改寫來源資料。
- `group_settings` 是人工可調設定；Supabase 上傳不得 TRUNCATE 或覆寫既有排序。
- 公開瀏覽器只能呼叫 reviewed read-only RPC；不可直接開放 raw table。

## 4. 下一個尚未實作的需求：性別

使用者接下來想在排行榜「更多」中加入性別篩選。這項功能尚未實作，也尚未決定
最終列舉值。

目前建議方向：

1. 在人工維護來源 `streamer_config.db` 的各 `streamer_<group>` 表加入可空的
   `gender TEXT`。
2. `src/streamer_tables.py`、初始化 SQL、人員表單、CLI 新增工具及
   `src/sync_streamers.py` 都要保留／同步該欄位。
3. `live_data.db.streamer`、發布用 merged DB、Supabase `dashboard.streamer` 及同步
   manifest/COPY 欄位都要加入 `gender`。
4. 成員排行榜 materialized view/RPC 必須回傳 `gender`，前端才能可靠篩選。
5. 排行榜「更多」加入性別選單，預設「全部」，即不篩選。
6. migration 必須相容既有資料；舊 row 的 `gender` 應為 NULL，不可要求一次補完。

先前提出、但尚待使用者確認的內部代碼為：

```text
female
male
non_binary
other
NULL（未設定）
```

曾提議前端顯示「全部、女性、男性、其他、未設定」，但使用者尚未回答是否接受。
下一個 Agent 不應自行假定分類，而應先向使用者確認；也要確認是否需要
`non_binary` 單獨顯示，或併入「其他」。內部建議使用穩定英文代碼，畫面再翻譯。

## 5. 實作性別前要追蹤的完整路徑

不要只改 Dashboard 的 `streamer` 表。至少搜尋並檢查：

```text
yt_dlp/sql_init/
yt_dlp/src/streamer_tables.py
yt_dlp/src/init_streamer_config.py
yt_dlp/src/create_streamer_group.py
yt_dlp/src/add_streamer.py
yt_dlp/src/streamer_form.py
yt_dlp/src/sync_streamers.py
yt_dlp/collector_supabase_tool/scripts/
live_dashboard/scripts/
live_dashboard/supabase/migrations/
live_dashboard/app.py
live_dashboard/static/api-client.js
live_dashboard/static/rankings.js
```

此外目前存在多份相似的 publish/merge 工具。先依主交接文件找出實際入口與最新版，
選定 canonical source 後再改；不可只改其中一份而讓正式上傳仍使用舊 schema。

## 6. 使用者既定 Git 習慣

- 一般功能完成後：更新對應 CHANGELOG、commit、push `main`。
- 不要自動建立 tag；只有使用者明確說要版本／tag 時才建立。
- 不提交 DB、cookie、私密 env、key、備份、lock 或產生資料。
- 已追蹤但正在被正式流程更新的 DB，修改前先確認用途，不可自行回復。
- 目錄大搬移期間，應先由使用者確認分階段計畫與 rollback，再進行大量 rename。

## 7. 給新 Codex 的最短啟動提示

在新資料夾的 Codex 對話中貼上：

```text
請先不要修改檔案，也不要啟動採集、排程、Supabase 上傳或部署。

請完整閱讀 AGENTS.md、PROJECT_MIGRATION_HANDOFF.md、
live_dashboard/CODEX_HANDOFF_ADDENDUM.md，以及 yt_dlp 與 live_dashboard 各自的
README.md、CHANGELOG.md。接著執行 git status 並列出實際目錄，對照文件確認
Git root、正式 DB、跨目錄路徑、重複的 Supabase 工具和目前未提交變更。

先回報你理解的架構、不可修改或提交的資料、建議的新目錄樹、分階段搬移與
rollback 計畫；等我確認後再修改。不得因驗證啟動長時間採集或連線執行正式上傳。
目前下一個功能是性別欄位與排行榜性別篩選，但分類代碼尚未由我確認，不要先實作。
```

## 8. 空資料夾如何交接

新 Codex 只能讀取它所連接的 workspace，不能自動看到本對話或舊資料夾。因此：

1. 最推薦先把完整 repository `git clone` 到新資料夾，保留 Git 歷史。
2. 將根目錄未追蹤的 `PROJECT_MIGRATION_HANDOFF.md` 與本附錄一起複製過去。
3. 確認新根目錄有 `AGENTS.md`。
4. 正式 `.db`、`.env.supabase.local`、cookie 等不要透過 Git；停止相關程序後另行
   安全複製，且先保留原始備份。
5. 在新 Codex 對話貼上上一節提示，讓它先做唯讀盤點。

如果只把交接文件放進空資料夾而沒有原始碼，Codex只能協助規劃，無法驗證路徑或
實際重構。完整 clone 加上 Git 外部的 runtime data，是最可靠的交接方式。
