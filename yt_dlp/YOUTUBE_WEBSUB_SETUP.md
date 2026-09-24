# YouTube WebSub + 官方 API 抓取設定

新管線寫入獨立的 `youtube_api_data.db`；原 collector 繼續使用
`live_data.db`。兩套可以同時執行，比較工具只會讀取舊資料庫。

若曾使用尚未分離資料庫的版本，可執行一次
`python src/migrate_youtube_api_data.py`。它只會從舊資料庫讀取並複製
WebSub/API 紀錄，不會刪除或改寫舊資料。

這是獨立於原本 YouTube.js／yt-dlp collector 的第二套驗證管線。

原本的程式與資料表維持不變；新管線只使用：

- `youtube_websub_*`
- `youtube_api_*`
- `working` 中的 `youtube_api_collector` 執行紀錄

因此兩套 collector 可以同時執行，再用比較工具檢查結果。

## 推薦：使用本機瀏覽器控制台

第一次準備好 YouTube API key 後，直接雙擊：

```text
open_youtube_websub_control.bat
```

它會啟動只監聽 `127.0.0.1:8790` 的本機控制台並自動開啟瀏覽器。控制台可以：

- 儲存 YouTube API key、webhook token、callback URL 和執行間隔。
- 自動產生 webhook token。
- Local 模式一鍵啟動 Cloudflare Quick Tunnel。
- 自動取得臨時 `trycloudflare.com` URL。
- 自動啟動 webhook server、訂閱所有頻道及官方 API scheduler。
- 手動執行一輪官方 API collector。
- 比較原 collector 與官方 API collector 的結果。
- 一次停止新管線，不影響原本的 scheduler。

第一次使用：

1. 輸入 YouTube API key。
2. 按「產生 token」。
3. 執行模式選擇 `quick_tunnel`。
4. 按「儲存設定」。
5. 按「一鍵啟動整套」。

Quick Tunnel URL 會由控制台自動取得，不需要手動複製。因為每次 Quick Tunnel
的 domain 可能不同，控制台會在取得新 URL 後自動重新訂閱所有頻道。

### 設定安全性

設定保存在：

```text
.local/youtube_websub_control.json
```

- `.local/` 已加入 `.gitignore`，不會上傳 GitHub。
- API key 和 webhook token 使用 Windows DPAPI 加密。
- 只有目前的 Windows 使用者帳號可以解密。
- callback URL、間隔與模式不是密鑰，因此以一般 JSON 保存。
- 控制台的 process log 不會顯示 API key 或 webhook token。

如果換 Windows 帳號或把設定檔搬到另一台電腦，DPAPI 將無法解密，需要重新輸入。

### cloudflared

Local 一鍵模式需要先安裝一次 `cloudflared`。可在 PowerShell 執行：

```powershell
winget install --id Cloudflare.cloudflared
```

安裝後關閉並重新開啟控制台。如果使用 production 固定 HTTPS callback，則可以
選擇 `fixed` 模式並直接填入完整 URL。

## 運作流程

```text
YouTube 頻道新增或更新影片
            ↓
Google WebSub Hub 呼叫公開 webhook
            ↓
保存 channelId、videoId 為候選影片
            ↓
每 5 分鐘將最多 50 個 videoId 合併成一次 videos.list
            ↓
保存官方 API 的直播狀態、標題、時間與 concurrentViewers
            ↓
和原本 YouTube.js collector 結果比較
```

WebSub 官方保證的通知是影片上傳，以及影片標題或說明更新。通知本身不是
「直播開始」事件，因此程式會把通知中的影片當成候選，再由官方
`videos.list` 確認它是 `upcoming`、`live`、`completed` 或一般影片。

## 事前準備

### 1. 建立 YouTube Data API Key

在 Google Cloud Console：

1. 建立或選擇 Project。
2. 啟用 YouTube Data API v3。
3. 建立 API key。
4. 建議將 key 限制為只能使用 YouTube Data API v3。

在 PowerShell 設定：

```powershell
$env:YOUTUBE_API_KEY = Read-Host "Paste YouTube API key"
```

不要把 API key 寫進 `.py`、`.bat`、README 或 Git。

### 2. 初始化資料表

```powershell
python src/init_youtube_api_db.py
```

這會新增 WebSub/API 專用資料表，不會刪除或改寫原 collector 的資料。

## Local dev：Cloudflare Quick Tunnel

以下是不用本機瀏覽器控制台時的手動操作方式。

### 1. 產生 webhook token

每次測試可使用一組隨機 token：

```powershell
$env:YOUTUBE_WEBHOOK_TOKEN = [Convert]::ToHexString(
    [Security.Cryptography.RandomNumberGenerator]::GetBytes(32)
)
```

這個 token 會附在 callback URL，避免公開 endpoint 接受任意請求。

### 2. 啟動 Quick Tunnel

先讓 tunnel 指向 webhook server 的本機 port：

```powershell
cloudflared tunnel --url http://127.0.0.1:8787
```

