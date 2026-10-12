# V2 Demo & Tests：10 分鐘課堂展示建議

## 建議 10 分鐘節奏

| 時間 | 內容 | 必須出示的可見證據 |
|---|---|---|
| 0:00–1:00 | Clinical problem & scope | HF+Diabetes 共病、居家資料缺失和 alert fatigue |
| 1:00–2:00 | Architecture | n8n 7 workflows、後端 Rules Gate、加密儲存、誰負責甚麼 |
| 2:00–3:00 | Perceive: synthetic observations | 3 筆跨日體重 Observation、七日 trends、缺失不補零 |
| 3:00–4:30 | Reason: true Multi-Agent | n8n Planner call loop、HF/Diabetes/Nutrition、RAG 引文與 Safe Stop |
| 4:30–6:30 | Act/Human Oversight | 臨床任務 queue、先 Claim、Approving vs Reject/Escalate |
| 6:30–7:30 | Closed-loop | 新增 `escalation_followup` task、`unable_to_reach` 不可直接完成 |
| 7:30–8:30 | Safety challenge | 模擬 urgent checkin、角色 scope、逾時、prompt injection、安全拒絕 |
| 8:30–9:30 | Evaluation | pytest 測試結果、Audits、RAG provenance、技術 metrics |
| 9:30–10:00 | Limits and roadmap | Synthetic-only、沒有真 FHIR、沒有 Postgres / 真通知或臨床驗證 |

## 關鍵 demo 驗收流程

1. 開啟 Dashboard，用短效 Demo clinician JWT 登入。
2. 送三筆不同 timestamp 的 `weight_kg`。讀 `GET /v2/patients/DEMO-P001/trends`，觀察 observed samples 和 delta。
3. 發 urgent Check-in，`/v2/tasks` 出現 `reported_symptom_review`（不依賴 n8n 啟動）。
4. 送 `examples/normal.json` 到 `/v1/intake`，n8n 應跑完整 4 個必要 Tool 再 finalize；缺少 API Key 應 Fail Closed。
5. 查看 clinical review Task。未 Claim 前嘗試 `/v1/decisions`，應回 HTTP 409；Claim 後才允許對安全案件核准。
6. 送 `examples/redflag.json` 到 `/v1/intake`；即使 Clinician Claim，Approve 應被獨立政策阻擋；Escalate 新增 `escalation_followup` 任務。
7. 對 Follow-up Task 記錄 `unable_to_reach`，任務應回到 OPEN，不可偽裝為有收到患者回覆。
8. 重複送相同 Observation event_id，應回 HTTP 409；重複 Claim by another clinician 應回 HTTP 409；重複執行 Watchdog 不應重複新增相同 daily missingness task。
9. 在 `/v1/audit/{case_id}` 檢查 HMAC chain_valid 及 redacted metadata，不能當作正式 WORM 記錄。

## 執行離線測試

```bash
python -m pip install -r backend/requirements.txt pytest pytest-asyncio
pytest -q
```

**測試不是**安全認證、臨床有效性或正式 n8n 匯入成功的證明；Docker 與真 OpenAI API 未在本工作階段執行。

## 量測表：不要虛構評估結果

| 面向 | 後續收集指標 | 最小可接受的評估方式 |
|---|---|---|
| Clinical safety | 高風險病例召回率、誤報率 | 臨床人員標註的 synthetic scenario test set |
| Workflow reliability | 遺漏案件、SLA 逾時比例、重送成功率 | 故障注入並擷取 audit/queue traces |
| Agent reliability | JSON schema validity、tool authorization、token/cost | 分版本 prompt 和模型的回歸測試 |
| RAG faithfulness | Citation accuracy、source freshness、句子/來源相符率 | 人工檢查引用是否真的支持結論 |
| Human factors | 審核時間、warning 理解度、automation bias | 使用者任務研究，非純單元測試 |
| Equity | 不同族群的缺失率和誤報差異 | 取得相應合規資料後的分組評估 |
