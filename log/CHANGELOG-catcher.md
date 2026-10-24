# 2026-09-29 目錄整理

- 依 sort.md 分類程式、資料庫、工具與文件，保留全部原檔。
- 更新預設路徑、操作入口與部署設定；未改變採集及統計規則。

# 更新日誌

本文件記錄各版本的重要功能、修正與資料結構變更。

版本編號採用 [Semantic Versioning](https://semver.org/lang/zh-TW/)：

- `MAJOR`：不相容的重大變更。
- `MINOR`：向下相容的新功能。
- `PATCH`：向下相容的錯誤修正。

## 尚未發布

### 新增

- 新增獨立的 YouTube WebSub webhook server。
- 新增 WebSub 頻道訂閱、驗證狀態與 lease 到期管理。
- 新增 YouTube Data API `videos.list` 50 支一批的候選影片 collector。
- 新增官方 API 專用候選、快照與目前直播狀態資料表。
- WebSub／官方 API 管線改用獨立的 `youtube_api_data.db`；比較時只讀取原本的 `live_data.db`。
- 新增獨立的每 5 分鐘官方 API scheduler。
- 新增原 collector 與官方 API collector 的結果比較工具。
- 新增 WebSub + 官方 API 本機與 production 設定文件。
- 新增 YouTube WebSub + 官方 API 本機瀏覽器控制台與雙擊啟動檔。
- 新增 Windows DPAPI 加密設定保存，避免每次啟動重複輸入密鑰。
- 本機瀏覽器控制台可自動啟動 Quick Tunnel、取得 callback URL、訂閱頻道、執行
  scheduler 及比較新舊結果。

### 變更

- 原本 YouTube.js／yt-dlp collector 維持原樣；新方法使用獨立程式與資料表。

### 修正

- 尚無。

## 1.1.0 - 2026-07-29

### 新增

- 新增 `YOUTUBE_COOKIE` 支援，可使用登入狀態查詢 YouTube。
- 新增 YouTube Cookie 設定與安全注意事項文件。
- 新增 YouTube 頻道 ID 稽核工具 `src/audit_youtube_channels.mjs`。
- 新增 YouTube 請求隨機延遲設定：
  - `YTJS_REQUEST_DELAY_MIN_MS`
  - `YTJS_REQUEST_DELAY_MAX_MS`
- 新增直播候選項目的除錯輸出選項 `YTJS_DEBUG_CANDIDATES`。
- `working` 資料表新增 `synced_streamers` 欄位。
- 資料庫初始化時會自動將舊版 `working.summary` 中的同步人數遷移至
  `synced_streamers`。

### 變更

- 將 `youtubei.js` 從 `15.0.0` 升級至 `17.2.0`。
- YouTube 單一頻道預設逾時由 15 秒調整為 10 秒。
- YouTube collector 現在會記住上一輪的直播狀態，遇到不確定結果時保留原狀。
- 改善 YouTube 直播徽章、觀看文字、待機室與解析節點的判斷。
- 暫時性的 `fetch failed` 會等待一小段時間後自動重試一次。
- scheduler 傳遞執行結果時會限制錯誤清單長度，避免程序間佇列負擔過大。
- `working` 執行紀錄改用明確欄位保存同步人數，不再保存完整 `summary` JSON。
- 更新 VTuber 設定資料與直播資料快照。
- Git 忽略 collector lock 檔案與 `.tmp_*` 臨時目錄。

### 修正

- 修正 YouTube 查詢發生錯誤時，可能將未知狀態誤判為離線的問題。
- 修正上一輪仍在直播、但本輪直播分頁暫時消失時被直接標記為離線的問題。
- 改善影片資訊需要登入或無法明確判斷直播狀態時的錯誤處理。
- 改善 scheduler timeout 與 stale job 清理後的工作紀錄。

## 1.0.0 - 2026-07-23

### 新增

- 第一個正式版本。
- 支援 YouTube 與 Twitch 直播狀態抓取。
- 支援直播標題、分類、標籤、觀看人數快照與目前直播狀態。
- 支援本機每 5 分鐘執行的 scheduler。
- 支援 VTuber 團體、頻道設定與 SQLite 資料庫管理。
- 支援工作執行紀錄與工作日曆檢視工具。
