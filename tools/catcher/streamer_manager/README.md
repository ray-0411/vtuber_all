# VTuber 名單管理

用表單新增或修改 VTuber、平台連結與相關設定。雙擊 `open_streamer_form.bat` 啟動；也可以從專案根目錄執行：

```powershell
python tools/catcher/streamer_manager/streamer_form.py
```

表單會更新 `database/main/streamer_config.db`，並同步名單至 `database/main/live_data.db`。程式使用 `catcher/src/` 的共用名單與資料庫模組，請從專案目錄執行，不要單獨搬走此資料夾。
