"""
국가유산포털 오픈 API 크롤러
- 서울 전체 문화유산 수집
- 대상: 유적건조물 / 자연유산 / 등록문화유산
- 제외: 주소에 박물관·관리소·미술관·도서관·기념관·전시관·수장고 포함 항목
"""

import requests
import sqlite3
import time
import re
import xml.etree.ElementTree as ET

DB_PATH = "/Users/minhee/Desktop/DB/capstone_db/seoul_docent.db"
LIST_URL = "https://www.khs.go.kr/cha/SearchKindOpenapiList.do"
DETAIL_URL = "https://www.khs.go.kr/cha/SearchKindOpenapiDt.do"

TARGET_GCODES = {"유적건조물", "자연유산", "등록문화유산"}

EXCLUDE_ADDR_KEYWORDS = [
    "박물관", "관리소", "미술관", "도서관", "기념관", "전시관", "수장고", "보관소", "자료관"
]

SOURCE_NAME = "국가유산포털"


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


_session = None

def get_session():
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update({"User-Agent": "Mozilla/5.0"})
    return _session


def fetch_xml(url, params, retries=5):
    for i in range(retries):
        try:
            res = get_session().get(url, params=params, timeout=30)
            res.raise_for_status()
            res.encoding = "utf-8"
            return res.text
        except Exception as e:
            wait = 2 * (i + 1)
            print(f"  요청 오류 (시도 {i+1}/{retries}): {e} → {wait}초 대기")
            time.sleep(wait)
            # 세션 초기화
            global _session
            _session = None
    return None


def get_text(el, tag):
    node = el.find(tag)
    if node is not None and node.text:
        return node.text.strip()
    return ""


def fetch_all_list():
    """목록 전체 페이지 수집"""
    page_unit = 100
    page_index = 1
    items = []

    # 첫 페이지로 전체 건수 확인
    xml_text = fetch_xml(LIST_URL, {"ccbaCtcd": "11", "pageUnit": page_unit, "pageIndex": 1})
    if not xml_text:
        return items

    root = ET.fromstring(xml_text)
    total_cnt = int(root.findtext("totalCnt") or 0)
    total_pages = (total_cnt + page_unit - 1) // page_unit
    print(f"총 {total_cnt}건, {total_pages}페이지")

    def parse_items(root):
        for item in root.findall("item"):
            items.append({
                "name": get_text(item, "ccbaMnm1"),
                "ccmaName": get_text(item, "ccmaName"),
                "ccsiName": get_text(item, "ccsiName"),
                "ccbaKdcd": get_text(item, "ccbaKdcd"),
                "ccbaCtcd": get_text(item, "ccbaCtcd"),
                "ccbaAsno": get_text(item, "ccbaAsno"),
                "ccbaCpno": get_text(item, "ccbaCpno"),
                "ccbaCncl": get_text(item, "ccbaCncl"),
                "longitude": get_text(item, "longitude"),
                "latitude": get_text(item, "latitude"),
            })

    parse_items(root)

    for page_index in range(2, total_pages + 1):
        print(f"  목록 {page_index}/{total_pages} 페이지 수집 중...")
        xml_text = fetch_xml(LIST_URL, {"ccbaCtcd": "11", "pageUnit": page_unit, "pageIndex": page_index})
        if xml_text:
            parse_items(ET.fromstring(xml_text))
        time.sleep(0.3)

    return items


def fetch_detail(kdcd, asno, ctcd):
    """상세 정보 조회"""
    xml_text = fetch_xml(DETAIL_URL, {"ccbaKdcd": kdcd, "ccbaAsno": asno, "ccbaCtcd": ctcd})
    if not xml_text:
        return None

    root = ET.fromstring(xml_text)
    item = root.find("item")
    if item is None:
        return None

    addr_raw = get_text(item, "ccbaLcad")
    addr = re.sub(r'\s+', ' ', addr_raw).strip()

    return {
        "gcodeName": get_text(item, "gcodeName"),
        "bcodeName": get_text(item, "bcodeName"),
        "ccmaName": get_text(item, "ccmaName"),
        "name": get_text(item, "ccbaMnm1"),
        "addr": addr,
        "ccsiName": get_text(item, "ccsiName"),
        "content": get_text(item, "content"),
        "imageUrl": get_text(item, "imageUrl"),
        "ccbaAsdt": get_text(item, "ccbaAsdt"),  # 지정일
    }


