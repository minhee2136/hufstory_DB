"""
places 테이블 완전 초기화 후 8개 JSON 파일로 재구축
- place_id: POI_ + MD5(name)[:8].upper()
- 동일 name → sources JSON 병합, address/image_url/category는 채워질 때 우선
- 서울역사편찬원.json은 서울 좌표 범위 밖 항목 제외
"""

import json
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "seoul_docent.db"
DATA_DIR = Path(__file__).parent.parent.parent / "데이터_수집"

# 서울 좌표 범위 필터
SEOUL_LAT = (37.3, 37.8)
SEOUL_LNG = (126.7, 127.3)

def make_place_id(n: int) -> str:
    return f"POI_{n:05d}"

def try_float(v):
    try:
        return float(v) if v not in (None, "", "None") else None
    except (ValueError, TypeError):
        return None

# 각 소스 파일 정의: (source_key, file, addr_col, img_col, cat_col)
SOURCES = [
    ("서울역사편찬원", "서울역사편찬원.json",  None,      None,        None      ),
    ("visitseoul",    "명소.json",            "address", "image_url", None      ),
    ("visitseoul",    "문화공간.json",         "주소",    "image_url", "주제분류"),
    ("서울시야경명소", "야경명소.json",         "주소",    None,        "분류"    ),
    ("visitseoul",    "자연.json",            "address", None,        None      ),
    ("nculture",      "nculture.json",        "주소",    "image_url", None      ),
    ("국가유산포털",  "국가유산포털.json",      "address", "image_url", "category"),
    ("visitkorea",    "visitkorea.json",       "address", "image_url", "cat1"    ),
]

def main():
    # places 딕셔너리: name → place dict
    places = {}  # key: name, value: {place_id, name, lat, lng, address, category, image_url, sources: {}}

    total_loaded = 0
    total_skipped = 0

    for source_key, filename, addr_col, img_col, cat_col in SOURCES:
        path = DATA_DIR / filename
        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        loaded = 0
        skipped = 0

        for item in data:
            name = item.get("name", "").strip()
            if not name:
                skipped += 1
                continue

            lat = try_float(item.get("lat"))
            lng = try_float(item.get("lng"))
            description = item.get("description", "") or ""

            # 좌표가 서울 범위 밖이면 오기입으로 간주 → NULL 처리 (장소 자체는 포함)
            if lat is not None and lng is not None:
                if not (SEOUL_LAT[0] <= lat <= SEOUL_LAT[1] and SEOUL_LNG[0] <= lng <= SEOUL_LNG[1]):
                    lat, lng = None, None

            address  = item.get(addr_col, "").strip() if addr_col and item.get(addr_col) else None
            image_url = item.get(img_col, "").strip() if img_col and item.get(img_col) else None
            category  = item.get(cat_col, "").strip() if cat_col and item.get(cat_col) else None

            if name not in places:
                # 첫 등장 시 좌표 없으면 일단 보류 (나중에 다른 소스에서 채워질 수 있음)
                places[name] = {
                    "place_id":  None,  # 좌표 필터 후 순번 부여
                    "name":      name,
                    "lat":       lat,
                    "lng":       lng,
                    "address":   address,
                    "category":  category,
                    "image_url": image_url,
                    "sources":   {},
                }
            else:
                p = places[name]
                # 좌표: 기존이 None이면 채움
                if p["lat"] is None and lat is not None:
                    p["lat"] = lat
                if p["lng"] is None and lng is not None:
                    p["lng"] = lng
                # address / image_url / category: 기존이 없으면 채움
                if not p["address"] and address:
                    p["address"] = address
                if not p["image_url"] and image_url:
                    p["image_url"] = image_url
                if not p["category"] and category:
                    p["category"] = category

            # sources 병합: 같은 source_key면 더 긴 description 유지
            p = places[name]
            existing = p["sources"].get(source_key, "")
            if len(description) > len(existing):
                p["sources"][source_key] = description

            loaded += 1

        print(f"[{source_key}] {filename}: {loaded}건 로드, {skipped}건 제외")
        total_loaded += loaded
        total_skipped += skipped

    print(f"\n총 고유 장소: {len(places)}개 (전체 로드 {total_loaded}건, 제외 {total_skipped}건)")

    # DB 반영
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # places 초기화
    cur.execute("DELETE FROM places")
    cur.execute("DELETE FROM sqlite_sequence WHERE name='places'")
    print("places 테이블 초기화 완료")

    # 좌표 없는 장소 제외 + 순번 place_id 부여
    before = len(places)
    places = {k: v for k, v in places.items() if v["lat"] is not None and v["lng"] is not None}
    for i, p in enumerate(places.values(), start=1):
        p["place_id"] = make_place_id(i)
    print(f"좌표 없음 제외: {before - len(places)}건 → 최종 {len(places)}건")

    # INSERT
    rows = [
        (
            p["place_id"],
            p["lat"],
            p["lng"],
            p["address"],
            p["category"],
            p["image_url"],
            json.dumps(p["sources"], ensure_ascii=False),
            p["name"],
            None,  # embedding
        )
        for p in places.values()
    ]

    cur.executemany(
        "INSERT INTO places (place_id, lat, lng, address, category, image_url, sources, name, embedding) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()

    # 결과 확인
    cur.execute("SELECT COUNT(*) FROM places")
    print(f"INSERT 완료: {cur.fetchone()[0]}건")

    cur.execute("SELECT COUNT(*) FROM places WHERE image_url IS NOT NULL AND image_url != ''")
    print(f"image_url 보유: {cur.fetchone()[0]}건")

    cur.execute("SELECT COUNT(*) FROM places WHERE address IS NOT NULL AND address != ''")
    print(f"address 보유: {cur.fetchone()[0]}건")

    # sources 키 분포
    from collections import Counter
    key_counter = Counter()
    cur.execute("SELECT sources FROM places")
    for (s,) in cur.fetchall():
        try:
            key_counter.update(json.loads(s).keys())
        except Exception:
            pass

    print("\nsources 키 분포:")
    for k, v in sorted(key_counter.items(), key=lambda x: -x[1]):
        print(f"  {k}: {v}건")

    conn.close()

if __name__ == "__main__":
    main()
