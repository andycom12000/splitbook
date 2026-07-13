# TripSplit 部署指南

## 前置需求
- Ubuntu 22.04+ (DigitalOcean Droplet)
- Python 3.11+
- Nginx
- Let's Encrypt (certbot)

## 部署步驟

1. 複製程式碼到伺服器
   git clone <repo> /opt/tripsplit

2. 建立虛擬環境
   cd /opt/tripsplit
   python3 -m venv .venv
   .venv/bin/pip install -r requirements.txt

3. 設定環境變數
   cp .env.example .env
   nano .env  # 填入 Notion token 和 DB IDs

4. 設定 Nginx
   cp deploy/nginx.conf /etc/nginx/sites-available/tripsplit
   ln -s /etc/nginx/sites-available/tripsplit /etc/nginx/sites-enabled/
   # 修改 server_name 為你的網域
   # 設定 basic auth:
   htpasswd -c /etc/nginx/.htpasswd admin
   nginx -t && systemctl reload nginx

5. 設定 SSL
   certbot --nginx -d your-domain.com

6. 啟動服務
   cp deploy/tripsplit.service /etc/systemd/system/
   systemctl enable tripsplit
   systemctl start tripsplit

7. 驗證
   curl https://your-domain.com/
