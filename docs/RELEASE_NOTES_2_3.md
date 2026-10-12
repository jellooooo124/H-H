# V2.3 — On-call Shift Handoffs & Durable Dispatch

版本：2.3.0（2026-10-11） · 教學合成資料原型

## 已實作

1. **值班登記**：授權醫護人員只能登記自己對已授權合成患者的 15 分鐘至 24 小時值班；可查詢同患者有效值班名單並取消自己的值班。
2. **雙方確認的交接**：原任務擁有人可以邀請有效值班人員，接受前仍持有任務；接班人必須親自接受，系統才原子更新責任人。拒絕、過期、超時、重複接受均不偷偷轉移。
3. **時間軸**：記錄值班登記、交接、認領、處理、患者合成回執與決策的最小元資料；不儲存交接原文或敏感量測。交接理由加密儲存。
4. **持久化 dispatch_jobs**：案件與 Check-in 出站事件先進 DB queue；有最長 120 秒的 Lease、重試次數、有限 60/120/240 秒 backoff、Dead Letter，並在失敗後建立可供人工查看的模擬任務（案件事件）。
5. **防 webhook 假完成**：若 webhook 被接受，但案件 10 分鐘仍停留 RECEIVED，Reconciler 會有限度再次發送；必須仍以案件處理狀態確認成功。
6. **原有系統保持**：Agents、RAG、Safety Gate、Check-in、FHIR、Postgres/OIDC、audit chain。前端新增值班交接分頁。

## n8n 更新（不自動啟動）

| JSON | 變更 | 說明 |
|---|---|---|
| 01–06、08–09 | 無需重新匯入 | 舊版維持 |
| `07_pending_recovery.json` | **已修改** | 改呼叫 DB queue drain；**停用舊 07 再使用新 07** |
| `10_handoff_expiry_watch.json` | 新增 | 定時處理未接受且過期的交接 |
| `11_dispatch_integrity_watch.json` | 新增 | 定時檢查 Dead Letter；有異常會回 503 |

## 資料庫變更

程式啟動會透過 `CREATE TABLE IF NOT EXISTS` 新增：`duty_shifts`、`task_handoffs`、`care_timeline`、`dispatch_jobs`；`schema_migrations` 記錄版本 23。歷史 2.2 表維持相容；**啟用前務必備份資料庫與金鑰**。離線 SQLite→Postgres 腳本已增加 2.3 表；尚未完成真實大型資料庫遷移測試。

## 風險與限制

- 沒有真實醫院值班/傳呼服務，沒有保證有人在 SLA 內回應。
- n8n 回應 200 不是事件處理完成；這是 at-least-once，非 exactly-once。
- PostgreSQL 實機、n8n 執行、前端 production build 和外部 OIDC 仍待你的環境測試。
- 正式上線還需要臨床驗證、資料治理、行為評估、RBAC 授權測試、監控、負載與災難復原演練。
