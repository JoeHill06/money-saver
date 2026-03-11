import streamlit as st

st.set_page_config(page_title="Deploy", page_icon="🚀", layout="wide")

st.title("Deploy to Raspberry Pi")

st.markdown("""
### Pushing updates from your laptop to the Pi

**1. Push changes to GitHub (on your laptop):**
```bash
git add .
git commit -m "your message"
git push
```

**2a. Pull and restart on the Pi (from your laptop):**
```bash
ssh joehill@joespi.local "cd money-saver && git pull && sudo systemctl restart money-saver"
```

**2b. Pull and restart on the Pi (if already SSH'd in):**
```bash
cd ~/money-saver
git pull
sudo systemctl restart money-saver
```

---

### Notes
- Your `.env` and `finance.db` are never touched by git pulls — they're safe
- The app will be back up at [http://joespi.local:8501](http://joespi.local:8501) within a few seconds of restarting
- To check the app is running: `sudo systemctl status money-saver`
- To view logs: `journalctl -u money-saver -n 50`
""")
