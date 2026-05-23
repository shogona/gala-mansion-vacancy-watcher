# =========================================================
# gala-vacancy-watcher / main.py
#
# 概要:
#   ガーラ・プレシャス渋谷の賃貸サイトを定期的にスクレイピングし、
#   新しい空室が出たらメールで通知するスクリプト。
#   GitHub Actions などで定期実行することを想定している。
#
# 動作フロー:
#   1. 賃貸サイトの HTML を取得する
#   2. HTML から空室情報（部屋一覧）を抽出する
#   3. 前回チェック時の状態（state.json）と比較する
#   4. 新しく追加された部屋があればメールで通知する
#   5. 最新の状態を state.json に保存する
# =========================================================

import json
import os
import smtplib
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

# HTTP リクエストを送るライブラリ
import requests
# HTML を解析するライブラリ（pip install beautifulsoup4 で導入）
from bs4 import BeautifulSoup


# ---------- 定数 ----------

# 空室一覧ページの URL（チェック対象の物件ページ）
TARGET_URL = "https://www.gala-chintai.jp/bukken/?detail=1361"

# 詳細ページの相対 URL を絶対 URL に変換するときのベース
BASE_URL = "https://www.gala-chintai.jp"

# 前回チェック時の空室情報を保存するファイルパス
# このファイルが存在しなければ「初回実行」とみなす
STATE_PATH = Path("state.json")

# 日本標準時（UTC+9）のタイムゾーン定義
JST = timezone(timedelta(hours=9))


# ---------- データクラス ----------

@dataclass
class Room:
    """1 部屋分の空室情報を保持するデータクラス。

    サイトの表から読み取った各カラムをフィールドに対応させている。
    dataclass を使うことで、__init__ や __repr__ を自動生成できる。
    """
    room_id: str        # 部屋を一意に識別する ID（URL の add= パラメータ）
    floor: str          # 階数（例: "3階"）
    layout: str         # 間取り（例: "1LDK"）
    area: str           # 専有面積（例: "45.00m²"）
    rent: str           # 月額家賃（例: "150,000円"）
    management_fee: str # 管理費（例: "5,000円"）
    deposit: str        # 敷金（例: "300,000円"）
    key_money: str      # 礼金（例: "150,000円"）
    detail_url: str     # 詳細ページの絶対 URL


# ---------- ユーティリティ関数 ----------

def now_jst_iso() -> str:
    """現在の日時を JST の ISO 8601 形式（秒単位）で返す。

    例: "2026-05-23T10:30:00+09:00"
    ログ出力やメール本文のタイムスタンプに使う。
    """
    return datetime.now(JST).isoformat(timespec="seconds")


