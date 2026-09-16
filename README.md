# Alibaba Cloud DirectMail Multi-Region Automation Agent

A production-grade, secure, multi-region email automation platform connecting directly to Alibaba Cloud DirectMail APIs across **Singapore (`ap-southeast-1`)**, **Germany / Frankfurt (`eu-central-1`)**, and the **United States (`us-east-1`)**.

---

## Key Features

- **Multi-Region Routing**: Fully isolated credentials and direct RPC endpoint routing for Singapore, Frankfurt, and Virginia.
- **Server-Side Security**: Alibaba Cloud AccessKey ID and Secret remain strictly on the backend; secrets are never sent to the browser or exposed in error logs.
- **Independent Scheduler**: Background Python daemon continuously executes scheduled email jobs independently of browser activity.
- **Bulk Campaign Engine**: Supports manual recipient entry, list pasting, and CSV file upload with live syntax validation and duplicate detection.
- **Pre-Flight Safety Confirmation**: Requires explicit confirmation before sending bulk campaigns, displaying recipient count, sender, region, and schedule.
- **Safe Retries & Backoff**: Exponential backoff (5s, 20s, 60s) for transient errors (e.g. throttling, network timeouts) without duplicate deliveries.
- **Full Audit History**: Persistent SQLite database logging RequestId, EnvId, timestamps, status transitions, and sanitized API gateway responses.
- **Zero-Config Test Sandbox**: Integrated offline test simulation mode allows full feature testing without consuming paid Alibaba quota.

---

## 1. Project Structure

```
alibaba_email_agent/
├── backend/
│   ├── __init__.py
│   ├── config.py              # Regional endpoints & credential resolution
│   ├── database.py            # SQLite schema, indices, CRUD operations
│   ├── directmail.py          # HMAC-SHA1 RPC signer & DirectMail client
│   ├── router.py              # Regional routing & idempotent execution
│   ├── scheduler.py           # Persistent background worker & retry loop
│   ├── bulk_processor.py      # Concurrency & rate-limiting for campaigns
│   ├── validator.py           # Email syntax, timezone & CSV parser
│   └── models.py              # Pydantic schemas for REST API
├── frontend/
│   ├── index.html             # Single-Page Dashboard with 8 views
│   ├── css/
│   │   └── style.css          # Custom badges, animations, and dark theme
│   └── js/
│       └── app.js             # State management, forms, modals & polling
├── tests/
│   ├── test_signer.py         # Signature & canonical query unit tests
│   ├── test_validator.py      # Email syntax & CSV parsing tests
│   ├── test_router_and_scheduler.py # Idempotency, retries & scheduler tests
│   └── test_api.py            # FastAPI REST endpoints integration tests
├── .env.example               # Sanitized environment template
├── requirements.txt           # Python dependencies
├── run.py                     # Application launcher
└── README.md                  # Complete documentation
```

---

## 2. Required Environment Variables

Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

Configure your Alibaba Cloud credentials per region:

```env
# Singapore Region (ap-southeast-1)
ALIBABA_SG_ACCESS_KEY_ID=your_sg_key_id
ALIBABA_SG_ACCESS_KEY_SECRET=your_sg_key_secret

# Germany / Frankfurt Region (eu-central-1)
ALIBABA_GERMANY_ACCESS_KEY_ID=your_germany_key_id
ALIBABA_GERMANY_ACCESS_KEY_SECRET=your_germany_key_secret

# United States Region (us-east-1)
ALIBABA_US_ACCESS_KEY_ID=your_us_key_id
ALIBABA_US_ACCESS_KEY_SECRET=your_us_key_secret

# Mode: 'true' for offline sandbox testing, 'false' for live API calls
TEST_MODE=true

# Preferences
DEFAULT_TIMEZONE=Asia/Kolkata
RATE_LIMIT_QPS=5.0
MAX_RETRIES=3
PORT=8000
```

> **Security Note:** Never place real credentials into source control. The `.env` file should remain in `.gitignore`.

---

## 3. Official Region Endpoints Reference

| Region | Region ID | DirectMail RPC Endpoint | Auth Key Prefix |
| :--- | :--- | :--- | :--- |
| **Singapore** | `ap-southeast-1` | `dm.ap-southeast-1.aliyuncs.com` | `ALIBABA_SG_*` |
| **Germany (Frankfurt)** | `eu-central-1` | `dm.eu-central-1.aliyuncs.com` | `ALIBABA_GERMANY_*` |
| **United States** | `us-east-1` | `dm.us-east-1.aliyuncs.com` | `ALIBABA_US_*` |

---

## 4. Local Setup & Running Instructions

### Step 1: Install Dependencies

