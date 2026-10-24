# 2026-09-29 目錄搬移對照

| 原位置 | 新位置 |
| --- | --- |
| yt_dlp/src、sql_init、tests、Node/Python 依賴 | catcher/ 下相同目錄 |
| yt_dlp/*.bat | tools/catcher/ |
| yt_dlp/src/list_working.py、working_calendar.py | tools/catcher/ |
| live_dashboard/app.py、static、supabase | website/ 下相同目錄 |
| live_dashboard/*.bat、scripts | tools/website/ |
| yt_dlp/collector_supabase_tool | tools/publish/ |
| live_dashboard/collector_supabase_tool | other/archive/dashboard-publish-tool/ |
| live_dashboard/update_sql_use | other/archive/update_sql_use/ |
| yt_dlp/*.db | database/main/ |
| yt_dlp/collector_supabase_tool/data | database/published/ |
| live_dashboard/data | database/website/ |
| yt_dlp/import_previews | database/previews/ |
| yt_dlp/backups、db_backup | database/backups/ 各來源子目錄 |
| 各專案 CHANGELOG.md | log/catcher/、log/website/ |
| 設定、檔案指南與交接文件 | other/docs/ 各來源子目錄 |
| yt_dlp/.local、cookie | other/local/catcher/、other/local/cookie/ |
| 正式工具、網站的 .env.supabase.local | other/local/publish/、other/local/website/ |
| .migration-backup、.migration-work | other/archive/git-migration-backup、git-migration-work |
| 空 .agents/.github、舊 prototype/測試套件 | other/archive/ 各來源子目錄 |
| sql_temp | other/archive/sql_temp/ |

舊工具內的 DB 另集中至 `database/archive/`，保留來源路徑。JSON 報告與排程狀態移至 `log/data/`；新發布狀態寫入 `log/publish/`，首次執行可能重新發布一次。

`tools/website/scripts` 中的 merge、analytics、group settings、sync 入口轉呼叫 `tools/publish/scripts`，原版程式保存在修改前副本。網站側保留自己的 DB 預設來源；Supabase 使用正式發布設定，所有上傳保留遠端 Group 排序。

## 檔案保全

本機 `other/reorganization/inventory.json` 保存整理前檔案 SHA-256；`moves.json` 保存逐步搬移映射；`before-edits/` 保存修改前原文。
這些檔案可能包含本機資訊，不進 Git。所有原檔均保留，沒有刪除或覆蓋同名資料庫。
原根目錄 AGENTS/README 的歷史規則已由本次使用者明確指定的 sort.md 配置取代。

不要直接重新執行一次性搬移腳本。回復時先停止所有排程，依映射逆序搬回，並對照修改前副本；不可覆蓋搬移後新增的資料。