def fetch_html(url: str) -> str:
    """指定した URL の HTML をテキストとして取得して返す。

    スクレイピングであることを隠さない User-Agent を設定している。
    サイトは Shift_JIS 系（cp932）でエンコードされているため、
    response.text（自動検出）ではなく content.decode で明示的に変換する。
    """
    headers = {
        # ブラウザに見せかけず、スクレイパーであることを明示する User-Agent
        "User-Agent": "Mozilla/5.0 (compatible; vacancy-watcher/1.0)",
        # 日本語ページを優先して返してもらうためのヘッダー
        "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    }

    # HTTP GET リクエストを送る。20 秒で応答がなければ例外を投げる
    response = requests.get(url, headers=headers, timeout=20)
    # 4xx / 5xx レスポンスが来た場合は HTTPError 例外を発生させる
    response.raise_for_status()

    # このサイトはShift_JIS系なのでcp932でdecodeする
    # errors="replace" により、変換できない文字を ? 等に置換して続行する
    return response.content.decode("cp932", errors="replace")


def normalize_text(text: str) -> str:
    """HTML から取得したテキストを正規化する。

    - \xa0（ノーブレークスペース）を通常のスペースに置換
    - 連続する空白・改行をまとめて 1 つのスペースにする
    例: "  3階\n " → "3階"
    """
    return " ".join(text.replace("\xa0", " ").split())


# ---------- HTML 解析 ----------

def extract_rooms(html: str) -> list[Room]:
    """HTML から空室情報のリストを抽出して返す。

    賃貸サイトの <table class="result_article_table_detail"> を対象にし、
    各行から部屋情報を読み取る。テーブル構造が想定と異なる場合は
    空リストを返す（エラーにしない）。
    """
    # BeautifulSoup で HTML を解析できるオブジェクトに変換する
    soup = BeautifulSoup(html, "html.parser")

    # CSS セレクターで空室一覧テーブルを取得する
    # select_one は 1 つ目にマッチした要素を返し、見つからなければ None を返す
    table = soup.select_one("table.result_article_table_detail")
    if table is None:
        # テーブルが見つからない場合（ページ構造が変わった場合など）は空リストを返す
        return []

    rooms: list[Room] = []

    # 1行目はヘッダーなので除外
    # select("tr") は全 <tr> タグのリストを返す。[1:] でヘッダー行をスキップ
    rows = table.select("tr")[1:]

    for row in rows:
        # 詳細ページへのリンク（href に "add=" を含む <a> タグ）を探す
        # このリンクが存在しない行は部屋情報ではないとみなしてスキップする
        detail_link = row.select_one('a[href*="add="]')
        if detail_link is None:
            continue

        href = detail_link.get("href")
        if not href:
            continue

        # 相対 URL（例: /bukken/?detail=1361&add=14831）を絶対 URL に変換する
        detail_url = urljoin(BASE_URL, href)

        # 例: /bukken/?detail=1361&add=14831
        # URL の "add=" 以降の値を room_id として使う（部屋の一意識別子）
        room_id = detail_url.split("add=")[-1].split("&")[0]

        # 各 <td> のテキストを正規化してリストにする
        cols = [normalize_text(td.get_text(" ", strip=True)) for td in row.select("td")]

        # 想定カラム:
        # 0: お気に入り
        # 1: 画像
        # 2: 部屋番号など
        # 3: 階数
        # 4: 間取り
        # 5: 面積
        # 6: 家賃
        # 7: 管理費
        # 8: 敷金
        # 9: 礼金
        # 10: パノラマ画像
        # 11: 詳細
        # カラム数が 10 未満の行はデータ不足とみなしてスキップする
        if len(cols) < 10:
            continue

        rooms.append(
            Room(
                room_id=room_id,
                floor=cols[3],
                layout=cols[4],
                area=cols[5],
                rent=cols[6],
                management_fee=cols[7],
                deposit=cols[8],
                key_money=cols[9],
                detail_url=detail_url,
            )
        )

    return rooms


# ---------- 状態の読み書き ----------

def load_state() -> dict[str, Any]:
    """state.json から前回チェック時の状態を読み込んで返す。

    ファイルが存在しない場合（初回実行時）はデフォルト値を返す。
    last_checked_at が None であれば初回実行と判定できる。
    """
    if not STATE_PATH.exists():
        # 初回実行時のデフォルト値
        return {
            "last_room_ids": [],    # 前回検知した部屋 ID のリスト（空）
            "last_rooms": [],       # 前回検知した部屋の詳細情報（空）
            "last_checked_at": None,  # 前回チェック日時（None = 未実行）
        }

    # JSON ファイルを読み込んで Python の辞書に変換する
    with STATE_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_state(rooms: list[Room]) -> None:
    """現在の空室情報を state.json に保存する。

    次回実行時に「前回の状態」として参照される。
    asdict() は dataclass を辞書に変換するヘルパー関数。
    """
    state = {
        "last_room_ids": [room.room_id for room in rooms],  # 比較用の ID リスト
        "last_rooms": [asdict(room) for room in rooms],     # 詳細情報（デバッグ用）
        "last_checked_at": now_jst_iso(),                   # 保存日時
    }

    # UTF-8 で書き込み。ensure_ascii=False で日本語をそのまま保存、
    # indent=2 で人間が読みやすい整形済み JSON にする
    with STATE_PATH.open("w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
        f.write("\n")  # ファイル末尾に改行を追加（Unix 慣例）


# ---------- メール送信 ----------

def build_email_body(new_rooms: list[Room], all_rooms: list[Room]) -> str:
    """通知メールの本文を生成して返す。

    new_rooms: 今回新しく検知した部屋のリスト
    all_rooms: 現在サイトに掲載されている全部屋のリスト
    """
    lines: list[str] = []

    lines.append("ガーラ・プレシャス渋谷の空室一覧に変化がありました。")
    lines.append("")
    lines.append(f"検知日時: {now_jst_iso()}")
    lines.append(f"確認URL: {TARGET_URL}")
    lines.append("")
    lines.append("【新しく検知した空室】")

    # enumerate で 1 始まりの番号を付けながらループする
    for index, room in enumerate(new_rooms, start=1):
        lines.append("")
        lines.append(f"{index}.")
        lines.append(f"階数: {room.floor}")
        lines.append(f"間取り: {room.layout}")
        lines.append(f"面積: {room.area}")
        lines.append(f"家賃: {room.rent}")
        lines.append(f"管理費: {room.management_fee}")
        lines.append(f"敷金: {room.deposit}")
        lines.append(f"礼金: {room.key_money}")
        lines.append(f"詳細: {room.detail_url}")

    lines.append("")
    lines.append("【現在検知している空室数】")
    lines.append(f"{len(all_rooms)}件")
    lines.append("")
    lines.append("※このメールはGitHub Actionsによる自動チェックで送信されています。")

    # リストの各要素を改行でつなげて 1 つの文字列にする
    return "\n".join(lines)


def send_email(subject: str, body: str) -> None:
    """SMTP 経由でメールを送信する。

    接続情報はすべて環境変数から読み込む（コードにパスワードを書かないため）。
    必須の環境変数が設定されていない場合は KeyError が発生する。
    """
    # 環境変数から SMTP 設定を取得する（デフォルト値付き）
    smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")   # SMTP サーバーホスト名
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))          # ポート番号（587 = STARTTLS）
    smtp_user = os.environ["SMTP_USER"]          # 送信に使うメールアドレス（必須）
    smtp_password = os.environ["SMTP_PASSWORD"]  # アプリパスワード等（必須）
    mail_to = os.environ["MAIL_TO"]              # 通知先メールアドレス（必須）
    mail_from = os.environ.get("MAIL_FROM", smtp_user)  # 送信元（省略時は smtp_user と同じ）

    # MIMEText でメールオブジェクトを生成する（plain = プレーンテキスト形式）
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = mail_from
    msg["To"] = mail_to

    # SMTP サーバーに接続してメールを送信する
    # with ブロックを抜けると自動的に接続が閉じられる
    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.starttls()                          # 通信を TLS で暗号化する
        server.login(smtp_user, smtp_password)     # 認証する
        server.send_message(msg)                   # メールを送信する


