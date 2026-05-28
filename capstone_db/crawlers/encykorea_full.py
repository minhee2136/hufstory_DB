"""
한국민족문화대백과 전체 수집 크롤러
- DB의 모든 장소명으로 검색 (location_confidence A/B)
- 서울 25개 구 + 주요 지명 키워드 추가 검색
- 상세 API로 본문 전체(body) 수집
- 이미 수집된 eid는 스킵
"""

import requests
import sqlite3
import time
import re

API_KEY = "3HCjWHehPQh1G6RH2A3G8B776Umi7jcT4dZ024qVbSQ="
BASE_URL = "https://devin.aks.ac.kr:8080/api"
DB_PATH = "/Users/minhee/Desktop/DB/capstone_db/seoul_docent.db"
SOURCE_NAME = "한국민족문화대백과"

SEOUL_KEYWORDS = [
    # 서울 25개 구
    "종로구", "중구", "용산구", "성동구", "광진구", "동대문구", "중랑구",
    "성북구", "강북구", "도봉구", "노원구", "은평구", "서대문구", "마포구",
    "양천구", "강서구", "구로구", "금천구", "영등포구", "동작구", "관악구",
    "서초구", "강남구", "송파구", "강동구",
    # 궁궐·유적
    "한양", "경복궁", "창덕궁", "창경궁", "덕수궁", "종묘", "사직단",
    "경희궁", "경운궁", "운현궁", "성균관", "장충단", "효창공원",
    # 성문·성곽
    "숭례문", "흥인지문", "돈의문", "혜화문", "한양도성", "북악산", "낙산",
    "독립문", "동대문", "서대문", "서대문형무소",
    # 산·자연
    "북한산", "남산", "인왕산", "관악산", "도봉산", "수락산", "불암산",
    "한강", "청계천", "중랑천", "안양천", "홍제천", "탄천", "양재천",
    # 주요 지역·동네
    "광화문", "인사동", "북촌", "서촌", "정동", "을지로", "명동",
    "이태원", "홍대", "신촌", "연희동", "합정", "망원동",
    "성수동", "왕십리", "뚝섬", "익선동", "가로수길",
    "노량진", "마포", "여의도", "영등포", "봉천동",
    "탑골공원", "낙원동", "피맛골", "육조거리", "운종가",
    # 시장
    "광장시장", "남대문시장", "동대문시장", "통인시장", "망원시장",
    "노량진수산시장", "경동시장", "황학동시장",
    # 역·교통
    "서울역", "경성역", "용산역",
]

# 본문이 있는 항목만 저장할 최소 길이
MIN_TEXT_LEN = 50


def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


session = requests.Session()
session.headers.update({"X-API-Key": API_KEY})


def search(keyword, page=1, page_size=20):
    try:
        res = session.get(
            f"{BASE_URL}/articles/search",
            params={"q": keyword, "p": page, "ps": page_size},
            timeout=30
        )
        res.raise_for_status()
        return res.json()
    except Exception as e:
        print(f"  검색 오류 ({keyword}): {e}")
        time.sleep(3)
        return None


def fetch_detail(eid):
    try:
        res = session.get(f"{BASE_URL}/articles/{eid}", timeout=30)
        res.raise_for_status()
        return res.json()
    except Exception as e:
        print(f"  상세 오류 ({eid}): {e}")
        time.sleep(3)
        return None


def is_seoul_related(item):
    """검색 결과가 서울 관련인지 판단"""
    text = " ".join([
        item.get("headword", ""),
        item.get("definition", ""),
        item.get("summary", ""),
    ])
    return "서울" in text or "한양" in text or "경성" in text


