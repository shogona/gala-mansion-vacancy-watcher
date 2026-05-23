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
```

## External cron

このリポジトリでは GitHub Actions の `workflow_dispatch` を外部 cron から叩いて定期実行します。

`cron` は「決まった時刻や間隔で処理を起動する仕組み」です。たとえば `*/15 * * * *` は「15分ごと」を意味します。

GitHub REST API endpoint:

```text
POST https://api.github.com/repos/shogona/gala-mansion-vacancy-watcher/actions/workflows/scheduled-vacancy-check.yml/dispatches
```

Request headers:

```text
Accept: application/vnd.github+json
Authorization: Bearer <YOUR_GITHUB_TOKEN>
X-GitHub-Api-Version: 2022-11-28
Content-Type: application/json
```

Request body:

```json
{"ref":"main"}
```

GitHub token は fine-grained personal access token を使い、このリポジトリだけに限定します。権限は `Actions: Read and write` と `Contents: Read-only` を付けます。token は README やコードには書かず、外部 cron サービス側の secret/header 設定にだけ保存します。
