# Sprint B1 — FHIR R4 Synthetic Interoperability (2.1)

## 交付物

- 新增 **`workflows/08_synthetic_fhir_sandbox_sync.json`**，可直接匯入 n8n；12 小時一次排程，HTTP Request 呼叫後端 `POST /internal/fhir/sandbox-sync`。其他 7 條 workflows 仍完整保留。所有 workflows 匯入時 `active: false`，請**逐一匯入**，只在檢查完成後啟用。
- `backend/app/fhir_bridge.py`：只接受 `DEMO-` 病人、`final` 狀態、FHIR R4 collection Bundle、單一 `http://loinc.org` 編碼、指定 UCUM 單位，及病人匹配的 Observation。拒絕所有非白名單欄位（包括自由文字、extension）。
- 依 `(patient_ref, remote resource id)` 建立來源追蹤；相同內容再次匯入計為 `unchanged`；相同 ID 不同內容回 409；同一個 Bundle **全部成功或全部回滾**。
- `POST /v3/fhir/import`：clinician 身分令牌 + `{patient_ref,is_synthetic:true,bundle}` 封裝。可透過測試版 `patient_refs` claim 做額外患者範圍限制；但現有 demo JWT **不是實際 IAM/SSO**。
- `GET /v3/fhir/Observation?patient_ref=DEMO-P001`：匯出 synthetic 限定格式 FHIR Observation Bundle。
- `POST /internal/fhir/sandbox-sync`：使用**內建、固定值、合成的本地資料**；回傳 count 和 `remote_ehr_connected:false`，並**不會**存取 Epic、Cerner、任何實際醫院 FHIR Server。
- PostgreSQL 目標設計增加 `fhir_source_registry`，但當前執行時仍使用 SQLite，不應把這份 SQL 當成已完成 PostgreSQL 遷移。

## 測試流程

```bash
# 根目錄：先啟動 API、n8n；先生成 Demo Token
python scripts/generate_fhir_demo_payload.py
# 取得 Clinician token 並設定 CLINICIAN_TOKEN
curl -sS -X POST http://127.0.0.1:8000/v3/fhir/import \
  -H "Authorization: Bearer $CLINICIAN_TOKEN" -H 'Content-Type: application/json' \
  --data-binary @examples/fhir_synthetic_bundle.json
# 重做同一個 curl 將回傳 imported=0, unchanged=4
curl -sS -H "Authorization: Bearer $CLINICIAN_TOKEN" \
  'http://127.0.0.1:8000/v3/fhir/Observation?patient_ref=DEMO-P001'
```

### n8n 匯入

1. n8n → Workflows → Import from File，選 `workflows/08_synthetic_fhir_sandbox_sync.json`。
2. 檢查 HTTP URL `http://api:8000/internal/fhir/sandbox-sync`。此主機名稱只適用於提供的 Docker Compose 網路。
3. `X-Internal-Key` 以 `$env.HAH_INTERNAL_KEY` 讀取，**僅限隔離的合成教學環境**；正式部署要改用 n8n 的憑證管理/短效機器身分。
4. **先手動執行**並檢查回傳 `synthetic_only:true`、`remote_ehr_connected:false`。
5. 若需要，再開啟排程；每次定期同步會略過當日已經匯入的三筆資料。

## 與產品化的差距

- 尚未實作遠端 FHIR Server OAuth 2.0 / SMART on FHIR、增量 `_since` 分頁同步、Subscription、API 速率控制、FHIR Profile 驗證、Patient ID mapping、Terminology Service，亦未通過規範驗證套件。
- 不允許把醫院 FHIR URL 或任何真實病人資料輸入此原型。下一階段先於獨立 FHIR Sandbox 測試 OAuth、分頁與資料欄位映射，再增加 PostgreSQL 正式 runtime 以及 OIDC/MFA、患者照護團隊權限隔離。
- 現有安全鏈是本地 HMAC 防篡改示範；正式運作需要獨立儲存、外部時間戳及安全監控。

## 為什麼這項改動對 CA6117 有幫助？

可以 Demo 第一次 FHIR 匯入 `imported=4`、第二次 `unchanged=4`、不符 UCUM 單位返回 422、冒用 Patient ID 返回 422，以及同一 Observation ID 被修改返回 409。可直接展示 **工具整合、明確約束、持久化狀態、錯誤處理、可追溯來源及測試證據**，而不是只展示 AI 回答。
