#!/bin/bash
set -e

USER=$(whoami)
DIR=$(cd "$(dirname "$0")" && pwd)

echo "Setting up Money Saver..."

# Install system dependencies
sudo apt update && sudo apt install -y python3-pip python3-venv sqlite3

# Create virtual environment and install dependencies
python3 -m venv "$DIR/venv"
source "$DIR/venv/bin/activate"
pip install -r "$DIR/requirements.txt" -q

# Create .env if it doesn't exist
if [ ! -f "$DIR/.env" ]; then
    cp "$DIR/.env.example" "$DIR/.env"
    echo ""
    echo "Created .env from template — fill in your TrueLayer credentials:"
    echo "  nano $DIR/.env"
    echo ""
fi

# Create systemd service
sudo tee /etc/systemd/system/money-saver.service > /dev/null << EOF
[Unit]
Description=Money Saver Dashboard
After=network.target

[Service]
User=$USER
WorkingDirectory=$DIR
EnvironmentFile=$DIR/.env
ExecStart=$DIR/venv/bin/streamlit run app.py --server.port 8501 --server.address 0.0.0.0
Restart=always

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable money-saver
sudo systemctl start money-saver

echo ""
echo "Done! Money Saver is running at http://$(hostname).local:8501"
