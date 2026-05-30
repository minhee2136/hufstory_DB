"""
한국민족문화대백과 — places 이름 기반 수집
두 가지 케이스 구분:

1. 독립 항목 (exact match)
   places.name "경복궁" → encykorea headword "경복궁"
   → 기존 place에 sources 추가

2. 상위 포함 항목 (suffix match)
   places.name "강녕전" → encykorea headword "경복궁 강녕전"
   → "경복궁 강녕전" place를 find-or-create → 그쪽에 sources 추가
   → 원래 "강녕전" place는 건드리지 않음

한자 제거: "가락교(可樂橋)" → "가락교" 로 검색
"""

import requests
import sqlite3
import json
import time
import re
from hashlib import md5

API_KEY = "3HCjWHehPQh1G6RH2A3G8B776Umi7jcT4dZ024qVbSQ="
BASE_URL = "https://devin.aks.ac.kr:8080/api"
DB_PATH = "/Users/minhee/Desktop/DB/capstone_db/seoul_docent.db"
SOURCE_NAME = "한국민족문화대백과"
MIN_TEXT_LEN = 50
MIN_NAME_LEN = 3


def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


session = requests.Session()
session.headers.update({"X-API-Key": API_KEY})


# ── 이름 정제 ─────────────────────────────────────────

def clean_name(name: str) -> str:
    """한자·괄호 제거 후 검색어로 사용할 이름 반환"""
    n = re.sub(r'[\u4e00-\u9fff]+', '', name)
    n = re.sub(r'\([^)]*\)', '', n)
    return re.sub(r'\s+', ' ', n).strip()


# ── API 호출 ──────────────────────────────────────────

def search_encykorea(keyword: str) -> list:
    """encykorea 검색 — 최대 50건"""
    try:
        res = session.get(
            f"{BASE_URL}/articles/search",
            params={"q": keyword, "p": 1, "ps": 50},
            timeout=30
        )
        res.raise_for_status()
        return res.json().get("items", [])
    except Exception as e:
        print(f"  검색 오류 ({keyword}): {e}")
        time.sleep(3)
        return []


def fetch_detail(eid: str) -> dict | None:
    try:
        res = session.get(f"{BASE_URL}/articles/{eid}", timeout=30)
        res.raise_for_status()
        return res.json()
    except Exception as e:
        print(f"  상세 오류 ({eid}): {e}")
        time.sleep(3)
        return None


# ── 매칭 판단 ─────────────────────────────────────────

def match_type(headword: str, target: str) -> str | None:
    """
    'exact'  — headword == target  (예: "경복궁" == "경복궁")
    'suffix' — headword ends with " target"  (예: "경복궁 강녕전" → "강녕전")
    None     — 매칭 없음
    """
    hw = re.sub(r'\([^)]*\)', '', headword).strip()
    if hw == target:
        return "exact"
    if hw.endswith(" " + target):
        return "suffix"
    return None


def is_seoul_related(item: dict) -> bool:
    text = " ".join([
        item.get("headword", ""),
        item.get("definition", ""),
        item.get("summary", ""),
    ])
    return any(kw in text for kw in ["서울", "한양", "경성", "조선", "서울시", "서울특별시"])


# ── DB 조작 ───────────────────────────────────────────

def make_place_id(name: str) -> str:
    """name 기반 place_id 생성 (EKC_ 접두사)"""
    safe = re.sub(r'[^가-힣a-zA-Z0-9]', '', name)[:12]
    return f"EKC_{safe}_{md5(name.encode()).hexdigest()[:6]}"


def find_or_create_place(conn, name: str, ref_place_id: str) -> str:
    """name으로 place를 찾거나 새로 생성, place_id 반환"""
    row = conn.execute(
        "SELECT place_id FROM places WHERE name = ? LIMIT 1", (name,)
    ).fetchone()
    if row:
        return row[0]

    # 새 place 생성 — 좌표·카테고리는 ref_place에서 참조
    ref = conn.execute(
        "SELECT lat, lng, category FROM places WHERE place_id = ? LIMIT 1",
        (ref_place_id,)
    ).fetchone()
    lat, lng, cat = (ref or (None, None, "지명"))

    new_id = make_place_id(name)
    # 충돌 방지
    while conn.execute("SELECT 1 FROM places WHERE place_id=?", (new_id,)).fetchone():
        new_id += "_x"

    conn.execute(
        "INSERT INTO places (place_id, name, lat, lng, category) VALUES (?,?,?,?,?)",
        (new_id, name, lat, lng, cat)
    )
    conn.commit()
    return new_id


