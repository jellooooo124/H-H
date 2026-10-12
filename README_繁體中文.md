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

[英文 README](README.md) · [Portfolio 驗收與缺口](docs/PORTFOLIO_ACCEPTANCE.md) · [Mac 2017 遠端部署說明](docs/MAC_AIR_2017_DEPLOYMENT_V33.md) · [安全限制](docs/SECURITY_LIMITATIONS.md)
