# 2017 MacBook Air：實際運行 Docker / PostgreSQL / n8n（合成資料研究專用）

## 硬體和 macOS 的現實限制

Apple MacBook Air 13-inch 2017：Intel 雙核心、通常 8 GB RAM；官方最高支援 macOS Monterey 12。
當前 Docker Desktop 支援現行及前兩版 macOS；Colima 目前要求 macOS 13+。
**不要在 Monterey 上強行安裝最新版 Docker Desktop／Colima，亦不要把舊版無安全更新 Docker 用於真實醫療資料。**

先在自己的 Mac Terminal 執行（只讀取資訊，不修改設定）：

```bash
bash scripts/mac_air_preflight.sh
```

## A — 建議方案：Mac 上操作，遠端 Linux 跑四個容器

環境：一台自己可管理的 Ubuntu 24.04 LTS Linux VPS / 桌面 Linux，初步可用 **4 vCPU / 8 GiB RAM / 40 GiB SSD**。這是合成 Demo 的起始配置，非保證；n8n/影像處理或大型資料量可能需要擴充。用 OpenAI API 推論，不在 Mac 本機跑大型模型。

1. 在 Linux 安裝 Docker Engine + Compose v2：參照 [Docker 官方 Ubuntu 安裝文件](https://docs.docker.com/engine/install/ubuntu/)。完成後驗證：

   ```bash
   sudo docker run --rm hello-world
   docker compose version
   ```

   若仍需 sudo，後續命令使用 `sudo docker compose`；加入 docker 群組等同高權限，不建議盲目變更。

2. 在 Linux 建立專案資料夾，透過 `scp` / `rsync` 將解壓後的專案上傳。不要將 `.env` 或含病人資料的資料庫推到 GitHub。

   ```bash
   # 在 Mac 的已解壓資料夾上一層執行（SERVER_USER、SERVER_IP 須替換）
   rsync -av --exclude='.env' --exclude='.git' --exclude='*.db' hah_care_coordination_clean_architecture_v3_3/ SERVER_USER@SERVER_IP:~/hah/
   ```

3. 在 Linux 主機內（不是 Mac）執行：

   ```bash
   cd ~/hah
   cp .env.example .env
   python3 -m venv .venv
   .venv/bin/pip install cryptography
   .venv/bin/python scripts/generate_secrets.py
   ```

   將生成的值**手動填入** `.env` 並 `chmod 600 .env`。`OPENAI_API_KEY` 可先留空：Agent 會 fail-closed，轉技術人工審查，並非 AI 成功。絕不能把真實 PHI 傳到展示版。

4. 啟動：

   ```bash
   docker compose config -q
   docker compose up -d --build
   docker compose ps
   bash scripts/verify_remote_deployment.sh
   ```

5. 專案的 Compose 將前端、n8n、API 三者映射到 Linux **127.0.0.1**，PostgreSQL **不暴露 host port**。從 Mac 建立 SSH tunnel：

   ```bash
   ssh -N -L 8080:127.0.0.1:8080 \
          -L 5678:127.0.0.1:5678 \
          -L 8000:127.0.0.1:8000 SERVER_USER@SERVER_IP
   ```

   保持 Tunnel 開啟，然後在 Mac 瀏覽器存取：
   - http://127.0.0.1:8080 （醫護 Dashboard）
   - http://127.0.0.1:8080/patient.html （患者 Demo）
   - http://127.0.0.1:5678 （n8n）
   - http://127.0.0.1:8000/docs （API docs）

6. n8n 上建立 owner account，逐一匯入 `workflows/*.json` 的 15 條流程，**先別啟用排程**。確認 n8n HTTP Request 節點連到 Compose 內網 `http://api:8000/internal/...`，且 `HAH_INTERNAL_KEY` 由 `.env` 注入、與 API 的 `APP_INTERNAL_KEY` 一致。先手動執行合成測試再逐條開啟。

7. 關閉、查看錯誤、備份（在 Linux）：

   ```bash
   docker compose logs --tail=100 api n8n postgres
   docker compose stop  # 保留 data volumes
   # 注意：docker compose down -v 會刪除 named volumes，除非確定不需要資料，切勿使用。
   ```

**安全事項**：n8n 的 `N8N_BLOCK_ENV_ACCESS_IN_NODE=false` 與 `N8N_SECURE_COOKIE=false` 是課程 Demo 的設計債。不可在公網開放端口；只透過 SSH Tunnel / 私人 VPN。正式部署須改用 n8n Credential/Secrets 管理與 HTTPS，再將環境變數存取設為封閉，並重做 workflow credentials。

## B — 不租遠端主機：Mac 本機輕量開發

Monterey 不適合最新版 Docker Desktop。可先獨立執行 FastAPI + SQLite 合成測試，並視你可安裝的 Node 版本嘗試 n8n 2.x 的 npm 安裝（n8n 3.0 起 npm 安裝逐步淘汰，請驗證版本）。

```bash
cd hah_care_coordination_clean_architecture_v3_3
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt pytest pytest-asyncio
PYTHONPATH=backend pytest -q
```

若要在 Mac 跑 API / n8n，需要改 `.env`、`DB_PATH`、`N8N_WEBHOOK_URL` 及啟動方式，**不能原封不動使用 Docker Compose**。本機最少可以完成程式與合成單元測試；完整實機驗證建議 A 方案。

## 完成驗收的標準

- `docker compose ps` 服務健康、無重啟迴圈
- `bash scripts/verify_remote_deployment.sh` 成功
- 15 條 n8n JSON 成功匯入，至少一條合成 Case 從 Intake → Agent → Safe Stop → 人工任務完成
- PostgreSQL 容器重啟後資料仍持久化、錯誤注入時整筆交易回滾
- 同時觸發兩個 worker 時無重複派送（**尚未完成此驗證**）
- 沒有公開 PostgreSQL/API/n8n 服務埠，測試全程無真實病人資料

以上屬待在你機器上驗證的步驟，**不是本次環境已跑過的結果**。
