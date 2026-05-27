import subprocess
import sqlite3
import time
import re
import json
from bs4 import BeautifulSoup
from urllib.parse import urlencode

DB_PATH = "/Users/minhee/Desktop/DB/capstone_db/seoul_docent.db"
BASE_URL = "https://museum.seoul.go.kr/archive/search/NR_search.do"

SEARCH_KEYWORDS = [
    "서울생활", "서울역사", "종로", "을지로", "청계천", "인사동",
    "명동", "남대문", "경복궁", "창덕궁", "북촌", "서촌",
    "광화문", "정동", "마포", "용산", "한강", "남산",
    "독립운동", "시장", "골목", "한옥", "근대"
]


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def fetch_page(keyword, page_index):
    params = urlencode({"query": keyword, "pageIndex": page_index, "pageUnit": 10})
    url = f"{BASE_URL}?{params}"
    try:
        result = subprocess.run(
            ["curl", "-s", "--max-time", "15", "-A", "Mozilla/5.0", url],
            capture_output=True, text=True
        )
        if result.returncode != 0 or not result.stdout:
            print(f"  curl 오류 (키워드={keyword}, 페이지={page_index})")
            return None
        return BeautifulSoup(result.stdout, "html.parser")
    except Exception as e:
        print(f"  요청 오류 (키워드={keyword}, 페이지={page_index}): {e}")
        return None


def parse_items(soup):
    items = []
    for a in soup.select("ul li a[href*='NR_archiveView']"):
        href = a.get("href", "")
        url = "https://museum.seoul.go.kr" + href if href.startswith("/") else href

        # <a> 내부 텍스트를 라벨 기준으로 파싱
        raw = a.get_text(separator="|", strip=True)
        parts = [p.strip() for p in raw.split("|") if p.strip()]

        title = parts[0] if parts else ""
        text = " ".join(parts)

        # 장소 추출 (텍스트에서 "구" 패턴)
        location = ""
        loc_match = re.search(r'([가-힣]+구)', raw)
        if loc_match:
            location = loc_match.group(1)

        if title:
            items.append({
                "title": title,
                "text": text,
                "url": url,
                "location": location
            })
    return items


def find_place_id(conn, keyword):
    c = conn.cursor()
    row = c.execute(
        "SELECT place_id FROM places WHERE name LIKE ? LIMIT 1",
        (f"%{keyword}%",)
    ).fetchone()
    return row[0] if row else None


def save_items(conn, place_id, items, keyword):
    c = conn.cursor()
    saved = 0
    for item in items:
        exists = c.execute(
            "SELECT 1 FROM sources WHERE place_id=? AND source_url=?",
            (place_id, item["url"])
        ).fetchone()
        if not exists:
            text = f"[{item['title']}] {item['text']}"
            c.execute(
                "INSERT INTO sources (place_id, source_name, raw_text, source_url) VALUES (?,?,?,?)",
                (place_id, "서울역사아카이브", text, item["url"])
            )
            saved += 1
    conn.commit()
    return saved


def run():
    conn = get_conn()
    total = 0

    for keyword in SEARCH_KEYWORDS:
        place_id = find_place_id(conn, keyword)
        if not place_id:
            place_id = f"ARC_{keyword}"
            conn.execute(
                "INSERT OR IGNORE INTO places (place_id, name, category) VALUES (?,?,?)",
                (place_id, keyword, "지명")
            )
            conn.commit()

        print(f"\n[{keyword}] 수집 중...")
        keyword_total = 0

        for page in range(1, 6):  # 최대 5페이지 (50건)
            soup = fetch_page(keyword, page)
            if not soup:
                break

            items = parse_items(soup)
            if not items:
                break

            saved = save_items(conn, place_id, items, keyword)
            keyword_total += saved
            print(f"  페이지 {page}: {len(items)}건 수집, {saved}건 저장")
            time.sleep(1)

        print(f"  → 소계: {keyword_total}건")
        total += keyword_total

    conn.close()
    print(f"\n완료: 총 {total}건 저장")


if __name__ == "__main__":
    run()