Cloudflare 會顯示類似：

```text
https://random-name.trycloudflare.com
```

設定完整 callback URL：

```powershell
$env:YOUTUBE_WEBHOOK_CALLBACK_URL =
    "https://random-name.trycloudflare.com/webhooks/youtube"
```

Quick Tunnel 重啟後網址通常會改變。網址改變時必須重新執行訂閱。

### 3. 啟動 webhook server

另開一個 PowerShell，重新設定同一組 callback URL 和 token，再執行：

```powershell
python src/youtube_webhook_server.py
```

預設只監聽：

```text
http://127.0.0.1:8787/webhooks/youtube
```

外部 HTTPS 由 cloudflared 提供。

### 4. 訂閱頻道

建議先 dry run：

```powershell
python src/youtube_websub_subscribe.py --dry-run
```

只測試單一頻道：

```powershell
python src/youtube_websub_subscribe.py --channel-id "UC..."
```

訂閱所有啟用且已有 `youtube_channel_id` 的頻道：

```powershell
python src/youtube_websub_subscribe.py
```

Google Hub 接受請求後，會用 `GET` 驗證 callback。Webhook server 會原樣回傳
`hub.challenge`，並將驗證狀態寫入 `youtube_websub_subscription`。

檢查結果：

```powershell
python -c "import sqlite3; c=sqlite3.connect('youtube_api_data.db'); print(c.execute('SELECT status, count(*) FROM youtube_websub_subscription GROUP BY status').fetchall())"
```

### 5. 執行官方 API collector

手動跑一輪：

```powershell
python src/youtube_api_collector.py
```

每 5 分鐘執行：

```powershell
python src/run_youtube_api_scheduler.py --run-immediately
```

這個 scheduler 只執行新的官方 API collector，不會呼叫或停用原本的
`run_local_scheduler.py`。兩個 scheduler 可以同時運行。

### 6. 比較兩套結果

列出所有頻道：

```powershell
python src/compare_youtube_collectors.py
```

只列出直播狀態不同的頻道：

```powershell
python src/compare_youtube_collectors.py --differences-only
```

`NO_EVENT` 代表該頻道尚未收到 WebSub 候選影片，不能視為官方 API 判定離線。

## 訂閱續期

WebSub 訂閱有期限。Webhook 驗證時會保存 `hub.lease_seconds` 和
`expires_at`。建議每天執行一次：

```powershell
python src/youtube_websub_subscribe.py --due-within-hours 24
```

它只會重新訂閱尚未驗證、缺少到期時間，或 24 小時內即將到期的頻道。

## Production：Reverse proxy

正式環境可使用固定平台網址或自己的 domain：

```text
https://example.com/webhooks/youtube
        ↓
Nginx／Caddy／Cloudflare reverse proxy
        ↓
http://127.0.0.1:8787/webhooks/youtube
```

Reverse proxy 必須：

- 允許外部 `GET` 和 `POST`。
- 保留 query string，否則 webhook token 和 `hub.*` 驗證參數會消失。
- 允許 `application/atom+xml` request body。
- 不要在此 path 套用登入頁、CSRF 或會修改 response body 的 middleware。
- 使用固定 HTTPS URL；callback URL 改變後要重新訂閱。

Webhook 收到事件後只做 XML 驗證與 SQLite 寫入，會快速回覆 `204`。官方 API
查詢由另一個 scheduler 執行，不會阻塞 webhook response。

## API 額度

`videos.list` 每次呼叫消耗 1 unit，每次最多放 50 個 video ID。

若每 5 分鐘固定檢查 1,500 個候選影片：

```text
1,500 ÷ 50 = 30 calls/輪
30 × 288 輪/天 = 8,640 units/天
```

程式預設 `--limit 1500`，保留部分額度供重試和其他操作使用。實際上一般影片
第一次確認不是直播後會停止輪詢；已結束直播也會停用，因此通常遠低於這個數字。

## 已知限制

- WebSub 官方只保證影片上傳、標題更新和說明更新通知，不保證每次直播狀態切換
  都發送事件。
- 頻道建立待機室時通常可先取得 video ID，但仍必須由 `videos.list` 確認狀態。
- 私人、刪除或 API 無法取得的影片會標記為 `unavailable` 或 `deleted`。
- `concurrentViewers` 可能因目前沒有觀眾或頻道隱藏觀看數而缺少，資料表允許空值。
- 目前新管線刻意不寫入原本的直播資料表；驗證完成前，以
  `youtube_api_current_status` 和 `youtube_api_snapshot` 為準。

## 主要資料表

| 資料表 | 用途 |
| --- | --- |
| `youtube_websub_subscription` | 訂閱狀態、lease 與到期時間 |
| `youtube_websub_event` | 原始 WebSub 影片事件 |
| `youtube_api_candidate` | 等待或持續檢查的候選影片 |
| `youtube_api_snapshot` | 官方 API 每次查詢結果 |
| `youtube_api_current_status` | 官方 API 管線目前判斷的直播狀態 |
