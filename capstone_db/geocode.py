"""
카카오맵 API 지오코딩
1. 주소 있는 장소 → 주소 검색 API
2. 주소 없고 이름 있는 장소 → 키워드 검색 API (서울 범위 내)
"""

import sqlite3
import requests
import time

API_KEY = "7723abe9e847a3e1027981b539d56f42"
DB_PATH = "capstone_db/seoul_docent.db"

# 서울 중심 좌표 (키워드 검색 시 반경 기준)
SEOUL_X = 126.978
SEOUL_Y = 37.566
SEOUL_RADIUS = 20000  # 20km (카카오 API 최대값)

session = requests.Session()
session.headers.update({"Authorization": f"KakaoAK {API_KEY}"})


def geocode_by_address(address):
    """주소로 좌표 검색"""
    try:
        res = session.get(
            "https://dapi.kakao.com/v2/local/search/address.json",
            params={"query": address},
            timeout=10
        )
        res.raise_for_status()
        docs = res.json().get("documents", [])
        if docs:
            return float(docs[0]["y"]), float(docs[0]["x"])
    except Exception as e:
        print(f"  주소 오류: {e}")
    return None, None


def clean_name_for_search(name):
    """한자 괄호 제거: '가평로(加平路)' → '가평로'"""
    import re
    cleaned = re.sub(r'\([^)]*[\u4e00-\u9fff][^)]*\)', '', name).strip()
    return cleaned if cleaned else name


def geocode_by_keyword(name):
    """장소명으로 좌표 검색 (서울 범위). 한자 포함 시 정제 후 재시도."""
    queries = [f"서울 {name}"]
    cleaned = clean_name_for_search(name)
    if cleaned != name:
        queries.append(f"서울 {cleaned}")

    for query in queries:
        try:
            res = session.get(
                "https://dapi.kakao.com/v2/local/search/keyword.json",
                params={
                    "query": query,
                    "x": SEOUL_X,
                    "y": SEOUL_Y,
                    "radius": SEOUL_RADIUS,
                    "size": 1,
                },
                timeout=10
            )
            res.raise_for_status()
            docs = res.json().get("documents", [])
            if docs:
                lat, lng = float(docs[0]["y"]), float(docs[0]["x"])
                # 서울 범위 확인
                if 37.3 <= lat <= 37.8 and 126.7 <= lng <= 127.3:
                    return lat, lng
        except Exception as e:
            print(f"  키워드 오류: {e}")
    return None, None


def main():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # 1단계: 주소 있는 장소
    cur.execute("""
        SELECT place_id, name, address FROM places
        WHERE (lat IS NULL OR lng IS NULL)
          AND address IS NOT NULL AND address != ''
    """)
    addr_rows = cur.fetchall()
    print(f"주소 기반 지오코딩 대상: {len(addr_rows)}건")

    addr_ok = 0
    for place_id, name, address in addr_rows:
        # 우편번호 제거 (예: "153-815 서울 금천구...")
        clean_addr = address.strip()
        clean_addr = __import__('re').sub(r'^\d{3}-\d{3}\s*', '', clean_addr)

        lat, lng = geocode_by_address(clean_addr)
        if lat and lng:
            cur.execute("UPDATE places SET lat=?, lng=? WHERE place_id=?", (lat, lng, place_id))
            addr_ok += 1
        time.sleep(0.1)

    conn.commit()
    print(f"주소 기반 성공: {addr_ok}/{len(addr_rows)}건\n")

    # 2단계: 주소 없고 이름 있는 장소
    cur.execute("""
        SELECT place_id, name FROM places
        WHERE (lat IS NULL OR lng IS NULL)
          AND (address IS NULL OR address = '')
          AND name IS NOT NULL AND name != ''
    """)
    name_rows = cur.fetchall()
    print(f"이름 기반 지오코딩 대상: {len(name_rows)}건")

    name_ok = 0
    for i, (place_id, name) in enumerate(name_rows):
        lat, lng = geocode_by_keyword(name)
        if lat and lng:
            cur.execute("UPDATE places SET lat=?, lng=? WHERE place_id=?", (lat, lng, place_id))
            name_ok += 1

        if (i + 1) % 200 == 0:
            conn.commit()
            print(f"  진행: {i+1}/{len(name_rows)} | 성공: {name_ok}건")

        time.sleep(0.1)

    conn.commit()
    print(f"이름 기반 성공: {name_ok}/{len(name_rows)}건\n")

    # 최종 현황
    cur.execute("SELECT COUNT(*) FROM places WHERE lat IS NULL OR lng IS NULL")
    remaining = cur.fetchone()[0]
    print(f"=== 완료 ===")
    print(f"주소 기반: {addr_ok}건 / 이름 기반: {name_ok}건")
    print(f"여전히 좌표 없는 장소: {remaining}건")

    conn.close()


if __name__ == "__main__":
    main()
