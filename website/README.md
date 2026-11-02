> 目錄已於 2026-09-29 整理。下文保留原說明，舊路徑請對照根目錄 README 與 other/docs/LAYOUT.md；操作入口在 tools/。

# VTuber Live Observatory

台灣 VTuber 的 YouTube、Twitch 直播資料觀測網站，提供即時直播、觀看排行、
Group 與成員分析、直播月曆及單場觀看人數變化。

## 公開網站

**[開啟 VTuber Live Observatory](https://ray0411.win)**

網站部署於 GitHub Pages，資料由你電腦上執行的唯讀 API 提供。網站不需要登入，
使用手機或電腦瀏覽器皆可開啟；電腦或網路中斷時，資料查詢會暫時無法使用。

## 網站功能

- 上週 YouTube、Twitch 平均／最高觀看人數 Top 10。
- 上個完整月份的平均觀看人數排行。
- 顯示目前正在直播的頻道、頭像、標題與觀看人數。
- 依 Group 查看成員、直播次數及平台平均觀看人數。
- 查看個別成員的直播統計、常見分類、活動時段與近期直播。
- 依月份查看開台月曆與直播紀錄。
- 點選直播紀錄，以彈出視窗查看該場直播的觀看人數快照曲線。
- 從左側導覽開啟「關於網站」，查看網站與資料說明。

「關於網站」的公開文字位於 `static/about.html`；搜尋 `about-card` 即可修改各段內容。

統計平均值時，快照數不超過 3 筆的直播不納入平均；週排行則要求至少 5 筆
快照，避免觀測時間太短造成排名失真。

## 資料與架構

```text
抓取器 SQLite
   ↓ 合併及建立分析快取
本機發布 SQLite
   ↓ 本機唯讀 API（Cloudflare Tunnel HTTPS）
GitHub Pages 靜態網站
```

- API 只開放網站使用的 GET 查詢，SQLite 以唯讀方式開啟。
- API 預設只接受正式網站與本機預覽的瀏覽器來源。
- 不公開 SQLite 檔案，也不開放資料庫連接埠或寫入 API。
- 本機資料庫不提交到 Git。

## 維護資料

使用 `tools/catcher/.main_catcher.bat` 執行本機採集排程時，每輪抓取結束會自動更新網站資料庫：

1. 採集器寫入 `database/main/live_data.db`。
2. 排程以 SQLite 備份建立具版本名稱的 API 快照，合併 `streamer_audience.db`、保留 Group 設定並重建分析快取。
3. 兩個檔案都完成後才更新 `database/published/current_snapshot.json`；API 每次查詢都依此指標讀取同一版本。
4. 發布資料夾最多保留最近兩組快照；舊檔若仍被 API 使用，會延後到後續發布再清理。

若採集器是用其他方式執行，或只想手動更新網站副本，可雙擊
`tools/publish/update_local_dashboard.bat`。此工具不會上傳 Supabase。

若仍需使用舊的 Supabase 同步工具，可分開執行：

```powershell
refresh_merged_data.bat
upload_to_supabase.bat
```

Supabase 同步使用 Git 忽略的 `.env.supabase.local`；切換本機 API 後，網站查詢不依賴這個同步。

```dotenv
SUPABASE_DB_URL=postgresql://...
```

此連線字串包含資料庫密碼，不可上傳或分享。

## 啟動本機 API

需要 Python 3，並先準備：

- `database/published/merged_live_data.db`
- `database/published/merged_analytics_cache.db`

啟動方式：

```powershell
tools/website/.start_local_api.bat
```

或在 PowerShell 執行 `python website/app.py`。本機預覽可開啟 <http://127.0.0.1:8000>。
API 預設只綁定本機回環位址；外網使用時，
應以 Cloudflare Tunnel 將公開 HTTPS 網址導向 `http://127.0.0.1:8000`，不要把 API
改綁到所有網路介面，也不要在路由器公開 SQLite 或 SQL 連接埠。

本專案預計以 `ray0411.win` 提供網站，並以 `api.ray0411.win` 提供 API。Cloudflare
Tunnel 與 GitHub Pages DNS 設定完成後，電腦需保持開機、
連網且不進入睡眠；否則公開網站會暫時無法讀取資料。

## 主要目錄

```text
static/                       GitHub Pages 網頁與前端程式
supabase/migrations/          PostgreSQL schema、RLS 與唯讀 RPC
scripts/                      合併、分析、同步與驗證工具
collector_supabase_tool/      可搬至抓取器端的一鍵更新工具
.github/workflows/pages.yml   GitHub Pages 自動部署
```

## 版本紀錄

版本更新內容請參閱 [CHANGELOG.md](../log/website/CHANGELOG.md)。
