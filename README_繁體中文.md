# Hospital-at-Home Care Coordination：完整研究展示版

這是一套整合 **n8n + FastAPI + PostgreSQL + Vue 3 + 多代理 AI + RAG + Human-in-the-Loop** 的 CA6117 研究原型，只可使用**合成病人資料**，不是正式醫療產品。

## 目前可展示的完整流程

病人提交量測／Check-in → 後端驗證並儲存事件 → n8n 觸發受限制 AI 工具與 RAG → 安全規則阻擋風險 → 醫護接單、檢視和決策 → 任務交接與逾時重試 → 固定模板站內訊息草稿 → 醫護明確核准發佈 → 病人確認已讀；逾期則產生追蹤任務。整段過程留下稽核紀錄。

可展示患者入口、醫護工作台、FHIR R4 合成 Observation、歷史趨勢、醫護交接、RAG 來源、工作評估、合成規則測試。**無真實 SMS、Email、醫院呼叫或臨床救援服務**。

## 安裝

```bash
cp .env.example .env
python scripts/generate_secrets.py
# 將輸出金鑰填入 .env，切勿提交 .env 至 Git
docker compose up -d --build
```

- 醫護：http://127.0.0.1:8080/
- 病人：http://127.0.0.1:8080/patient.html
- n8n：http://127.0.0.1:5678
- API 文件：http://127.0.0.1:8000/docs

逐一匯入 `workflows/` 內的 **15 個 JSON**，每個預設 `active=false`；不要把 ZIP 當成單一 Workflow 匯入。先確認 n8n HTTP 節點在 Docker 網路可以呼叫 `http://api:8000/internal/...`，環境變數 `HAH_INTERNAL_KEY` 與 API 的 `APP_INTERNAL_KEY` 一致。先手動測試，再啟用排程。

**模型未設定金鑰時，不會偽裝成 AI 成功分析；會安全停止並轉人工技術複核。**

## 驗證

```bash
pip install -r backend/requirements.txt pytest pytest-asyncio
pytest -q
python scripts/verify_artifact.py
python scripts/evaluate_synthetic_policy.py
```

臨床級安全與正式部署要求尚未達成；請查看 `docs/SECURITY_LIMITATIONS.md`。目前新功能依 Domain → Application → Infrastructure → API 分層，舊版 v1–v4 相容 API 保留於 `legacy_api.py`，仍有後續技術債，不宣稱整個歷史程式已全面重構。

GitHub 的新 Repository 發布方案請見 `docs/GITHUB_PUBLISH.md`。`workflows/*.json` 是可直接在 n8n 匯入的原始 JSON。

## Clean Architecture v3.1 重構

本版將患者監測、交接、FHIR、患者互動、案件查詢 API 拆成 Presentation / Application 模組，將主要 SQL 儲存移至 Infrastructure，並加入純 Domain 的授權政策及相容契約測試。原 59 個 API method/path 及 15 個 n8n JSON 工作流程不變。尚留 16 個主要臨床協調 API 在相容層，**不是**全面完成的臨床級 Clean Architecture。詳見 [重構說明](docs/REFACTOR_3_1.md)。

## Clean Architecture v3.2 更新

本版把 v3.1 留在 `legacy_api.py` 的收案、醫護決策、Agent、Safe Stop、Watchdog、事件重試及管理路由，全部移到獨立的 Presentation Router 與 Application Use Case。`legacy_api.py` 保留為約 109 行的組裝及向下相容入口。

**59 個原有 API method/path 全部保留；15 個 n8n JSON 與 v3.1 完全一致**，若已匯入舊版，不需要再次匯入，以免重複排程。並新增交易回滾、技術失敗人工任務、逾時升級與原有介面契約測試。驗證為 79 項離線測試通過、1 項 PostgreSQL 實機測試跳過，12/12 合成安全案例通過。

請參閱 [`docs/REFACTOR_3_2.md`](docs/REFACTOR_3_2.md)；舊的照護協調、FHIR、排班與通知模組尚有資料庫邏輯混用，不能宣稱整套系統已完全 Clean Architecture，更不能視為正式臨床系統。
