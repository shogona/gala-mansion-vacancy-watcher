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

import requests
from bs4 import BeautifulSoup


TARGET_URL = "https://www.gala-chintai.jp/bukken/?detail=1361"
BASE_URL = "https://www.gala-chintai.jp"

STATE_PATH = Path("state.json")

JST = timezone(timedelta(hours=9))


@dataclass
class Room:
    room_id: str
    floor: str
    layout: str
    area: str
    rent: str
    management_fee: str
    deposit: str
    key_money: str
    detail_url: str


def now_jst_iso() -> str:
    return datetime.now(JST).isoformat(timespec="seconds")


def fetch_html(url: str) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; vacancy-watcher/1.0)",
        "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    }

    response = requests.get(url, headers=headers, timeout=20)
    response.raise_for_status()

    # このサイトはShift_JIS系なのでcp932でdecodeする
    return response.content.decode("cp932", errors="replace")


def normalize_text(text: str) -> str:
    return " ".join(text.replace("\xa0", " ").split())


def extract_rooms(html: str) -> list[Room]:
    soup = BeautifulSoup(html, "html.parser")

    table = soup.select_one("table.result_article_table_detail")
    if table is None:
        return []

    rooms: list[Room] = []

    # 1行目はヘッダーなので除外
    rows = table.select("tr")[1:]

    for row in rows:
        detail_link = row.select_one('a[href*="add="]')
        if detail_link is None:
            continue

        href = detail_link.get("href")
        if not href:
            continue

        detail_url = urljoin(BASE_URL, href)

        # 例: /bukken/?detail=1361&add=14831
        room_id = detail_url.split("add=")[-1].split("&")[0]

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


def load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {
            "last_room_ids": [],
            "last_rooms": [],
            "last_checked_at": None,
        }

    with STATE_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_state(rooms: list[Room]) -> None:
    state = {
        "last_room_ids": [room.room_id for room in rooms],
        "last_rooms": [asdict(room) for room in rooms],
        "last_checked_at": now_jst_iso(),
    }

    with STATE_PATH.open("w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
        f.write("\n")


def build_email_body(new_rooms: list[Room], all_rooms: list[Room]) -> str:
    lines: list[str] = []

    lines.append("ガーラ・プレシャス渋谷の空室一覧に変化がありました。")
    lines.append("")
    lines.append(f"検知日時: {now_jst_iso()}")
    lines.append(f"確認URL: {TARGET_URL}")
    lines.append("")
    lines.append("【新しく検知した空室】")

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

    return "\n".join(lines)


def send_email(subject: str, body: str) -> None:
    smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ["SMTP_USER"]
    smtp_password = os.environ["SMTP_PASSWORD"]
    mail_to = os.environ["MAIL_TO"]
    mail_from = os.environ.get("MAIL_FROM", smtp_user)

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = mail_from
    msg["To"] = mail_to

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.send_message(msg)


def should_notify_on_first_run() -> bool:
    value = os.environ.get("NOTIFY_ON_FIRST_RUN", "true").lower()
    return value in ["1", "true", "yes", "y"]


def main() -> int:
    print(f"Start vacancy check: {now_jst_iso()}")

    state = load_state()
    previous_room_ids = set(state.get("last_room_ids", []))
    is_first_run = state.get("last_checked_at") is None

    html = fetch_html(TARGET_URL)
    rooms = extract_rooms(html)

    current_room_ids = {room.room_id for room in rooms}
    new_room_ids = current_room_ids - previous_room_ids
    new_rooms = [room for room in rooms if room.room_id in new_room_ids]

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

    should_send = False

    if is_first_run:
        should_send = bool(rooms) and should_notify_on_first_run()
    else:
        should_send = bool(new_rooms)

    if should_send:
        target_rooms = rooms if is_first_run else new_rooms
        subject = "【空室通知】ガーラ・プレシャス渋谷に空室が出ました"
        body = build_email_body(target_rooms, rooms)
        send_email(subject, body)
        print("Email sent.")
    else:
        print("No email sent.")

    save_state(rooms)
    print("State updated.")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        raise