def find_or_get_place_id(conn, place_name):
    """장소명으로 place_id 조회 or 생성"""
    c = conn.cursor()
    row = c.execute(
        "SELECT place_id FROM places WHERE name = ? LIMIT 1", (place_name,)
    ).fetchone()
    if row:
        return row[0]

    # 부분 일치
    row = c.execute(
        "SELECT place_id FROM places WHERE name LIKE ? LIMIT 1", (f"%{place_name}%",)
    ).fetchone()
    if row:
        return row[0]

    # 새 place 생성
    place_id = f"EKC_{re.sub(r'[^가-힣a-zA-Z0-9]', '', place_name)[:15]}"
    suffix = 0
    base_id = place_id
    while c.execute("SELECT 1 FROM places WHERE place_id=?", (place_id,)).fetchone():
        suffix += 1
        place_id = f"{base_id}_{suffix}"
    c.execute(
        "INSERT OR IGNORE INTO places (place_id, name, category) VALUES (?,?,?)",
        (place_id, place_name, "지명")
    )
    conn.commit()
    return place_id


def process_item(conn, item, place_id, seen_eids):
    """단일 검색 결과를 DB에 저장"""
    eid = item.get("eid", "")
    if not eid or eid in seen_eids:
        return False

    seen_eids.add(eid)

    detail = fetch_detail(eid)
    time.sleep(0.4)
    if not detail:
        return False

    body = detail.get("body", "").strip()
    definition = detail.get("definition", "").strip()
    summary = detail.get("summary", "").strip()

    # 본문이 없으면 definition + summary로
    text = body if len(body) > len(definition) else (definition + "\n" + summary).strip()
    if len(text) < MIN_TEXT_LEN:
        return False

    headword = detail.get("headword", item.get("headword", ""))
    field = detail.get("field", item.get("field", ""))
    url = detail.get("url", item.get("url", f"https://encykorea.aks.ac.kr/Article/{eid}"))

    raw_text = f"[{field}] {headword}\n{text}"

    c = conn.cursor()
    c.execute(
        "INSERT INTO sources (place_id, source_name, raw_text, source_url) VALUES (?,?,?,?)",
        (place_id, SOURCE_NAME, raw_text, url)
    )
    conn.commit()
    return True


def search_and_save(conn, keyword, place_id, seen_eids, seoul_only=True):
    """키워드 검색 후 전 페이지 저장"""
    saved = 0
    page = 1
    while True:
        data = search(keyword, page=page, page_size=20)
        time.sleep(0.4)
        if not data:
            break

        items = data.get("items", [])
        total_page = data.get("totalPage", 1)

        for item in items:
            if seoul_only and not is_seoul_related(item):
                continue
            if process_item(conn, item, place_id, seen_eids):
                saved += 1

        if page >= total_page:
            break
        page += 1

    return saved


def run():
    conn = get_conn()
    c = conn.cursor()

    # 기존 수집된 eid 로드 (source_url에서 추출)
    seen_eids = set()
    for (url,) in c.execute(f"SELECT source_url FROM sources WHERE source_name=?", (SOURCE_NAME,)).fetchall():
        m = re.search(r'/Article/(\w+)', url or "")
        if m:
            seen_eids.add(m.group(1))
    print(f"기존 수집 eid: {len(seen_eids)}건\n")

    total_saved = 0

    # 1단계: 서울 핵심 키워드
    print("=== 1단계: 서울 핵심 키워드 ===")
    for kw in SEOUL_KEYWORDS:
        place_id = find_or_get_place_id(conn, kw)
        n = search_and_save(conn, kw, place_id, seen_eids, seoul_only=False)
        if n:
            print(f"  [{kw}] {n}건 저장")
        total_saved += n
        time.sleep(0.3)

    # 2단계: DB 장소명 전체 (confidence A/B)
    print(f"\n=== 2단계: DB 장소명 검색 (confidence A/B) ===")
    places = c.execute(
        "SELECT place_id, name FROM places WHERE location_confidence IN ('A','B') ORDER BY location_confidence"
    ).fetchall()
    print(f"대상: {len(places)}개 장소\n")

    for i, (place_id, name) in enumerate(places):
        if len(name) < 2:
            continue

        n = search_and_save(conn, name, place_id, seen_eids, seoul_only=False)
        total_saved += n

        if (i + 1) % 200 == 0:
            print(f"  진행: {i+1}/{len(places)} | 누적 저장: {total_saved}건")

        time.sleep(0.2)

    conn.close()
    print(f"\n=== 완료: 총 {total_saved}건 저장 ===")


if __name__ == "__main__":
    run()
