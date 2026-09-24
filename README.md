# VTuber 採集與直播網站

本專案統一管理採集器與網站，保留兩個原始專案的 Git 歷史。

| 目錄 | 用途 | 說明 |
| --- | --- | --- |
| `yt_dlp/` | YouTube / Twitch 採集器與本機管理工具 | [採集器 README](yt_dlp/README.md) |
| `live_dashboard/` | 直播網站、資料整合與 Supabase 工具 | [網站 README](live_dashboard/README.md) |

## 本機使用

保留原本目錄與啟動方式：採集器入口是 `yt_dlp/run_collect_once.bat`、`yt_dlp/start_local_scheduler.bat`；網站入口是 `live_dashboard/start_dashboard.bat`。依各子專案 README 安裝依賴與設定環境。

在本目錄執行 Git 操作及開啟 Codex。兩個子目錄共用一個 repository，仍可分別維護 CHANGELOG 與發布版本。

## 資料與設定

環境設定、cookie、新產生的資料庫、備份與依賴目錄不納入版本控制。原本已追蹤的採集器資料庫仍保留追蹤，避免改變現有採集流程；`.gitignore` 不會取消已追蹤檔案。

## Git 歷史

原始 commit 保留不重寫；搬移 commit 之前的路徑仍位於原 repository 根目錄。舊分支保存在 `archive/collector/`、`archive/dashboard/` 下；舊遠端追蹤分支另保存在其 `remote/` 子目錄。舊 tag 使用 `collector/` 與 `dashboard/` 前綴。

本機 `.migration-backup/` 保存遷移前 Git 中繼資料及 bundle，`.migration-work/` 是遷移工作檔，兩者均排除提交。

## 新 GitHub repository

本機整合不設定遠端，也不推送至舊 repository。建立空白 GitHub repository 後，在本目錄設定新 `origin`，推送 `main`；需要時再推送歷史標籤與 archive 分支。

根目錄 `.github/workflows/collect.yml` 保留手動採集（無定時排程），需要新 repository 的 `TWITCH_CLIENT_ID`、`TWITCH_CLIENT_SECRET` secrets。

`.github/workflows/pages.yml` 部署 `live_dashboard/static`。新 repository 需將 Pages 來源設為 GitHub Actions；部署時會依 Pages 設定與 repository 名稱產生網站路徑及 commit 連結。Supabase 設定仍依網站 README 管理。
