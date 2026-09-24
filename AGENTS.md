# 專案工作規則

- 這是單一 Git repository；`yt_dlp/` 是採集器，`live_dashboard/` 是網站與資料整合工具。
- 開始修改前閱讀相關子專案 README；各自 CHANGELOG 保留。
- 保留現有目錄名稱與啟動腳本的工作目錄行為，注意跨目錄的資料庫路徑。
- 不提交 cookie、私人環境設定、密鑰、備份或新產生的資料庫。原本已追蹤的資料庫修改須確認用途。
- 不因驗證而啟動持續採集、排程、上傳或部署；優先使用不寫入正式資料的檢查。
- GitHub Actions 統一位於根目錄 `.github/workflows/`。
- `.migration-backup/` 與 `.migration-work/` 是本機遷移資料，不得提交。
