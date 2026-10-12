# Care Coordination 2.1 Release Notes — 2026-10-11

## 本輪已可使用的功能

- 2.0 原有 7 個 workflow 保留；新增第 8 條 `08_synthetic_fhir_sandbox_sync.json`，可由 n8n 定時呼叫後端同步**內建、固定值、合成** Observation（並非任何外部醫院或 EHR）。
- FHIR R4 `Observation` / `Bundle` 限定子集匯入、匯出，白名單 LOINC/UCUM，拒絕不受支援的欄位、時間、單位、非 DEMO 病人，以及格式錯誤；來源追溯、整批回滾、冪等匯入、衝突 409。
- 33 項離線測試綠燈；8 條 n8n 工作流程經 JSON 靜態結構與內部 API 節點檢查。**尚未在 n8n 2.42.6 實例實際匯入執行**。
- PostgreSQL 目標 DDL 新增 `fhir_source_registry`；但仍是設計，不是已實施 PostgreSQL runtime。當前 SQLite 加密儲存 demo 保持不變。

## 安裝與升級

1. 保留原有 `.env` 的 `APP_ENCRYPTION_KEY`、`APP_TOKEN_SECRET`、`N8N_ENCRYPTION_KEY`、`APP_INTERNAL_KEY`；不要更換現有資料庫的加密金鑰。把新專案作為完整替換的程式碼來源，不要把舊資料覆蓋或將未加密的實際病人資料傳入。
2. `docker compose up -d --build`。現有資料存在 Docker `cases_data` volume。若已建立不同 compose 專案名稱，請檢查 volume 名稱，避免誤以為資料遺失。
3. n8n：現有 01–07 如沒有自行修改，**不用重複匯入**（避免製造重複的計畫工作流程）。只需 Import from File 新增 `08_synthetic_fhir_sandbox_sync.json`。全新環境則逐一匯入全部 8 個 JSON。
4. 先以 n8n 手動執行新流程，觀察 `imported=3`；第二次當日執行應 `imported=0, unchanged=3`。只有確認結果正確，再開啟定時排程。
5. 原有 01/05 Webhook 的 ID/path 必須保持一致；n8n 複製匯入或重新啟用可能導致相同 path 衝突，應先停用舊的對應流程。

## 為什麼沒有直接切成 PostgreSQL？

在沒有 PostgreSQL 執行實例、正式 migrations 和對現有 SQLite 讀寫、Audit 一致性的測試前，直接聲稱完成實際 runtime 遷移並不安全。本次先完成 FHIR 標準資料邊界和安全範圍，下一輪以 PostgreSQL 切換與跨程序事務測試為優先，並加入 OIDC/SSO 或可配置的外部測試身分提供者。

## 已知產品化缺口

真正遠端 FHIR OAuth/SMART on FHIR、醫院系統互通、真實病人授權、多院區權限、正式 PostgreSQL runtime、審批後真通知/值班救援、臨床效能驗證與合規審查均未完成。本版本 **synthetic-only**。
