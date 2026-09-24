# YouTube Cookie 抓取與重新啟動指南

這份文件用於電腦重開機、PowerShell 關閉，或 Cookie 失效後，重新恢復 YouTube 直播抓取。

Cookie 不會寫入程式碼、SQLite 或 Git。它只保存在目前的 PowerShell 環境變數中，因此關閉該視窗後就要重新設定。

## 一、準備專用 Google 帳號

建議使用非主要用途的 Google 帳號：

- 帳號必須能正常登入 YouTube。
- 若需要讀取年齡限制的直播，帳號本身也必須完成 Google 的年齡驗證。
- 不要把密碼或 Cookie 貼到聊天、程式碼、資料庫或 GitHub。

## 二、從瀏覽器取得 Cookie

以下以 Chrome 或 Edge 為例：

1. 開啟無痕或 InPrivate 視窗。
2. 登入準備給抓取器使用的 Google 帳號。
3. 開啟 `https://www.youtube.com/`。
4. 按 `F12` 開啟開發人員工具。
5. 切換到 `Network`（網路）分頁。
6. 重新整理 YouTube 頁面。
7. 在請求清單中點選一個送往 `youtube.com` 的請求，例如 `browse`。
8. 在右側切換到 `Headers`。
9. 找到 `Request Headers` 裡的 `cookie`。
10. 複製 `cookie:` 後面的完整內容，只複製值，不要包含 `cookie:` 這個名稱。

如果找不到：

- 確認 Network 左上角的錄製圓點是紅色。
- 清除 Network 的搜尋條件。
- 重新整理 YouTube。
- 點選 `youtube.com`、`browse` 或 `youtubei/v1/browse` 的請求。
- 在 Headers 頁面搜尋 `cookie`。

## 三、開啟專案 PowerShell

進入專案資料夾：

```powershell
cd "C:\Users\Ray\Desktop\coding\summer_project\vtuber\api_version\yt_dlp"
```

如果 Twitch 金鑰尚未設定，也要在同一個 PowerShell 設定：

```powershell
$env:TWITCH_CLIENT_ID = "你的 Twitch Client ID"
$env:TWITCH_CLIENT_SECRET = "你的 Twitch Client Secret"
```

## 四、設定 YouTube Cookie

### 方法 A：讀取插件匯出的 cookies.txt（建議）

專案預設會讀取：

```text
cookie/www.youtube.com_cookies.txt
```

把插件匯出的 Netscape 格式檔案放在這個位置，就不需要設定環境變數。若要使用其他位置，再指定完整路徑：

```powershell
$env:YOUTUBE_COOKIES_FILE = "C:\Users\Ray\Downloads\cookies.txt"
```

程式也接受插件匯出的 JSON Cookie 陣列，或只包含完整 Cookie header 的文字檔。設定檔案路徑後，不需要再設定 `YOUTUBE_COOKIE`。如果兩者都有設定，檔案優先。

請勿把 Cookie 檔案提交到 Git；專案已忽略常見的 `cookies.txt` 檔名。

### 方法 B：直接貼上 Cookie header

使用 `Read-Host`，避免 Cookie 直接出現在指令歷史中：

```powershell
$env:YOUTUBE_COOKIE = Read-Host "Paste YouTube Cookie"
```

出現提示後，貼上第二步複製的完整 Cookie 值，再按 Enter。

只檢查長度，不要把內容輸出到畫面：

```powershell
$env:YOUTUBE_COOKIE.Length
```

結果應該是大於 `0` 的數字。不要使用 `$env:YOUTUBE_COOKIE` 直接顯示內容。

## 五、設定抓取頻率

目前程式的預設值已經是：

- 4 個並行 worker。
- 每個頻道開始查詢前隨機等待 200～600ms。
- 單一頻道最多等待 10 秒。
- `fetch failed` 會等待約 0.8～1.6 秒後重試一次。
- 整輪 scheduler 最多執行 240 秒。

使用預設值時不必另外設定。若想明確指定：