def is_excluded_addr(addr):
    return any(kw in addr for kw in EXCLUDE_ADDR_KEYWORDS)


def find_or_create_place(conn, name, addr, lat, lng):
    c = conn.cursor()
    # 기존 places에서 이름 유사 검색 (HRT_ 아닌 것 우선)
    row = c.execute(
        "SELECT place_id FROM places WHERE name = ? LIMIT 1", (name,)
    ).fetchone()
    if row:
        return row[0]

    place_id = f"KHS_{re.sub(r'[^가-힣a-zA-Z0-9]', '', name)[:15]}"
    # 중복 place_id 처리
    suffix = 0
    base_id = place_id
    while c.execute("SELECT 1 FROM places WHERE place_id=?", (place_id,)).fetchone():
        suffix += 1
        place_id = f"{base_id}_{suffix}"

    lat_val = float(lat) if lat else None
    lng_val = float(lng) if lng else None

    c.execute(
        "INSERT INTO places (place_id, name, address, lat, lng, category) VALUES (?,?,?,?,?,?)",
        (place_id, name, addr, lat_val, lng_val, "문화유산")
    )
    conn.commit()
    return place_id


def run():
    conn = get_conn()
    c = conn.cursor()

    # 기존 국가유산포털 source URL 목록
    seen_urls = set(
        r[0] for r in c.execute(
            "SELECT source_url FROM sources WHERE source_name=?", (SOURCE_NAME,)
        ).fetchall()
    )
    print(f"기존 {SOURCE_NAME} 수집 건수: {len(seen_urls)}\n")

    # 목록 전체 수집
    all_items = fetch_all_list()
    print(f"\n목록 수집 완료: {len(all_items)}건\n")

    saved = 0
    skipped_type = 0
    skipped_addr = 0
    skipped_cancel = 0
    skipped_dup = 0

    for i, item in enumerate(all_items):
        # 지정 취소 항목 제외
        if item.get("ccbaCncl") == "Y":
            skipped_cancel += 1
            continue

        detail_url = f"https://www.khs.go.kr/cha/SearchKindOpenapiDt.do?ccbaKdcd={item['ccbaKdcd']}&ccbaAsno={item['ccbaAsno']}&ccbaCtcd={item['ccbaCtcd']}"

        if detail_url in seen_urls:
            skipped_dup += 1
            continue

        if (i + 1) % 50 == 0:
            print(f"  진행: {i+1}/{len(all_items)} | 저장:{saved} 유형제외:{skipped_type} 주소제외:{skipped_addr}")

        detail = fetch_detail(item["ccbaKdcd"], item["ccbaAsno"], item["ccbaCtcd"])
        time.sleep(0.5)

        if not detail:
            continue

        # 유형 필터
        if detail["gcodeName"] not in TARGET_GCODES:
            skipped_type += 1
            continue

        # 주소 필터
        addr = detail["addr"]
        if is_excluded_addr(addr):
            skipped_addr += 1
            continue

        if not detail["content"]:
            continue

        # raw_text 구성
        raw_text = (
            f"[{detail['gcodeName']}/{detail['ccmaName']}] {detail['name']}"
            f" | 소재지: {addr}"
        )
        if detail["bcodeName"]:
            raw_text += f" | 분류: {detail['bcodeName']}"
        if detail["ccbaAsdt"]:
            raw_text += f" | 지정일: {detail['ccbaAsdt']}"
        raw_text += f"\n{detail['content']}"

        place_id = find_or_create_place(
            conn, item["name"], addr,
            item.get("latitude", ""), item.get("longitude", "")
        )

        c.execute(
            "INSERT INTO sources (place_id, source_name, raw_text, source_url) VALUES (?,?,?,?)",
            (place_id, SOURCE_NAME, raw_text, detail_url)
        )
        seen_urls.add(detail_url)
        saved += 1

        if saved % 50 == 0:
            conn.commit()

    conn.commit()
    conn.close()

    print(f"\n=== 완료 ===")
    print(f"저장: {saved}건")
    print(f"유형 제외 (박물·공예품 등): {skipped_type}건")
    print(f"주소 제외 (실내시설): {skipped_addr}건")
    print(f"지정취소 제외: {skipped_cancel}건")
    print(f"중복 스킵: {skipped_dup}건")


if __name__ == "__main__":
    run()
