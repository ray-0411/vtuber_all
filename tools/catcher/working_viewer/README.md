# 採集工作紀錄檢視

此工具以文字列表或日曆檢視採集工作結果和錯誤；兩種介面都只讀取 `database/main/live_data.db`。

- 雙擊 `list_working.bat` 查看最近 30 筆紀錄；可附加 `--errors`、`--job` 等篩選參數。
- 雙擊 `working_calendar.bat` 開啟日曆，查看每天及每輪採集的狀態。

也可以從專案根目錄執行：

```powershell
python tools/catcher/working_viewer/list_working.py --limit 30
python tools/catcher/working_viewer/working_calendar.py
```

工具會從 `catcher/src/` 載入共用資料庫路徑設定，請保留整個專案目錄結構。