# ---------- 設定ヘルパー ----------

def should_notify_on_first_run() -> bool:
    """初回実行時にメール通知を送るかどうかを環境変数から判定する。

    環境変数 NOTIFY_ON_FIRST_RUN が "1", "true", "yes", "y"（大文字小文字不問）
    のいずれかであれば True を返す。デフォルトは "true"（通知あり）。
    """
    value = os.environ.get("NOTIFY_ON_FIRST_RUN", "true").lower()
    return value in ["1", "true", "yes", "y"]


# ---------- メイン処理 ----------

def main() -> int:
    """スクリプトのメイン処理。終了コードを返す（0 = 正常終了）。"""

    print(f"Start vacancy check: {now_jst_iso()}")

    # 前回チェック時の状態を読み込む
    state = load_state()
    # 前回の部屋 ID を集合（set）にする。集合は差分計算が O(1) で高速
    previous_room_ids = set(state.get("last_room_ids", []))
    # last_checked_at が None なら初回実行と判定する
    is_first_run = state.get("last_checked_at") is None

    # サイトから最新の HTML を取得し、空室情報を抽出する
    html = fetch_html(TARGET_URL)
    rooms = extract_rooms(html)

    # 今回の部屋 ID の集合を作る
    current_room_ids = {room.room_id for room in rooms}
    # 差集合（-）で「今回初めて登場した部屋 ID」を求める
    new_room_ids = current_room_ids - previous_room_ids
    # 新しい部屋 ID に対応する Room オブジェクトのリストを作る
    new_rooms = [room for room in rooms if room.room_id in new_room_ids]

    # 結果をコンソールに出力する（GitHub Actions のログで確認できる）
    print(f"Current rooms: {len(rooms)}")
    print(f"Previous rooms: {len(previous_room_ids)}")
    print(f"New rooms: {len(new_rooms)}")

    if rooms:
        for room in rooms:
            print(
                f"- room_id={room.room_id}, "
                f"floor={room.floor}, layout={room.layout}, "
                f"area={room.area}, rent={room.rent}, "
                f"management_fee={room.management_fee}"
            )

    # メールを送信すべきかどうかを判定する
    should_send = False

    if is_first_run:
        # 初回実行: 空室が 1 件以上あり、かつ環境変数で通知が有効な場合のみ送信
        should_send = bool(rooms) and should_notify_on_first_run()
    else:
        # 2 回目以降: 新しい部屋が 1 件以上あれば送信
        should_send = bool(new_rooms)

    if should_send:
        # 初回実行時は全部屋を、2 回目以降は新しい部屋のみをメール本文に含める
        target_rooms = rooms if is_first_run else new_rooms
        subject = "【空室通知】ガーラ・プレシャス渋谷に空室が出ました"
        body = build_email_body(target_rooms, rooms)
        send_email(subject, body)
        print("Email sent.")
    else:
        print("No email sent.")

    # 今回の空室情報を state.json に保存して次回実行に備える
    save_state(rooms)
    print("State updated.")

    # 0 を返すと「正常終了」を意味する（Unix 慣例）
    return 0


# ---------- エントリーポイント ----------

if __name__ == "__main__":
    # このファイルを直接実行したときだけ main() を呼ぶ
    # SystemExit に整数を渡すと、そのコードでプロセスが終了する
    try:
        raise SystemExit(main())
    except Exception as e:
        # 予期せぬ例外は標準エラー出力に表示してから再送出する
        # GitHub Actions では stderr がエラーログとして記録される
        print(f"ERROR: {e}", file=sys.stderr)
        raise
