# V2.3 Integration, Safety Tests, and CA6117 Demonstration

## 1. 啟動及匯入

執行 README 的環境設定與 Compose 啟動。必須先確認 API `/health`；n8n 編輯器匯入 `workflows/` 的 JSON（不要直接匯入 ZIP）。從 2.2 升級時請停用舊 07；啟用新版 07、10、11 之前先手動 Execute Workflow 一次，確定能連到 `http://api:8000`。`09` 需 PostgreSQL 執行。

## 2. 示範「班次交接」

需先由合成患者 token 提交 `examples/normal.json`，用 `01` 分析並產生臨床 Review Task。示範用 `clinician-A` token 認領任務，另一個 `clinician-B` token 登記同一 synthetic patient 的有效值班：

```http
POST /v3/shifts
Authorization: Bearer <clinician-B-token>
Content-Type: application/json

{
  "patient_ref":"DEMO-P001",
  "starts_at":"<ISO8601_current_UTC_minus_1min>",
  "ends_at":"<ISO8601_current_UTC_plus_3hours>"
}
```

再由原本的 `clinician-A` 提出交接：

```http
POST /v3/tasks/<TASK_ID>/handoff
Authorization: Bearer <clinician-A-token>
Content-Type: application/json

{"to_clinician_sub":"clinician-B", "reason":"End of synthetic duty shift; pending documented review"}
```

新接班人先 `GET /v3/handoffs/inbox`，再 `POST /v3/handoffs/<HANDOFF_ID>/accept`；回應顯示新負責人。**同一 Review Task 不允許由舊負責人再次做 `/v1/decisions`**。若接班人按 Reject 或交接超過 15 分鐘，責任仍留在舊負責人。

Dashboard 的「值班交接與追蹤」分頁可執行這些操作。`GET /v3/patients/DEMO-P001/timeline` 顯示最小、無 PHI 的交接和處置時間軸。

## 3. 示範失敗恢復

先以測試 fake-dispatch 模擬 n8n Webhook 下線。患者 `/v1/intake` 接受後，`dispatch_jobs` 會有 PENDING 工作。新 07 定時呼叫 `/internal/ops/dispatch-drain`：限量取出事件、短租約、失敗重試；超過 4 次後狀態變 DEAD，並在合成照護佇列建立 `DISPATCH_DEAD_LETTER` 任務；11 視為操作異常而回 503。真實 n8n webhook 即使曾回 200，案件若 10 分鐘沒有開始，仍會被排入有上限的再次嘗試。

## 4. CA6117 報告展示建議

1. 2 分鐘：醫療資源/Alert Fatigue 問題 + 原有 Multi-Agent RAG 安全設計。
2. 3 分鐘：單一 synthetic patient 進件 → Agent Trace → RAG Citation → Safety Gate。
3. 3 分鐘：人工接單 → 值班交接邀請 → 新負責人接受 → 原負責人不能越權決策。
4. 1 分鐘：Dead Letter / 恢復機制的單元測試 + 11 條 n8n 流程。
5. 1 分鐘：對照評估表，誠實揭露未通過的外部環境/臨床性能驗證。

## 5. 測試指令

```bash
pytest -q
python scripts/verify_artifact.py
# 外部 Docker 與 PostgreSQL 由你本地啟動後另外測試
# 前端需可以使用 npm registry / node_modules 才可 npm run build
```

本版已觀察到 48 passed / 1 skipped；skip 是 opt-in Postgres live 測試。沒有證據可宣稱醫療效果或臨床安全。
