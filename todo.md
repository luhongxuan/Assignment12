這是一個非常好的問題。作為 **Developer (開發者)**，你在 Task 2 的核心職責不是「制定商業合約 (SLA)」，而是 **「確保技術上能偵測到問題 (SLI/SLO)」** 以及 **「提供具體的技術修復手段 (Runbooks)」**。

根據你提供的圖片（特別是 `image_58c003.png` 定義的指標 和 `image_58bfbf.png` 的 Runbook 範例），以下是你作為開發者需要執行的詳細步驟：

-----

### 第一階段：定義與實作 SLI/SLO (Metrics Implementation)

雖然 PM 可能定義了目標，但身為 Developer，你需要確認程式碼吐出的 Metrics 能不能算得出這些數字。

**1. 確認 Guest Checkout 的 SLI (可用性)**

  * **目標 (SLO)**: 99.90% Availability。
  * **開發者動作**:
      * 你需要確保 `prometheus-flask-exporter` 能正確捕捉到 `/api/book` 的 HTTP 狀態碼。
      * **驗證方法**: 確認當發生 500 錯誤時，Prometheus 的 `flask_http_request_total{status="500"}` 會增加。
      * **報告內容**: 在報告中列出你的 Prometheus Query (SLI 實作公式)，例如：
        ```promql
        sum(rate(flask_http_request_total{status="200"}[5m])) / sum(rate(flask_http_request_total[5m]))
        ```

**2. 確認 Seat Allocation 的 SLI (延遲)**

  * **目標 (SLO)**: Latency \< 400ms。
  * **開發者動作**:
      * 你需要確保 `api/seat-config` (自動配位 API) 的回應時間被記錄。
      * **驗證方法**: 檢查 Grafana 是否能單獨拉出 `path="/api/seat-config"` 的 P95 Latency 線圖。
      * **報告內容**: 列出 Latency 的監控 Query：
        ```promql
        histogram_quantile(0.95, sum(rate(flask_http_request_duration_seconds_bucket{path="/api/seat-config"}[5m])) by (le))
        ```

-----

### 第二階段：撰寫技術 Runbook (The "Kill Switch" Strategy)

這是 Task 2 拿高分的關鍵。你需要寫一份「當 SLO 爆炸時，工程師該怎麼救火」的操作手冊。根據你的圖片 `image_58bfbf.png`，你已經有一個很好的範本。

**你的任務是把這張流程圖變成「可執行的程式碼/指令」。**

#### Runbook 劇本：Seat Allocation High Latency (配位系統變慢)

**Step 1: Incident Detection (偵測)**

  * **觸發條件**: 當 Grafana 顯示 `/api/seat-config` 的 P95 Latency 超過 400ms 持續 5 分鐘。
  * **開發者產出**: 截一張 Grafana Alert 設定的圖 (模擬設定即可)。

**Step 2: Root Cause Identification (診斷)**

  * **動作**: 檢查系統資源。
  * **開發者指令**:
      * 查看 CPU 使用率 (你剛剛在 Task 1 加的 `system_cpu_usage_percent`)。
      * 如果 CPU \> 80%：代表演算法太耗效能。
      * 如果 CPU 正常但很慢：代表資料庫 Lock 住或網路問題。

**Step 3: Recovery Procedures (修復 - 重點！)**

  * 這就是你的 Feature Toggle 發揮作用的地方！
  * **情境 A (CPU 過高/演算法卡死)**:
      * **策略**: 降級服務 (Service Degradation)。暫時關閉「智慧配位」，強制切換回「手動選位」，先讓使用者能買票再說。
      * **執行指令 (Action)**:
        修改 `toggles.yaml`：
        ```yaml
        auto_seating:
          value: false  # <--- 將這裡從 true 改成 false
        ```
        然後重新部署或重啟服務。
      * **解釋**: 解釋為什麼這樣做有效（減少計算量，保護系統不崩潰）。

**Step 4: Validation (驗證)**

  * **動作**: 確認 Latency 恢復正常。
  * **開發者產出**: 截一張 Log 圖，證明 `METRIC_SEAT_PAGE_ENTER` 的 `mode` 變成了 `manual`，且系統沒有噴錯。

-----

### 第三階段：定義升級路徑 (Escalation Path)

參考 `image_58bffc.png`，你需要定義如果 Developer 解決不了該怎麼辦。

  * **Level 1 (On-Call Engineer)**: 收到警報，執行上述 Step 3 的 Feature Toggle 切換。
  * **Level 2 (Senior Developer)**: 如果切換 Toggle 後還是慢（例如 DB 整個掛掉），則需要資深開發者介入修復 DB。
  * **Level 3 (PM/Tech Lead)**: 如果服務中斷超過 30 分鐘，影響營收，需由 PM 對外發布公告。

-----

### 總結：Developer 在這份作業的具體產出清單

為了滿足 **"Exceeding"** 等級，請在 PDF 中放入以下內容：

1.  **SLI 定義表**: 對應 `image_58c003.png`，但加上你的 Prometheus Query 語法，證明你是真的用程式碼在監控。
2.  **Runbook 文件**:
      * 標題：`Runbook: High Latency in Smart Seating`
      * 內容：依照上述 **Step 1\~4** 撰寫，重點在於強調使用 **Feature Toggle (`toggles.yaml`)** 作為修復手段。
3.  **截圖證據**:
      * 一張 Grafana 顯示 Latency 的圖 (SLI)。
      * 一張 VS Code 修改 `toggles.yaml` 的截圖 (Recovery Action)。
      * 一張 Log 截圖顯示系統切換回 `manual` 模式 (Validation)。

這樣你就完美結合了提供的教材概念與你的程式碼實作。