# 專案工作規則

- 這是單一 Git repository；`catcher/` 是採集器，`website/` 是網站，操作工具在 `tools/`。
- 開始修改前閱讀相關子專案 README；各自 CHANGELOG 保留。
- 資料庫集中於 `database/`；正式來源在 `database/main/`。使用以程式位置解析的路徑，不依賴啟動時的工作目錄。
- 不提交 cookie、私人環境設定、密鑰、備份或新產生的資料庫。原本已追蹤的資料庫修改須確認用途。
- 不因驗證而啟動持續採集、排程、上傳或部署；優先使用不寫入正式資料的檢查。
- GitHub Actions 統一位於根目錄 `.github/workflows/`。
- `other/archive/`、`other/local/`、`other/reorganization/` 是封存、私人設定與搬移核對資料，不得提交。
- 依使用者要求，整理期間不刪除任何原檔；不確定用途的檔案先放 `other/`。修改前原版保存在 `other/reorganization/before-edits/`。
