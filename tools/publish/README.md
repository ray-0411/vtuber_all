> 2026-10-03：舊直播歷史已併入 `database/main/live_data.db`。`database/website/data.db` 和 `legacy_live_data.db` 保留為來源副本，不再參與日常發布。`.supabase_update.bat` 與 `update_and_upload.bat` 都從目前的 `live_data.db` 和 `streamer_audience.db` 建立發布副本。舊路徑請對照[目錄表](../../other/docs/LAYOUT.md)。

# 抓取器資料合併與 Supabase 上傳工具

發布工具位於 `tools/publish/`；資料庫來源和產物集中在 `database/`。

## 預設放置方式

```text
database/
├─ main/
│  ├─ live_data.db
│  └─ streamer_audience.db
└─ published/
   ├─ merged_live_data.db
   └─ merged_analytics_cache.db

tools/publish/
├─ update_and_upload.bat
├─ update_one_time.bat
├─ .supabase_update.bat
└─ scripts/
```

如果來源資料庫不在 `database/main/`，請修改 `settings.bat` 的
`SOURCE_DIR`。可以使用完整路徑，例如：

```bat
set "SOURCE_DIR=C:\Users\Ray\Desktop\collector"
```

## 第一次使用

1. 執行 `setup.bat` 安裝 PostgreSQL 上傳套件。
2. 確認 `.env.supabase.local` 存在。
3. 確認 `settings.bat` 指向正確的來源資料庫資料夾。

## 更新與發布

抓取器完成資料更新後，雙擊 `update_and_upload.bat`。它會依序：

1. 從目前已包含舊歷史的 `live_data.db` 和 `streamer_audience.db` 建立發布副本。
2. 更新 Group 排序資料。
3. 重建分析快取。
4. 在單一交易中上傳 Supabase、核對所有資料表筆數，並重建全站排行榜快取。

看到 `Update and upload completed` 才表示全部完成。公開網站不需要重新部署，
重新整理後就會讀到 Supabase 的新資料。

排行榜快取只會在上傳成功的最後一步更新。原本保留 Supabase Group 排序設定的
機制不會改變；若上傳或快取重建失敗，整次交易都不會提交。

`.supabase_update.bat` 會定期從目前資料庫建立發布副本並上傳。

`update_one_time.bat` 只會上傳 `database/published/` 中已建立的資料，不會重新合併或建立發布副本。

## 安全注意事項

`.env.supabase.local` 含有 Supabase 資料庫密碼。此工具資料夾可以在自己的電腦間
搬移，但不可上傳 GitHub、雲端公開連結或傳給其他人。若不小心外洩，請立刻在
Supabase 重設資料庫密碼。

上傳會取代 Supabase 中由 dashboard 管理的資料表，但使用交易處理；若中途失敗，
未完成的變更不會提交。
