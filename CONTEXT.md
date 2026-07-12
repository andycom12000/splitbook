# SplitBook 領域詞彙

所有程式碼與 UI 文案一致使用下列詞彙：

| 中文 | 程式名稱 | 說明 |
|------|---------|------|
| 帳本 | Group | 一次旅程/一個分帳群組，所有資料的容器 |
| 成員 | Member | 帳本內的人，≤5 人，可設 PIN 登入 |
| 分錄 | Entry | 帳本內一筆紀錄，kind = `expense`（支出）或 `transfer`（轉帳） |
| 分攤 | Allocation | 支出在寫入時固化的每人分攤額（不隨主檔變動） |
| 分攤規則 | split policy | `equal`（均分）/ `weights`（權重）/ `exact`（指定金額） |
| 轉帳類型 | transfer_kind | `prepay`（預付/代墊還款）/ `settlement`（結算轉帳） |
| 結算快照 | Snapshot | 凍結某時點的轉帳方案（誰轉給誰多少），付款對準它 |
| 對帳 | reconcile | 快照方案 vs 實際結算轉帳的比對，支援部分付款 |
| 淨額 | net | `advanced + sent - received - share`，正 = 應收回，負 = 應付 |

## 規則摘要

- 守恆不變量：Σnet = 0，分攤總和 = 支出總額，違反 raise `LedgerImbalance`
- 尾差規則：均分餘數從付款人下一位輪流 +1；權重用整數最大餘數法
- 付款即分錄：結算轉帳直接入帳，餘額自洽；快照僅用於追蹤付款進度
- 過期規則：快照後任何非結算分錄的新增/編輯/刪除（rev > through_rev）即過期
- 成員歸屬驗證在儲存層（Repo）強制執行：payer/from/to/分攤對象必須屬於該帳本，違反 raise `ValueError`