Ensure Python 3.10+ is installed, then run:

```bash
pip install -r requirements.txt
```

### Step 2: Run Automated Tests

Run the complete test suite (22 unit and integration tests):

```bash
python -m unittest discover tests
```

### Step 3: Start the Application

```bash
python run.py
```

The application will start on `http://127.0.0.1:8000`.

- **Web Dashboard**: [http://127.0.0.1:8000](http://127.0.0.1:8000)
- **Interactive OpenAPI Docs**: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

---

## 5. How to Test Each Region

### In Test Sandbox Mode (`TEST_MODE=true`)
1. Open the dashboard at `http://127.0.0.1:8000`.
2. Navigate to **Send Email**.
3. Select **🇸🇬 Singapore**:
   - Sender: `notifications-sg@directmail.example.com`
   - Recipient: `test@company.com`
   - Subject: `Singapore Test Email`
   - Click **Send Now**. Inspect the returned `RequestId` in the quick activity bar.
4. Select **🇩🇪 Germany**:
   - Sender: `notifications-de@directmail.example.com`
   - Recipient: `test@company.de`
   - Click **Send Now**. Verify region is marked as Germany.
5. Select **🇺🇸 United States**:
   - Sender: `notifications-us@directmail.example.com`
   - Click **Send Now**.
6. Switch to **Email History** to verify all three entries are logged with their respective region tags.

### Testing Error Handling & Retries
- Send an email with subject containing `[SIMULATE_RETRY]`: the system will trigger a transient 503 error, schedule an automatic exponential backoff retry, and log the attempt.
- Send an email with subject containing `[SIMULATE_FAIL]`: the system will reject with `InvalidToAddress.NotFound` and record it in **Failed Emails**, where you can click **Retry Now**.

### In Live Mode (`TEST_MODE=false`)
1. In your `.env` file, supply your actual `ALIBABA_SG_ACCESS_KEY_ID` and `ALIBABA_SG_ACCESS_KEY_SECRET`.
2. Ensure your sender domain and sender address are verified in the Alibaba Cloud DirectMail console for that region.
3. Set `TEST_MODE=false`.
4. Send an email and verify delivery in your inbox.

---

## 6. How to Deploy in Production

### Option A: Systemd / Linux VM (Ubuntu / Debian)
1. Clone the repository and install dependencies:
   ```bash
   git clone <repo-url> /opt/alibaba_email_agent
   cd /opt/alibaba_email_agent
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
2. Create systemd service `/etc/systemd/system/email-agent.service`:
   ```ini
   [Unit]
   Description=Alibaba Cloud DirectMail Automation Agent
   After=network.target

   [Service]
   User=www-data
   WorkingDirectory=/opt/alibaba_email_agent
   EnvironmentFile=/opt/alibaba_email_agent/.env
   ExecStart=/opt/alibaba_email_agent/venv/bin/python run.py
   Restart=always
   RestartSec=5

   [Install]
   WantedBy=multi-user.target
   ```
3. Enable and start:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now email-agent
   ```

### Option B: Docker Container
Create a `Dockerfile`:
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["python", "run.py"]
```
Build and run:
```bash
docker build -t alibaba-email-agent .
docker run -d -p 8000:8000 --env-file .env alibaba-email-agent
```

### Option C: Reverse Proxy (Nginx)
Configure Nginx to reverse proxy to port 8000 with SSL:
```nginx
server {
    listen 443 ssl http2;
    server_name mail.yourcompany.com;

    ssl_certificate /etc/letsencrypt/live/mail.yourcompany.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/mail.yourcompany.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

---

## 7. Known Alibaba Cloud DirectMail Limitations

1. **Regional Resource Isolation**: Sender addresses and domains created in one region (e.g. Singapore) cannot be used in another region (e.g. Frankfurt or US). Each region requires separate domain verification (SPF, DKIM, DMARC, CNAME) in the respective regional console.
2. **Attachments**: Alibaba Cloud DirectMail's `SingleSendMail` HTTP API does not support file attachments. If attachments are strictly required, Alibaba Cloud recommends SMTP or OSS pre-signed link references in the email body.
3. **Daily Quotas & QPS**: Standard DirectMail accounts start with daily quotas (e.g. 2,000 emails/day) and concurrency limits. The application's rate limiter should be tuned (default: 5.0 QPS) to avoid `Rejected.Throttling` errors.
4. **BatchSendMail vs SingleSendMail**: Alibaba Cloud's native `BatchSendMail` requires pre-created recipient lists and pre-approved templates inside the Alibaba Cloud console. For dynamic campaigns, the application uses rate-limited `SingleSendMail` workers to allow arbitrary body text and custom recipient lists without console pre-registration.
