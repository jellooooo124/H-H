# Hospital-at-Home Care Coordination 2.2 — Release Notes

**版號**：2.2.0　　**範圍**：僅供 CA6117 合成資料課程展示與後續研究開發；不適用於真實患者或臨床使用。

## 交付內容

- **9 個停用狀態的原生 n8n Workflow JSON**，含新增 `09_database_auth_audit_health.json`。`01`–`08` 保留原 JSON 與路徑，方便舊版升級；請**不要**把舊有同名排程重複啟用。
- **PostgreSQL 執行路徑**：`DATABASE_URL` 使用 psycopg3 連線，保留現有加密 JSON、案件版本鎖、FHIR Bundle 整批交易與稽核 HMAC 鏈的儲存介面。Compose 新增 `postgres` 容器及持久化 volume，API 預設指向 PostgreSQL。明確設定 PostgreSQL 時，失敗即停止服務，不會自動改用 SQLite。
- **離線遷移工具**：`scripts/migrate_sqlite_to_postgres.py`；移轉前驗證來源稽核鏈，要求新資料庫所有業務表空白，採 PostgreSQL 單一交易匯入，檢查逐表筆數與目的地稽核鏈，失敗回滾。`APP_TOKEN_SECRET` 和 `APP_ENCRYPTION_KEY` 必須沿用原版。
- **身分驗證**：`AUTH_MODE=demo` 預設保留 HS256 合成 JWT；`AUTH_MODE=oidc` 改驗證外部 RSA RS256 JWT 的簽章、`kid`、Issuer、Audience、時效、`groups`，不採信任意 `role` 欄位；服務端 `clinician_assignments` 控制醫護可存取的病人，撤銷後立即拒絕。身分提供者測試使用本機 RSA 公鑰模擬，**沒有完成任一真實 IdP 的上線登入整合**。
- **獨立指派操作金鑰**：`APP_ADMIN_KEY`（不可傳給 n8n）管理 synthetic clinician→patient 指派。n8n 原有 `APP_INTERNAL_KEY` 不得操作醫護指派。
- **第 9 條 n8n 稽核監測**：每小時呼叫 `POST /internal/ops/audit-health`，對 PostgreSQL 連線及 HMAC 鏈進行測試；不是患者即時監測或臨床通知系統。API 不使用 PostgreSQL 時回傳 503。
- **前端**：可填入 OIDC Access Token；OIDC 模式下不提供全體病人聚合統計，前端即使該指標權限不足仍能使用有權限的案件清單。

## 證據與未驗證事項

`pytest -q`、`python scripts/verify_artifact.py`、`python -m compileall` 為離線檢查；執行次數與結果請以本版 `docs/OFFLINE_TEST_RESULTS_V22.txt` 為準。

**尚未完成**：實際 PostgreSQL/psycopg3 容器端到端測試（本執行環境無 Docker/PostgreSQL/psycopg3）、實際 n8n 2.42.6 匯入與排程執行、外部 OIDC 身分提供者登入及瀏覽器授權碼流程、FHIR 正式醫院 OAuth、網路 TLS、資料庫正式 migrations/RLS、多 worker 壓力測試、外部呼叫備援與患者真實通知、臨床效果驗證。這些須由部署環境執行及覆核，**不得稱為已完成正式上線**。

## 新版和舊版的區別

`database/postgres_target_schema.sql` 仍是**未實施的正式產品設計**，與 2.2 API 啟動時建立的相容性 PostgreSQL runtime schema 不同。本輪使用的是 PostgreSQL DBMS，但仍為合成資料原型，不是正式醫療級資料倉儲；要產品化仍應改為 versioned migrations、分離金鑰、可稽核備援、RLS 與多院區租戶授權。
