# money-saver

  Your Laptop  ──git push──▶  GitHub
  ──auto-pull──▶  Raspberry Pi

           │
  Your Phone
  ──────────────────Tailscale──────────────────▶
  :8501
  Your Laptop (browser)
  ───────Tailscale──────────────────▶  :8501

  ---
  Step 1 — Push the code to GitHub

  On your laptop:
  cd /Users/joehill/Developer/money-saver
  git add .
  git commit -m "ready for pi deployment"
  git remote add origin
  https://github.com/YOUR_USERNAME/money-saver.git
  git push -u origin main
  Make sure .gitignore has finance.db — you don't
  want your bank data in GitHub.

  ---
  Step 2 — Set up the Pi

  Flash Raspberry Pi OS Lite (64-bit, no desktop
  needed) to an SD card using Raspberry Pi Imager.
  In the imager settings, set your WiFi credentials
   and enable SSH before flashing.

  SSH in from your laptop:
  ssh pi@raspberrypi.local

  Install dependencies:
  sudo apt update && sudo apt install -y
  python3-pip python3-venv git sqlite3

  ---
  Step 3 — Clone the repo and install

  git clone
  https://github.com/YOUR_USERNAME/money-saver.git
  cd money-saver
  python3 -m venv venv
  source venv/bin/activate
  pip install -r requirements.txt

  Copy your .env file across from your laptop
  (never commit this):
  # Run this on your laptop, not the Pi
  scp /Users/joehill/Developer/money-saver/.env
  pi@raspberrypi.local:~/money-saver/.env

  Copy the database across too if you want your
  existing data:
  scp
  /Users/joehill/Developer/money-saver/finance.db
  pi@raspberrypi.local:~/money-saver/finance.db

  ---
  Step 4 — Run as a service (so it starts on boot)

  On the Pi, create a systemd service:
  sudo nano /etc/systemd/system/money-saver.service

  Paste this:
  [Unit]
  Description=Money Saver Dashboard
  After=network.target

  [Service]
  User=pi
  WorkingDirectory=/home/pi/money-saver
  EnvironmentFile=/home/pi/money-saver/.env
  ExecStart=/home/pi/money-saver/venv/bin/streamlit
   run app.py --server.port 8501 --server.address
  0.0.0.0
  Restart=always

  [Install]
  WantedBy=multi-user.target

  Enable and start it:
  sudo systemctl daemon-reload
  sudo systemctl enable money-saver
  sudo systemctl start money-saver

  ---
  Step 5 — Tailscale (access from anywhere)

  Install Tailscale on the Pi:
  curl -fsSL https://tailscale.com/install.sh | sh
  sudo tailscale up

  Install the Tailscale app on your phone and
  laptop too, sign into the same account. The Pi
  will appear in your Tailscale network with a name
   like raspberrypi. You can then access the
  dashboard from anywhere at:
  http://raspberrypi:8501

  ---
  Step 6 — Auto-deploy when you push from your
  laptop

  On the Pi, create a deploy script:
  nano /home/pi/money-saver/deploy.sh
  #!/bin/bash
  cd /home/pi/money-saver
  git pull origin main
  source venv/bin/activate
  pip install -r requirements.txt -q
  sudo systemctl restart money-saver
  chmod +x /home/pi/money-saver/deploy.sh

  Then whenever you push new code from your laptop,
   SSH into the Pi and run:
  ssh pi@raspberrypi ~/money-saver/deploy.sh

  Or you can make it fully automatic with a GitHub
  webhook or a cron job that polls for changes —
  but manual deploy is fine to start with.

  ---
  Summary of what lives where

  Thing: Code
  Where: GitHub + Pi (synced)
  ────────────────────────────────────────
  Thing: .env (credentials)
  Where: Pi only, never GitHub
  ────────────────────────────────────────
  Thing: finance.db (your data)
  Where: Pi only, never GitHub
  ────────────────────────────────────────
  Thing: Streamlit app
  Where: Running on Pi 24/7
  ────────────────────────────────────────
  Thing: Access
  Where: Via Tailscale from anywhere
