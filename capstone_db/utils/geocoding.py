import requests
import sqlite3
import time

KAKAO_API_KEY = "7723abe9e847a3e1027981b539d56f42"
KAKAO_URL = "https://dapi.kakao.com/v2/local/search/address.json"
KAKAO_KEYWORD_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
DB_PATH = "/Users/minhee/Desktop/DB/capstone_db/seoul_docent.db"
HEADERS = {"Authorization": f"KakaoAK {KAKAO_API_KEY}"}


def geocode_address(address):
    """주소로 좌표 검색"""
    try:
        res = requests.get(KAKAO_URL, headers=HEADERS,
                           params={"query": address}, timeout=10)
        data = res.json()
        docs = data.get("documents", [])
        if docs:
            return float(docs[0]["y"]), float(docs[0]["x"])
    except Exception:
        pass
    return None, None


def geocode_keyword(name, address="서울"):
    """이름+주소로 키워드 검색 (주소 검색 실패 시 fallback)"""
    try:
        res = requests.get(KAKAO_KEYWORD_URL, headers=HEADERS,
                           params={"query": f"{name} {address}"}, timeout=10)
        data = res.json()
        docs = data.get("documents", [])
        if docs:
            return float(docs[0]["y"]), float(docs[0]["x"])
    except Exception:
        pass
    return None, None


def run(target="all"):
    """
    target: "all" = 좌표 없는 모든 places
            "hrt" = HRT_ places만
    """
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    c = conn.cursor()

    if target == "hrt":
        rows = c.execute("""
            SELECT place_id, name, address FROM places
            WHERE place_id LIKE 'HRT_%'
            AND (lat IS NULL OR lng IS NULL)
            AND address IS NOT NULL
        """).fetchall()
    else:
        rows = c.execute("""
            SELECT place_id, name, address FROM places
            WHERE (lat IS NULL OR lng IS NULL)
            AND address IS NOT NULL
            AND address != ''
        """).fetchall()

    print(f"지오코딩 대상: {len(rows)}건")
    success = 0
    fail = 0

    for i, (place_id, name, address) in enumerate(rows, 1):
        lat, lng = geocode_address(address)

        # 주소 검색 실패 시 이름으로 키워드 검색
        if lat is None:
            lat, lng = geocode_keyword(name, address or "서울")

        if lat is not None:
            c.execute("UPDATE places SET lat=?, lng=?, location_confidence='B' WHERE place_id=?",
                      (lat, lng, place_id))
            success += 1
            if success % 50 == 0:
                conn.commit()
                print(f"  {i}/{len(rows)} 처리 중... ({success}건 성공)")
        else:
            fail += 1

        time.sleep(0.05)  # 카카오 API 속도 제한 대응

    conn.commit()
    conn.close()
    print(f"\n완료: 성공 {success}건 / 실패 {fail}건")


if __name__ == "__main__":
    run(target="all")
