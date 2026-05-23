# GALA Vacancy Watcher

GALA賃貸の物件ページを定期チェックし、空室一覧に新しい部屋が出たらメール通知するPythonスクリプトです。

## Target

https://www.gala-chintai.jp/bukken/?detail=1361

## Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export SMTP_HOST="smtp.gmail.com"
export SMTP_PORT="587"
export SMTP_USER="your-email@gmail.com"
export SMTP_PASSWORD="your-app-password"
export MAIL_TO="your-email@gmail.com"
export MAIL_FROM="your-email@gmail.com"
export NOTIFY_ON_FIRST_RUN="true"

python src/main.py
