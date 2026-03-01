# Money Saver 💰

A personal finance dashboard that connects to your real bank accounts via TrueLayer and gives you a live view of your spending, habits, budgets, and savings goals.

Built with Streamlit + SQLite. Designed to run on a Raspberry Pi so it's always on and accessible from your phone or laptop anywhere via Tailscale.

![Overview page showing spending capacity, merchant breakdown, and trend chart]

---

## Features

- **Live bank data** — connects to your real accounts via TrueLayer (Monzo, Barclays, HSBC, Lloyds, and more)
- **Multiple banks** — connect as many accounts as you like
- **Spending capacity** — see what you can spend today / this week / this month / this year based on your income, bills, and savings goals
- **Habits** — category and merchant breakdowns, trend charts, day-of-week analysis
- **Transactions** — full filterable table with bulk editing, category tagging, and shared splits
- **Budget** — set income sources, fixed outgoings, and savings goals
- **Auto-sync** — fetches new transactions every 5 minutes in the background
- **Merchant normalisation** — cleans up raw bank descriptions into readable names
- **Auto-categorisation** — automatically tags common merchants

---

## Prerequisites

- Python 3.10+
- A free [TrueLayer](https://truelayer.com) developer account
- Your bank must be supported by TrueLayer — check the full list at [truelayer.com/supported-banks](https://truelayer.com/supported-banks)

---

## Step 1 — Create a TrueLayer account

1. Go to [console.truelayer.com](https://console.truelayer.com) and sign up for free
2. Create a new application — name it anything you like
3. Under **Allowed redirect URIs**, add: `http://localhost:3000/callback`
4. Switch the app to **Live** mode (not Sandbox) to connect real banks
5. Copy your **Client ID** and **Client Secret** — you'll need these in the next step

---

## Step 2 — Run locally

```bash
# Clone the repo
git clone https://github.com/JoeHill06/money-saver.git
cd money-saver

# Create a virtual environment and install dependencies
python3 -m venv venv
source venv/bin/activate       # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Create your .env file from the template
cp .env.example .env
```

Open `.env` and fill in your TrueLayer credentials:

```
TRUELAYER_CLIENT_ID=your-client-id-here
TRUELAYER_CLIENT_SECRET=your-client-secret-here
TRUELAYER_REDIRECT_URI=http://localhost:3000/callback
USE_SANDBOX=false
```

Then start the app:

```bash
streamlit run app.py
```

Open [http://localhost:8501](http://localhost:8501) in your browser, click **Connect Bank**, and follow the OAuth flow to link your bank account.

---

## Step 3 — Deploy to Raspberry Pi (optional but recommended)

Running on a Pi means the app is always on, always syncing, and accessible from your phone from anywhere.

### 3a — Flash the Pi

1. Download [Raspberry Pi Imager](https://www.raspberrypi.com/software/)
2. Choose **Raspberry Pi OS Lite (64-bit)** — no desktop needed
3. Click the settings gear icon and:
   - Set a hostname (e.g. `moneysaver`)
   - Enable SSH
   - Set your WiFi credentials
4. Flash the SD card, insert into Pi, and power on

### 3b — SSH in and install dependencies

```bash
ssh pi@moneysaver.local

sudo apt update && sudo apt install -y python3-pip python3-venv git sqlite3
```

### 3c — Clone the repo and configure

```bash
git clone https://github.com/JoeHill06/money-saver.git
cd money-saver
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Copy your `.env` file from your laptop to the Pi (run this on your laptop, not the Pi):

```bash
scp ~/.../money-saver/.env pi@moneysaver.local:~/money-saver/.env
```

If you already have a database with existing data, copy that across too:

```bash
scp ~/.../money-saver/finance.db pi@moneysaver.local:~/money-saver/finance.db
```

### 3d — Run as a service (starts automatically on boot)

On the Pi, create a systemd service:

```bash
sudo nano /etc/systemd/system/money-saver.service
```

Paste the following:

```ini
[Unit]
Description=Money Saver Dashboard
After=network.target

[Service]
User=pi
WorkingDirectory=/home/pi/money-saver
EnvironmentFile=/home/pi/money-saver/.env
ExecStart=/home/pi/money-saver/venv/bin/streamlit run app.py --server.port 8501 --server.address 0.0.0.0
Restart=always

[Install]
WantedBy=multi-user.target
```

Enable and start it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable money-saver
sudo systemctl start money-saver

# Check it's running
sudo systemctl status money-saver
```

The dashboard is now running at `http://moneysaver.local:8501` on your local network.

---

## Step 4 — Access from anywhere with Tailscale

Tailscale creates a private VPN between your devices so you can reach the Pi from your phone or laptop even when you're away from home.

### On the Pi:

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

Follow the link it prints to authenticate the Pi with your Tailscale account.

### On your phone and laptop:

1. Install the Tailscale app ([iOS](https://apps.apple.com/app/tailscale/id1470499037) / [Android](https://play.google.com/store/apps/details?id=com.tailscale.ipn.android) / [desktop](https://tailscale.com/download))
2. Sign in with the same Tailscale account
3. The Pi will appear in your network — open your browser and go to:

```
http://moneysaver:8501
```

You now have access to your finance dashboard from anywhere in the world.

---

## Step 5 — Push updates from your laptop to the Pi

Create a deploy script on the Pi:

```bash
nano /home/pi/money-saver/deploy.sh
```

Paste:

```bash
#!/bin/bash
cd /home/pi/money-saver
git pull origin main
source venv/bin/activate
pip install -r requirements.txt -q
sudo systemctl restart money-saver
echo "Deployed."
```

Make it executable:

```bash
chmod +x /home/pi/money-saver/deploy.sh
```

Now whenever you push new code from your laptop, just run:

```bash
ssh pi@moneysaver ~/money-saver/deploy.sh
```

The Pi pulls the latest code and restarts the app automatically.

---

## What lives where

| Thing | Where |
|---|---|
| Code | GitHub + Pi (synced via git) |
| `.env` (credentials) | Pi only — **never commit this** |
| `finance.db` (your bank data) | Pi only — **never commit this** |
| Streamlit app | Running on Pi 24/7 |
| Access | Via Tailscale from anywhere |

---

## Troubleshooting

**App won't start on Pi**
```bash
sudo systemctl status money-saver   # check for errors
journalctl -u money-saver -n 50     # view recent logs
```

**Can't connect bank**
- Make sure `http://localhost:3000/callback` is listed as an allowed redirect URI in the TrueLayer console
- Check your `.env` has the correct Client ID and Secret
- Make sure `USE_SANDBOX=false` for real banks

**Transactions not updating**
- Hit the **Sync now** button on the Overview page
- Check the last sync status shown next to the button
- Traditional banks (Barclays, HSBC, etc.) can take 30–60 minutes to push new transactions regardless of how often you poll

**Database issues**
```bash
sqlite3 ~/money-saver/finance.db "SELECT COUNT(*) FROM transactions;"
```
