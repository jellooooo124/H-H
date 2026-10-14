# H@H Care Coordination · AI 與 n8n 自動化 Portfolio

這是**獨立的全端軟體工程作品集專案**，整合 **n8n、FastAPI、PostgreSQL、Vue 3、多代理 AI、RAG、醫護人工審核及稽核記錄**。它不是課程作業的延伸版本，也不是已核准的醫療產品。

**僅使用合成資料，不得處理真實病人資料、診斷、治療或緊急救援。**

## 已完成、經 GitHub CI 實際驗證的項目

- Vue 醫護工作台及患者入口、角色授權、監測資料與 Check-in、案件任務、加密儲存及稽核鏈。
- **15 個可匯入的 n8n JSON**，在真實 n8n 2.42.6 容器中全部匯入成功。
- PostgreSQL 17 真實資料庫及跨連線交易測試。
- Docker Compose 同時啟動 FastAPI、PostgreSQL、n8n 和 Vue／Nginx。
- 真實合成患者 API 送出 Check-in → n8n Webhook → FastAPI 內部分流 → PostgreSQL 狀態更新。
- **Chromium 真實瀏覽器**完成醫護建立訊息草稿 → 草稿不對患者可見 → 醫護審核發布 → 患者確認已讀 → 醫護看到回執。
- 重啟 PostgreSQL 與 FastAPI 後，患者確認紀錄與稽核鏈仍完整。
- 未提供真實 AI API 金鑰時，LLM 功能安全停止，不會假裝模型已執行成功。

請參閱 [GitHub Actions](https://github.com/jellooooo124/H-H/actions) 及 [Portfolio 驗收文件](docs/PORTFOLIO_ACCEPTANCE.md)。**CI 全綠不表示所有工作流程已執行、模型已實際呼叫，亦不表示已上線。**

## 啟動（私有 Linux／合成示範）

需要 Linux Docker Engine + Compose。你的 2017 MacBook Air 可以直接用瀏覽器／SSH 操作遠端 Linux，**不需要在 Mac 安裝 Docker**。

```bash
cp .env.example .env
python scripts/generate_secrets.py
# 把產生的獨立隨機金鑰填進 .env，絕不可將 .env 提交到 Git。
docker compose up -d --build
```

服務僅綁定本機位址：醫護介面 `http://127.0.0.1:8080/`、患者介面 `http://127.0.0.1:8080/patient.html`、FastAPI 文件 `http://127.0.0.1:8000/docs`、n8n 管理介面 `http://127.0.0.1:5678`。

逐一匯入 `workflows/` 下的 15 個 JSON。預設不會自動啟用；請在合成環境確認 Webhook、`HAH_INTERNAL_KEY`／`APP_INTERNAL_KEY` 相同後，才發佈需要的流程。勿重複發布相同 Webhook 路徑。短效 Demo Token 可參考 `python scripts/generate_demo_token.py --help`。

**不要把目前的 Demo HTTP 和示範身分驗證直接公開到 Internet。** 真正的公開 Portfolio Demo 還需要 HTTPS、身分存取設計及安全加固。

## 軟體架構

| 層級 | 用途 |
| --- | --- |
| Vue + Nginx | 醫護和患者實際可操作的介面 |
| FastAPI Presentation | 驗證角色、範圍與 HTTP 請求 |
| Application / Domain | 狀態轉換、醫護核准、安全規則 |
| PostgreSQL Infrastructure | 事件、加密、稽核、持久化任務 |
| n8n Automation | 定時、Webhook、失敗重試及 ID-only 協作 |
| LLM / RAG | 受限制工具、來源證據、無金鑰時安全停止 |

## 尚未完成的產品化工作

**目前沒有可供公眾隨時開啟的 Live Demo URL。** 尚需真實 AI 模型 API 金鑰與付費授權、長期雲端主機／網域、HTTPS、OIDC 正式登入、安全祕密管理、備份還原、監控，以及更完整的瀏覽器與負載測試。

現有各階段研究及重構文件保留於 `docs/` 作為技術歷史，但不再以課程評分標準決定 Portfolio 的目標與完成條件。

[英文 README](README.md) · [Portfolio 驗收與缺口](docs/PORTFOLIO_ACCEPTANCE.md) · [Mac 2017 私人遠端部署](docs/PRIVATE_REMOTE_DEMO.md) · [安全限制](docs/SECURITY_LIMITATIONS.md)

## 低成本維護工具

- 首次啟動前執行 `bash scripts/dev_preflight.sh`，先檢查 Docker Compose、`.env` 是否仍有佔位金鑰、設定是否有效及連接埠安全邊界。
- 啟動後執行 `bash scripts/check_demo.sh`，確認 API、前端與 n8n 健康端點，並再次檢查沒有把服務埠公開到所有網卡。
- 暫停使用執行 `bash scripts/stop_demo.sh`（保留資料）；要完全清空合成示範資料時才執行 `bash scripts/reset_demo.sh`。重設會刪除 PostgreSQL、n8n 和應用程式的 Docker volumes，並要求輸入確認字串。
- **依賴可重現安裝：** Python runtime 與測試套件已加入帶 SHA-256 hashes 的 lockfiles；前端及 Chromium 測試加入 npm lockfiles。Docker build 使用鎖定的 Python／npm 依賴，CI 使用 `pip --require-hashes` 與 `npm ci`。
- **Python 依賴更新：** 由每月／手動的 `.github/workflows/refresh-dependencies.yml` 同步更新 requirements constraints 對應的雜湊 lockfiles，並開 PR；避免 Dependabot 只改 `requirements.txt`、實際 CI 卻仍安裝舊 lockfile 的情況。
- **自動更新鎖版依賴：** `.github/workflows/refresh-dependencies.yml` 可手動執行或每月更新 lockfiles 並建立 PR；更新後仍需全部 CI 通過才合併。Dependabot 負責依賴版本提醒。

## 零預算開發方式（先不租主機）

- **預設不花 AI API 費用：** 保持 `OPENAI_API_KEY=` 空白。AI agent 必須 fail closed；合成資料的 API、角色流程、醫護審核、患者確認、資料庫持久化及大部分瀏覽器測試仍可驗證。只有明確測試真實模型時才自行設定金鑰，並先設定供應商的用量／支出上限。
- **避免重複 CI 消耗：** GitHub Actions 會取消同一分支或 PR 上已過時的同類執行；最新提交仍會跑品質、PostgreSQL／n8n 及全堆疊驗收。
- **不用全天開機：** Codespaces 或任何臨時開發環境只在要操作時啟動，完成後停止；先確認帳戶免費額度與計費設定，不假設額度必然足夠，也不把它當 24/7 主機。
- **本機零成本檢查：** 在不啟動 Docker 的情況下，可以執行 Python 離線測試與前端 build（若本機已有相容的 Python／Node 版本）；完整 PostgreSQL、n8n、Chromium Compose 驗收則交給 GitHub Actions Linux runner。
- **資料與安全：** 只用合成患者；不將 `.env`、token、API key 或資料庫備份提交到 Git。不要為省錢把 PostgreSQL／n8n 管理埠直接公開到網際網路。

這套方案的目標是開發階段 **NT$0 固定主機費、NT$0 必要模型費**。GitHub／雲端服務額度及供應商方案可能變動，使用前應查看帳戶目前的額度與 billing 設定。