```powershell
$env:YTJS_CONCURRENCY = "4"
$env:YTJS_REQUEST_DELAY_MIN_MS = "200"
$env:YTJS_REQUEST_DELAY_MAX_MS = "600"
$env:YTJS_CHANNEL_TIMEOUT_MS = "10000"
```

269 個頻道的隨機延遲平均約增加 27 秒，設計目標仍是在五分鐘內完成一輪。

若再次出現大量「登入帳戶以確認你不是機器人」，可以提高延遲，例如：

```powershell
$env:YTJS_REQUEST_DELAY_MIN_MS = "400"
$env:YTJS_REQUEST_DELAY_MAX_MS = "900"
```

不要同時執行 scheduler 和單次抓取。

## 六、先執行單次測試

在設定 Cookie 的同一個 PowerShell 執行：

```powershell
python src/run_local_scheduler.py --once
```

查看最近的 YouTube 工作紀錄：

```powershell
python src/list_working.py --job youtube_collector --limit 3 --errors
```

正常時不應大量出現：

- `LOGIN_REQUIRED`
- `登入帳戶以確認你不是機器人`
- `429 Too Many Requests`

少量 `fetch failed` 或單頻道逾時可能只是暫時性網路問題。錯誤頻道會保留上次狀態，不會直接被判定為離線。

## 七、啟動 scheduler

單次測試正常後，在同一個 PowerShell 執行：

```powershell
.\start_local_scheduler.bat
```

停止 scheduler：

```text
Ctrl+C
```

修改 Cookie 或頻率設定後，必須停止並重新啟動 scheduler，新設定才會生效。

## 八、下次關閉後的快速恢復步驟

每次重新開啟 PowerShell，依序執行：

```powershell
cd "C:\Users\Ray\Desktop\coding\summer_project\vtuber\api_version\yt_dlp"
$env:TWITCH_CLIENT_ID = "你的 Twitch Client ID"
$env:TWITCH_CLIENT_SECRET = "你的 Twitch Client Secret"
$env:YOUTUBE_COOKIE = Read-Host "Paste YouTube Cookie"
python src/run_local_scheduler.py --once
.\start_local_scheduler.bat
```

若原本的 Cookie 已失效，就先依照第二節從瀏覽器重新取得。

## 九、常見錯誤

### 登入帳戶以確認你不是機器人

可能原因：

- Cookie 沒有設定到啟動 scheduler 的同一個 PowerShell。
- PowerShell 關閉後，環境變數已消失。
- Cookie 已過期或帳號被登出。
- IP 或請求頻率觸發 YouTube 風控。

處理方式：

1. 停止 scheduler。
2. 用瀏覽器確認帳號仍可正常使用 YouTube。
3. 重新複製 Cookie 並設定 `YOUTUBE_COOKIE`。
4. 等待一段時間後先執行單次測試。
5. 必要時提高隨機延遲。

### 請登入帳戶以確認你已滿限制年齡

代表該影片有年齡限制。請先確認同一個瀏覽器帳號能直接觀看；若瀏覽器也要求驗證，就必須先完成帳號的年齡驗證。

歷史影片即使有年齡限制，現在會被略過，不會影響離線判斷。只有看起來正在直播的受限影片才會保留為未知狀態。

### 429 Too Many Requests

通常是 IP 或頻率限制。Cookie 不一定有用：

1. 立即停止 scheduler。
2. 不要連續手動重試。
3. 等待數十分鐘至數小時。
4. 恢復後提高隨機延遲。

### Cookie 是否真的有被讀取

開啟進度輸出時，helper 只會顯示：

```text
[youtube] authentication=cookie
```

它不會輸出 Cookie 內容。如果顯示 `authentication=anonymous`，代表啟動程式的環境中沒有 `YOUTUBE_COOKIE`。

## 十、安全提醒

- 不要把 Cookie 寫進 `.bat`、README、SQLite 或任何會進 Git 的檔案。
- 不要截圖或分享完整 Request Headers。
- 不要使用主要 Google 帳號。
- Cookie 洩漏時，立刻登出該 Google 帳號的工作階段並重新登入。
- Git 已忽略 `.env`，但目前流程不需要建立 `.env`；使用 PowerShell 環境變數即可。
