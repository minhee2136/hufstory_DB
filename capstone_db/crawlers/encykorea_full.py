"""
한국민족문화대백과 수집 크롤러 (새 DB 구조 대응)
- places.sources JSON 컬럼에 직접 병합
- 부족한 카테고리(독립운동, 시장과 생활, 인물 이야기) 위주 키워드 추가
- 이미 수집된 URL은 스킵
"""

import requests
import sqlite3
import json
import time
import re

API_KEY = "3HCjWHehPQh1G6RH2A3G8B776Umi7jcT4dZ024qVbSQ="
BASE_URL = "https://devin.aks.ac.kr:8080/api"
DB_PATH = "/Users/minhee/Desktop/DB/capstone_db/seoul_docent.db"
SOURCE_NAME = "한국민족문화대백과"

# 기존 키워드 (서울 25개 구 + 주요 지명)
KEYWORDS_BASE = [
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

# 추가 키워드 — 부족한 카테고리 보강
KEYWORDS_EXTRA = [
    # 독립운동
    "삼일운동", "3·1운동", "만세운동", "임시정부", "대한민국임시정부",
    "광복군", "의열단", "신간회", "독립협회", "독립신문",
    "안중근", "윤봉길", "유관순", "김구", "안창호", "신채호", "박은식",
    "이봉창", "이준", "김좌진", "홍범도", "이회영", "손병희",
    "탑골공원", "파고다공원", "서대문형무소", "경교장", "백범기념관",
    "봉황각", "광복회",

    # 시장과 생활
    "시전", "육의전", "보부상", "장시", "오일장",
    "청계천시장", "황학동", "동묘시장", "방산시장", "약령시장",
    "마포나루", "서강나루", "뚝섬나루", "광나루",
    "조선시대 상업", "한양 상인", "경강상인",
    "서울 민속", "서울 풍속", "생활사", "서민생활",
    "두모포", "칠패시장",

    # 인물 이야기 — 조선·근대 인물
    "정약용", "박지원", "이황", "이이", "정도전", "이순신",
    "세종대왕", "이성계", "왕건", "최한기", "허준",
    "김정호", "이항복", "황희", "성삼문", "사육신", "생육신",
    "최익현", "명성황후", "흥선대원군", "고종",
    "이상", "윤동주", "한용운", "이육사", "백석",
    "박경리", "이광수", "최남선",

    # 근대 역사 보강
    "경성", "조선총독부", "경성부", "조선은행", "식민지",
    "경인선", "경부선", "전차", "개화기", "갑오개혁",
    "을사늑약", "경술국치", "한일합방",
    "YMCA", "배재학당", "이화학당", "경성제국대학",
    "정동", "외국인거류지", "공사관",

    # 자연·공원 보강
    "북한산성", "삼각산", "도봉서원", "수락산", "망우리",
    "선유도", "밤섬", "노들섬", "뚝섬",
    "창경궁 동물원", "어린이대공원",
]

ALL_KEYWORDS = KEYWORDS_BASE + KEYWORDS_EXTRA
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
    text = " ".join([
        item.get("headword", ""),
        item.get("definition", ""),
        item.get("summary", ""),
    ])
    return any(kw in text for kw in ["서울", "한양", "경성", "조선"])


def find_or_create_place(conn, place_name):
    """장소명으로 place_id 조회 or 생성"""
    c = conn.cursor()
    row = c.execute("SELECT place_id FROM places WHERE name = ? LIMIT 1", (place_name,)).fetchone()
    if row:
        return row[0]

    row = c.execute("SELECT place_id FROM places WHERE name LIKE ? LIMIT 1", (f"%{place_name}%",)).fetchone()
    if row:
        return row[0]

    # 새 장소 생성
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


def upsert_source(conn, place_id, raw_text, url):
    """places.sources JSON에 한국민족문화대백과 항목 추가/갱신"""
    c = conn.cursor()
    row = c.execute("SELECT sources FROM places WHERE place_id=?", (place_id,)).fetchone()
    if not row:
        return

    src = json.loads(row[0]) if row[0] else {}

    # 이미 같은 URL이 있으면 스킵
    existing = src.get(SOURCE_NAME, "")
    if existing and url and url in existing:
        return

    # 여러 건인 경우 줄바꿈으로 합치기
    if existing:
        src[SOURCE_NAME] = existing + "\n\n" + raw_text
    else:
        src[SOURCE_NAME] = raw_text

    c.execute("UPDATE places SET sources=? WHERE place_id=?",
              (json.dumps(src, ensure_ascii=False), place_id))
    conn.commit()


def process_item(conn, item, place_id, seen_eids):
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

    text = body if len(body) > len(definition) else (definition + "\n" + summary).strip()
    if len(text) < MIN_TEXT_LEN:
        return False

    headword = detail.get("headword", item.get("headword", ""))
    field = detail.get("field", item.get("field", ""))
    url = detail.get("url", f"https://encykorea.aks.ac.kr/Article/{eid}")

    raw_text = f"[{field}] {headword}\n{text}"

    upsert_source(conn, place_id, raw_text, url)
    return True


def search_and_save(conn, keyword, place_id, seen_eids, seoul_only=True):
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

    # 기존 수집된 eid 로드 (places.sources JSON에서 추출)
    seen_eids = set()
    c.execute("SELECT sources FROM places WHERE sources IS NOT NULL")
    for (src_json,) in c.fetchall():
        src = json.loads(src_json)
        text = src.get(SOURCE_NAME, "") or ""
        for m in re.finditer(r'encykorea\.aks\.ac\.kr/Article/(\w+)', text):
            seen_eids.add(m.group(1))
    print(f"기존 수집 eid: {len(seen_eids)}건\n")

    total_saved = 0

    print(f"=== 전체 키워드 {len(ALL_KEYWORDS)}개 수집 시작 ===")
    for i, kw in enumerate(ALL_KEYWORDS):
        place_id = find_or_create_place(conn, kw)
        n = search_and_save(conn, kw, place_id, seen_eids, seoul_only=False)
        if n:
            print(f"  [{kw}] {n}건 저장")
        total_saved += n
        time.sleep(0.3)

        if (i + 1) % 20 == 0:
            print(f"  진행: {i+1}/{len(ALL_KEYWORDS)} | 누적: {total_saved}건")

    conn.close()
    print(f"\n=== 완료: 총 {total_saved}건 저장 ===")


if __name__ == "__main__":
    run()
