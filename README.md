[GitHub Pages](https://ray-0411.github.io/vtuber_all/)

# VTuber 採集與直播網站

已依 `sort.md` 於 2026-09-29 整理目錄。Git 根目錄不變；原檔全部保留，修改前版本在本機 `other/reorganization/before-edits/`。

| 目錄 | 用途 |
| --- | --- |
| `catcher/` | YouTube／Twitch 採集核心、SQL、測試與依賴 |
| `website/` | 網站、Python 本機 API、Supabase schema 與靜態前端 |
| `database/` | 正式、發布、歷史、預覽與備份資料庫；全部排除 Git |
| `log/` | 兩個專案 CHANGELOG、發布報告及排程狀態；執行產物排除 Git |
| `tools/` | BAT 入口、working 檢視工具及資料發布工具 |
| `other/` | 文件、私人設定、原版副本、舊工具及用途待確認內容 |

完整目錄樹與逐項用途請看 [DIRECTORY_GUIDE.md](DIRECTORY_GUIDE.md)。新增或移動項目時，請同步更新該索引。

## 常用入口

- `tools/catcher/.main_catcher.bat`：採集排程。
- `tools/catcher/run_collect_once.bat`：採集一輪。
- `tools/catcher/working_viewer/list_working.bat`：查看最近工作狀態。
- `tools/catcher/working_viewer/working_calendar.bat`：工作日曆。
- `tools/catcher/streamer_manager/open_streamer_form.bat`：人員管理。
- 官方 YouTube API／WebSub 驗證管線已封存於 `other/archive/youtube-api/`，不屬於目前採集流程。
- `tools/publish/.supabase_update.bat`：原正式定期發布流程，03／33 分執行。
- `tools/website/start_dashboard.bat`：使用原網站副本啟動本機網站。

BAT 會自行設定工作目錄。直接使用 Python 時，採集器的預設 DB 路徑也不依賴目前工作目錄。

## 資料與設定

目前使用的資料庫：`database/main/{live_data,streamer_config,streamer_audience}.db`。舊格式直播歷史已併入 `database/main/live_data.db`；`database/website/data.db` 與 `legacy_live_data.db` 保留為來源副本。
定期發布產物：`database/published/`。原網站資料副本：`database/website/`，為避免誤混資料仍獨立保存。
`database/main/youtube_api_data.db` 是先前獨立驗證管線留下的資料庫；目前主要採集不讀寫它。

Cookie 位於 `other/local/cookie/`；WebSub 設定位於 `other/local/catcher/`；正式發布密鑰位於 `other/local/publish/`。原網站密鑰另保留在 `other/local/website/`。不要提交這些資料。

Python 採集依賴：`catcher/requirements.txt`。Node 依賴：在 `catcher/` 執行 `npm install`。發布依賴：`tools/publish/requirements.txt`。

離線測試：`python -m unittest discover -s catcher/tests`。

## GitHub Actions

根目錄 `.github/workflows/pages.yml` 部署 `website/static/`。
`collect.yml` 仍只支援手動觸發；採集結果保存為 Actions artifact，避免將正式 DB 提交 Git。啟用使用前需提供 Twitch secrets 與名單資料。

## 文件

- [完整目錄對照](other/docs/LAYOUT.md)
- [待修改事項](log/待修改事項.md)
- [採集器原始說明](catcher/README.md)
- [網站原始說明](website/README.md)
- [採集器版本紀錄](log/catcher/CHANGELOG.md)
- [網站版本紀錄](log/website/CHANGELOG.md)
- [交接主文件](other/docs/PROJECT_MIGRATION_HANDOFF.md)

舊文件保留歷史原文；其中路徑以目錄對照表為準。舊工具位於 `other/archive/`，為追溯而保存，不作為日常執行入口。
