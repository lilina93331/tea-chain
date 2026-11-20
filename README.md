# 茶序｜連鎖飲料店分散式營運平台

桃園三間門市與台北、台中、台南各一間門市共用品牌菜單和操作介面。每間店有自己的網站、店長密碼、特色菜單與收銀資料庫。老闆在總部網站選擇營業日，即可查看各店營收、交易筆數與售出杯數。

## 在 Ubuntu 部署

以 **Ubuntu 24.04 LTS、可使用 sudo 的帳號** 為例。首次建置需要連網下載專案、容器映像及 Python 套件。已安裝 Docker Engine 和 Compose v2 的主機，可直接從第 2 步開始。以下指令都在 Ubuntu 終端機執行，也可使用 VS Code 的整合式終端機。

### 1. 安裝工具

全新 Ubuntu 主機可使用下列指令加入 Docker 官方套件來源。已經有 Docker 的主機可先用 `sudo docker version`、`sudo docker compose version` 檢查。

~~~bash
sudo apt-get update
sudo apt-get install -y git python3 ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu noble stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo docker compose version
~~~

其他 Ubuntu 版本與既有套件的相容性，請參閱 [Docker 官方 Ubuntu 安裝說明](https://docs.docker.com/engine/install/ubuntu/)。

### 2. 下載、建置與啟動

~~~bash
git clone https://github.com/lilina93331/tea-chain.git
cd tea-chain
python3 manage.py init
sudo docker compose config --quiet
sudo docker compose build hq
sudo docker compose up -d --wait --wait-timeout 120
sudo docker compose ps
python3 tests/check_stack.py
~~~

`init` 讀取 `stores.json`，建立 `compose.yaml`、各節點的環境設定與隨機密碼。重跑會保留既有金鑰。七個服務共用一次建置的映像，每間店各有一個持久化磁碟區。最後一行檢查全部公開菜單及總部對各分店的連線，成功時會看到 `OK HQ: 6/6 branches reporting`。

### 3. 開啟網站並登入

在 **Ubuntu 主機上的瀏覽器** 開啟下列網址。顧客可直接瀏覽分店菜單。店長點右上角「店長登入」，老闆則在總部選「老闆登入」。

| 網站 | 服務代號 | 本機網址 |
| --- | --- | --- |
| 品牌總部 | `hq` | [開啟總部](http://127.0.0.1:8100) |
| 桃園一店 | `taoyuan-1` | [開啟門市](http://127.0.0.1:8101) |
| 桃園二店 | `taoyuan-2` | [開啟門市](http://127.0.0.1:8102) |
| 桃園三店 | `taoyuan-3` | [開啟門市](http://127.0.0.1:8103) |
| 台北店 | `taipei` | [開啟門市](http://127.0.0.1:8104) |
| 台中店 | `taichung` | [開啟門市](http://127.0.0.1:8105) |
| 台南店 | `tainan` | [開啟門市](http://127.0.0.1:8106) |

在自己的終端機查詢所需角色的密碼。每間店長只需領取自己門市的密碼，總部密碼交由老闆保管。網頁登入效期為八小時。

~~~bash
python3 manage.py password taipei
python3 manage.py password hq
~~~

若 Ubuntu 是遠端主機，使用 VS Code Remote SSH 的 **Ports／連接埠** 面板轉送 8100–8106，或在自己電腦執行以下指令，把 `user@server` 換成 Ubuntu 的 SSH 帳號與主機。保持連線，再用自己電腦的瀏覽器開啟上表網址。

~~~bash
ssh -N -L 8100:127.0.0.1:8100 -L 8101:127.0.0.1:8101 -L 8102:127.0.0.1:8102 -L 8103:127.0.0.1:8103 -L 8104:127.0.0.1:8104 -L 8105:127.0.0.1:8105 -L 8106:127.0.0.1:8106 user@server
~~~

### 4. 驗收一筆營收

在剛初始化的空白部署中，依序操作即可核對門市隔離和總部加總。這會寫入一筆示範交易，正式營業資料請使用後面的唯讀檢查。

1. 在台北店確認五款品牌飲品，再登入店長後台，於「新增飲品」加入「桂花烏龍」，單價 80 元。
2. 開另一個分頁瀏覽台南店。台北的桂花烏龍只出現在台北店的「本店限定」。
3. 回台北店「收銀」，輸入開心奶茶 2 杯、桂花烏龍 1 杯，完成收款後按「確認收款並入帳」。交易總額為 **220 元**。
4. 開啟台北店「營收」，選今天，應顯示 1 筆、3 杯、220 元。品項銷售額分別是 140 元與 80 元。
5. 登入總部，選同一個營業日。台北列與全店總計均為 220 元，其他五店為 0 元。店長密碼只能登入對應門市。
6. 可在示範環境暫停台北服務，按總部的「重新查詢」。畫面顯示 5／6 間已回報、台北「暫無回報」。恢復後再查，台北的 220 元會重新納入。

~~~bash
sudo docker compose stop taipei
# 在總部查看部分門市報表後，再啟動台北店
sudo docker compose start taipei
~~~

## 固定菜單與營運規則

| 全店共通品項 | 售價（新臺幣／杯） |
| --- | ---: |
| 開心奶茶 | 70 |
| 快樂紅茶 | 55 |
| 烏龍綠茶 | 60 |
| 茉莉花茶 | 70 |
| 甘蔗青茶 | 65 |

品牌菜單來自單一版本控管檔案 `tea/catalog.json`。店長可新增本店特色飲品與價格。收銀以門市伺服器的定價計算，逐項保存成交時的品名、單價與杯數。營業日按台灣時間 00:00 至次日 00:00（UTC+8）切分，營收為店長確認已收款的交易金額。平台提供收銀登錄，金流由店家既有收款方式處理。

## 架構與故障行為

~~~mermaid
flowchart LR
  owner[老闆] --> hq[總部報表服務]
  public[顧客／各店店長] --> shop[六個獨立門市網站]
  hq -->|並行 HTTP 查詢／各店唯讀金鑰| shop
  shop -->|本店交易與特色菜單| db[(六個獨立 SQLite 磁碟區)]
~~~

- **門市自治**　每間店以獨立容器提供同一套網站，只掛載自己的資料庫。特色飲品、收銀、管理者驗證都在本店完成。總部停機時，各店仍可營業。
- **總部彙整**　總部持有六組分店報表金鑰。在每次查詢時並行向門市讀取同一營業日的已提交資料。逾時或無法驗證的門市會逐店標示，畫面只加總已回報資料。復線後重新查詢即可涵蓋離線期間的交易。不同門市的數字反映各自處理查詢時的資料快照。
- **交易一致性**　交易與明細在同一個 SQLite 交易提交。瀏覽器送出收款前會保存交易識別碼；遇到連線中斷，可在原分頁重新整理並「確認上筆交易」。伺服器對相同編號及內容回傳原收據，對同編號不同內容回傳衝突。
- **權限與網路**　公開端點提供菜單。店長權杖只在本店有效，老闆權杖用於總部查詢。分店報表金鑰僅能讀取該店的內部報表。Compose 為每間店與總部建立一個專用網路，網站連接埠預設綁定主機的 `127.0.0.1`。

## 將六間門市公開為獨立 HTTPS 網站

適用於有公網 IP 與自有網域的 Ubuntu 主機。單機部署將七個服務放在同一台主機上；要抵抗整台主機中斷，可將門市移到不同主機。

1. 為 `hq`、`taoyuan-1`、`taoyuan-2`、`taoyuan-3`、`taipei`、`taichung`、`tainan` 建立指向主機的 A 記錄。有提供 IPv6 時，再設定對應 AAAA。允許對外 TCP 80 與 443。
2. 依 [Caddy 的 Ubuntu 安裝說明](https://caddyserver.com/docs/install#debian-ubuntu-raspbian) 在宿主機安裝 Caddy。下例以新主機為例，把 `tea.your-domain.tw` 換成實際管理的網域。已有 Caddy 網站的主機，請將產出的站台區塊併入原設定。
3. 執行以下指令。DNS 生效後，可用 `https://taipei.tea.your-domain.tw` 開啟台北店。總部與其他門市各有自己的子網域。

~~~bash
sed 's/tea\.example\.com/tea.your-domain.tw/g' deploy/Caddyfile.example > /tmp/tea-Caddyfile
sudo caddy validate --config /tmp/tea-Caddyfile --adapter caddyfile
sudo install -m 0644 /tmp/tea-Caddyfile /etc/caddy/Caddyfile
sudo systemctl reload caddy
~~~

範本會將各子網域導向對應門市，且封住外網的 `/internal/*`。總部在 Docker 私有網路內查詢門市。HTTPS 憑證的簽發條件見 [Caddy 自動 HTTPS 說明](https://caddyserver.com/docs/automatic-https)。

## 擴充分店與跨主機部署

**新增加盟店**　在 `stores.json` 陣列加入一筆唯一的門市代號、店名與本機埠號，例如 `{"id":"hsinchu","name":"新竹店","port":8107}`。接著執行下列指令，再為新店補上 DNS 與 Caddy 路由。沿用既有門市代號即可保留對應資料庫與密碼。

~~~bash
python3 manage.py init
sudo docker compose up -d --wait
python3 tests/check_stack.py
python3 manage.py password hsinchu
~~~

**不同主機**　以下以把台北節點部署在另一台 Ubuntu 為例。先在總部產生一次設定，兩端使用同一版程式碼。

1. 在總部的 `stores.json` 為台北加入 `"report_url":"https://taipei-internal.your-domain.tw"`，填入總部容器能連線的實際私網 HTTPS 網址。再執行 `python3 manage.py init`。維持該店的 `REPORT_KEY` 以便雙方驗證。
2. 在台北主機複製本專案，安裝 Docker，執行 `sudo docker build -t tea-chain-service:local .`。將總部產出的 `.tea/env/taipei.compose.yaml` 和 `.tea/env/taipei.env` 透過 SSH 傳到台北主機的同一個私有目錄。這組設定只含台北節點。在該目錄執行 `sudo docker compose -f taipei.compose.yaml up -d --wait`。若遷移既有門市，先停收、備份與移轉該店磁碟區，再切換網址。
3. 台北的公開 HTTPS 站台指向台北主機的 `127.0.0.1:8104`。另設僅允許總部透過 VPN／私網連入的 HTTPS 站台，將 `/internal/report` 代理到同一個連接埠。兩個站台的憑證都須受呼叫方信任。
4. 總部用 `sudo docker compose up -d --wait hq taoyuan-1 taoyuan-2 taoyuan-3 taichung tainan` 啟動留在本機的節點。每個門市代號只運行一個收銀節點。登入總部確認台北已回報，並核對移轉前後金額。

## 維運、測試與排錯

| 操作 | 在專案目錄執行 |
| --- | --- |
| 查看容器與健康狀態 | `sudo docker compose ps` |
| 追蹤台北服務日誌 | `sudo docker compose logs --tail=50 -f taipei` |
| 唯讀檢查單機部署的菜單及六店彙整 | `python3 tests/check_stack.py` |
| 查看單一服務健康狀態 | `curl -fsS http://127.0.0.1:8104/health` |
| 停止服務並保留磁碟區 | `sudo docker compose down` |
| 拉取更新、保留金鑰和門市資料 | `git pull --ff-only`，然後重跑第 2 步的 `init`、`build hq` 和 `up` |
| 在暫存資料庫執行整合測試 | `python3 -m unittest discover -s tests -v` |

**備份**　`.tea/keys/` 含登入密碼及服務金鑰，請保存在僅管理者可讀的加密備份中。每家門市的交易都在獨立的具名磁碟區；重啟或重新建立容器會保留資料。以下在店內服務運行時使用 SQLite 線上備份，產生一致的台北資料庫副本。其他店將 `taipei` 換成相應代號。含 `-v` 的 `docker compose down -v` 會清除磁碟區。

~~~bash
umask 077
mkdir -p .tea/backup
sudo docker compose exec -T taipei python -c "import sqlite3; src=sqlite3.connect('/data/sales.sqlite'); dst=sqlite3.connect('/tmp/taipei-backup.sqlite'); src.backup(dst); dst.close(); src.close()"
sudo docker compose cp taipei:/tmp/taipei-backup.sqlite .tea/backup/taipei.sqlite
~~~

**常見問題**

- **連接埠遭占用**　用 `sudo ss -ltnp` 確認 8100–8106。門市對外埠可在 `stores.json` 調整，再重新執行 `init` 和 `up`；代理與 SSH 轉送埠也要跟著更新。
- **瀏覽器無法連線**　先在 Ubuntu 執行 `curl` 健康檢查。從其他電腦存取時，採用第 3 步的 SSH 轉送或 HTTPS 子網域。
- **總部出現「暫無回報」**　檢查該容器狀態、日誌、網路和報表金鑰。若曾刪除或還原 `.tea`，請確認總部與對應分店使用同一次設定產生的金鑰。
- **想用 VS Code 修改程式**　在專案目錄執行 `code .`。安裝 Python 3.10 以上即可用 `python3 manage.py init`、`python3 manage.py dev` 在本機啟動七個開發程序，按 Ctrl+C 結束。此模式使用 `.tea/data/` 的獨立測試資料，與 Compose 二擇一啟動以免連接埠衝突。Ubuntu 容器部署使用 [Waitress WSGI 伺服器](https://docs.pylonsproject.org/projects/waitress/en/latest/runner.html)。

`tea/app.py` 處理權限與跨店報表，`tea/ledger.py` 處理本店資料與交易，`tea/web/` 是門市與總部的介面。可在 GitHub 的 Actions 分頁查看 Ubuntu 建置、瀏覽器收銀與容器重建驗證的執行結果。
