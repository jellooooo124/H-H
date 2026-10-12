# PostgreSQL 實作、資料遷移與 OIDC 設定

## A. 全新 2.2 開發環境（無舊資料）

1. `cp .env.example .env`，執行 `python scripts/generate_secrets.py`，把所有產生的值填入 `.env`。`POSTGRES_PASSWORD` 使用 URL-safe 十六進位即可。
2. 留下 `AUTH_MODE=demo`，確認使用合成資料，放入自己的 OpenAI API Key（若需真的執行模型）。
3. `docker compose up -d --build`；`docker compose ps` 應顯示 `postgres` healthy、`api` 和 `n8n` 啟動。
4. `curl http://127.0.0.1:8000/health` 應看到 `"db_backend":"postgres"`。這只是 API 的啟動檢查，不代表臨床安全。
5. 在 n8n 新環境逐一匯入 `workflows/01`–`09` 的 JSON。所有工作流程匯入後均為 inactive，先手動執行 `09`，確認 `db_backend=postgres`、`audit_chain_valid=true`；再手動測試 `01/05/08`。
6. 在 `frontend` 執行 `npm install && npm run dev`；使用 demo JWT 登入查看合成測試案件。

**注意**：`POSTGRES_PASSWORD` 不放入 n8n 環境；n8n 只能經受限的 FastAPI `/internal` 端點查詢工作狀態。此 Docker 網路是開發網路，未配置傳輸層資料庫 TLS、Secret Manager 或網路出口白名單，僅供隔離測試使用。

## B. 2.1（SQLite）升級到 2.2（PostgreSQL）

**嚴格要求停機與備份。禁止對仍在服務中的 SQLite 執行匯入；不得使用任何真實患者資料。**

1. 使用原版 `docker compose stop api n8n`。備份原本的 SQLite `cases.db` **含 WAL**（在確認容器已停止並 checkpoint 後）和 `.env` 金鑰到受控的離線位置。保留 `APP_TOKEN_SECRET`、`APP_ENCRYPTION_KEY`、`APP_INTERNAL_KEY`、`N8N_ENCRYPTION_KEY`，不能重新產生舊金鑰。
2. 將程式更新至 2.2，但保留相同 Compose 專案名稱 `hah-course-demo` 和 `cases_data` volume。只新增 `POSTGRES_PASSWORD`、`APP_ADMIN_KEY` 和 AUTH 配置。預設先使用 `AUTH_MODE=demo`。
3. 啟動 PostgreSQL：`docker compose up -d postgres`。
4. 執行 API schema 初始化**但不要開放接收新請求**：

   ```bash
   docker compose run --rm api python -c "from app.main import app; print('PostgreSQL schema initialized')"
   ```

5. 執行離線遷移：

   ```bash
   docker compose run --rm -e SQLITE_SOURCE=/appdata/cases.db api python scripts/migrate_sqlite_to_postgres.py
   ```

   目的地所有業務表需為空白。若 Audit HMAC 密鑰錯誤、輸入資料異常或筆數不一致，會**拒絕／回滾**。
6. 重新啟動：`docker compose up -d api n8n`；檢查 API `/health`、`09` 稽核鏈、原有案例及 FHIR 合成資料查詢一致後才使用。
7. 失敗時不要刪除原 SQLite volume 或覆寫金鑰；停止新版 API，保留錯誤紀錄，先在測試環境復原舊 2.1 Compose，再重新規劃資料遷移。**不提供在線雙寫／不停機切換**。

## C. 切換外部 OIDC JWT 驗證（非完整 SSO 前端登入）

`.env` 示例（值必須來自已配置的測試身分提供者，非以下佔位文字）：

```ini
AUTH_MODE=oidc
OIDC_ISSUER=https://login.example.test/issuer
OIDC_AUDIENCE=hah-health-api
OIDC_JWKS_URL=https://login.example.test/issuer/protocol/openid-connect/certs
OIDC_CLINICIAN_GROUP=hah-clinician
OIDC_PATIENT_GROUP=hah-patient
```

- 接受的 Bearer JWT：`RS256`、可信 JWKS `kid`、精確 Issuer + Audience、`exp` + `iat` + `sub`、`groups` 限定恰好一種角色。患者還需經可信簽發 JWT 攜帶 `patient_ref=DEMO-P001`；所有非 `DEMO-` ID 都拒絕。
- 醫護人員即使有 `hah-clinician` 群組，也**沒有自動存取所有患者的權限**。必須使用獨立管理金鑰指派：

  ```bash
  curl -X POST http://127.0.0.1:8000/admin/assignments \
    -H "X-Admin-Key: $APP_ADMIN_KEY" -H 'Content-Type: application/json' \
    -d '{"clinician_sub":"staff-A","patient_ref":"DEMO-P001","active":true}'
  ```

- 撤銷同一指派使用 `active:false`，隨後的案件、趨勢、任務、FHIR 查詢均拒絕。這是後端存取授權，不是 Vue 的前端 UI 隱藏。
- `APP_ADMIN_KEY` 必須只由授權管理者持有，切勿傳入 n8n、瀏覽器或 Git。
- 2.2 並未做 OIDC Authorization Code + PKCE 的 Browser Login；前端只能貼入由你可信身分提供者取得的短效 Access Token，**切勿使用外部服務的 ID token 代替正規 API access token**。要走向正式產品需要完成 PKCE/BFF、Session、refresh token rotation、CSRF 與 IdP 群組同步。
- OIDC 模式故意不顯示跨患者彙整的 `/v2/metrics`；需另設有權限的統計角色/去識別查詢。

## D. 可選 PostgreSQL 實機煙霧測試

測試環境須先提供 psycopg3 和**專用、可丟棄的資料庫**，絕對不能把正式病人資料庫放入 `PG_TEST_URL`：

```bash
PG_TEST_ISOLATED=YES PG_TEST_URL='postgresql://.../hah_test_disposable' pytest -q tests/test_postgres_live_optin_v22.py
```

測試只會在明確設置兩個變數時執行。它不提供多 worker、壓力或備援保證。