def already_has_source(conn, place_id: str) -> bool:
    row = conn.execute(
        "SELECT sources FROM places WHERE place_id=?", (place_id,)
    ).fetchone()
    if not row or not row[0]:
        return False
    src = json.loads(row[0])
    return SOURCE_NAME in src


def upsert_source(conn, place_id: str, raw_text: str, url: str):
    """places.sources JSON에 encykorea 항목 추가"""
    row = conn.execute(
        "SELECT sources FROM places WHERE place_id=?", (place_id,)
    ).fetchone()
    if not row:
        return

    src = json.loads(row[0]) if row[0] else {}
    existing = src.get(SOURCE_NAME, "")
    if existing and url and url in existing:
        return
    src[SOURCE_NAME] = (existing + "\n\n" + raw_text).strip() if existing else raw_text

    conn.execute(
        "UPDATE places SET sources=? WHERE place_id=?",
        (json.dumps(src, ensure_ascii=False), place_id)
    )
    conn.commit()


def build_raw_text(detail: dict) -> str:
    headword = detail.get("headword", "")
    body = (detail.get("body") or "").strip()
    definition = (detail.get("definition") or "").strip()

    if len(body) >= MIN_TEXT_LEN:
        return f"{headword}\n\n{body}" if headword else body
    if len(definition) >= MIN_TEXT_LEN:
        return f"{headword}\n\n{definition}" if headword else definition
    return ""


# ── 대상 수집 ─────────────────────────────────────────

def fetch_targets(conn) -> list:
    """encykorea 없는 places — 유효한 이름만"""
    rows = conn.execute(
        "SELECT place_id, name FROM places WHERE name IS NOT NULL"
    ).fetchall()

    targets = []
    for place_id, name in rows:
        if already_has_source(conn, place_id):
            continue
        cleaned = clean_name(name)
        if len(cleaned) < MIN_NAME_LEN:
            continue
        if re.fullmatch(r'[\d\s\-\*\./_]+', cleaned):
            continue
        targets.append((place_id, name, cleaned))

    return targets


# ── 메인 ──────────────────────────────────────────────

def main():
    conn = get_conn()
    targets = fetch_targets(conn)
    print(f"검색 대상: {len(targets)}건\n")

    exact_added = 0
    suffix_added = 0
    no_match = 0

    for i, (place_id, orig_name, cleaned) in enumerate(targets):
        results = search_encykorea(cleaned)

        found = False
        for item in results:
            headword = item.get("headword", "")
            mtype = match_type(headword, cleaned)
            if not mtype:
                continue
            if not is_seoul_related(item):
                continue

            eid = item.get("eid", "")
            if not eid:
                continue

            detail = fetch_detail(str(eid))
            if not detail:
                continue

            raw_text = build_raw_text(detail)
            if len(raw_text) < MIN_TEXT_LEN:
                continue

            url = f"https://encykorea.aks.ac.kr/Article/{eid}"

            if mtype == "exact":
                # 독립 항목 → 기존 place에 추가
                upsert_source(conn, place_id, raw_text, url)
                exact_added += 1

            else:  # suffix
                # 상위 포함 항목 → headword 이름으로 별도 place find-or-create
                full_name = re.sub(r'\([^)]*\)', '', headword).strip()
                target_id = find_or_create_place(conn, full_name, place_id)
                if not already_has_source(conn, target_id):
                    upsert_source(conn, target_id, raw_text, url)
                suffix_added += 1

            found = True
            time.sleep(0.3)
            break  # 첫 번째 매칭만

        if not found:
            no_match += 1

        if (i + 1) % 200 == 0:
            print(f"  {i+1}/{len(targets)} 처리 | 독립: {exact_added} | 분리신규: {suffix_added} | 미매칭: {no_match}")

        time.sleep(0.3)

    conn.close()
    print(f"\n=== 완료 ===")
    print(f"독립 항목 추가: {exact_added}건")
    print(f"분리 신규 place 추가: {suffix_added}건")
    print(f"미매칭: {no_match}건")


if __name__ == "__main__":
    main()
