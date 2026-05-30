"""
대한민국구석구석 (korean.visitkorea.or.kr) 서울 여행지 수집
- TOUR_CONTENT_LIST_VIEW (tagId=All, areaCode=1) → 전체 목록 페이지 수집
- TOUR_CONTENT_BODY_DETAIL → cotId별 좌표(mapX/mapY) + overView 설명
- cat1 == 'FD' 또는 'A05' 제외 (음식/카페)
- 이미지: https://cdn.visitkorea.or.kr/img/call?cmd=VIEW&id={imgPath}
- 저장: 데이터_수집/visitkorea.json
  columns: name, lat, lng, image_url, description, address, cat1
"""

import requests
import json
import time
from pathlib import Path

API_URL = "https://korean.visitkorea.or.kr/call"
OUT_PATH = Path("/Users/minhee/Desktop/DB/데이터_수집/visitkorea.json")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "Chrome/136.0.0.0 Safari/537.36",
    "Content-Type": "application/x-www-form-urlencoded",
    "Referer": "https://korean.visitkorea.or.kr/list/travelinfo.do?service=ms",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
}

STAMP_ID = "1589345b-b030-11ea-b8bd-020027310001"
EXCLUDE_CAT1 = {"FD", "A05"}  # 음식점/카페 카테고리
IMG_BASE = "https://cdn.visitkorea.or.kr/img/call?cmd=VIEW&id="
CNT_PER_PAGE = 100


def fetch_list_page(session, page: int) -> dict:
    params = {
        "cmd": "TOUR_CONTENT_LIST_VIEW",
        "month": "All",
        "areaCode": "1",
        "sigunguCode": "All",
        "tagId": "All",
        "sortkind": "1",
        "locationx": "0",
        "locationy": "0",
        "page": str(page),
        "cnt": str(CNT_PER_PAGE),
        "typeList": "Tour",
        "stampId": STAMP_ID,
    }
    resp = session.post(API_URL, data=params, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    return resp.json()


def fetch_detail(session, cot_id: str) -> tuple:
    """TOUR_CONTENT_BODY_DETAIL로 좌표 + 설명 조회"""
    params = {
        "cmd": "TOUR_CONTENT_BODY_DETAIL",
        "cotId": cot_id,
        "locationx": "0",
        "locationy": "0",
        "stampId": STAMP_ID,
    }
    try:
        resp = session.post(API_URL, data=params, headers=HEADERS, timeout=20)
        d = resp.json()
        detail = d.get("body", {}).get("detail", {})
        if not detail:
            return None, None, ""

        lat_raw = detail.get("mapY")  # mapY = 위도
        lng_raw = detail.get("mapX")  # mapX = 경도
        lat = float(lat_raw) if lat_raw else None
        lng = float(lng_raw) if lng_raw else None

        # 서울 범위 확인
        if lat and not (37.3 <= lat <= 37.8 and 126.7 <= lng <= 127.3):
            lat, lng = None, None

        overview = (detail.get("overView") or "").strip().replace("\n", " ")
        return lat, lng, overview
    except Exception:
        return None, None, ""


def main():
    session = requests.Session()

    # 1단계: 전체 목록 수집
    print("=== 목록 수집 중 ===")
    all_items = []

    # 첫 페이지로 totalCount 확인
    first = fetch_list_page(session, 1)
    body = first.get("body", {})
    raw_list = body.get("result", [])
    total_count = int(body.get("totalCount") or 0)
    total_pages = (total_count + CNT_PER_PAGE - 1) // CNT_PER_PAGE
    print(f"총 {total_count}건 | {total_pages}페이지")

    def process_items(raw):
        filtered = []
        for item in raw:
            cat1 = item.get("cat1", "")
            if cat1 in EXCLUDE_CAT1:
                continue
            img_path = item.get("imgPath", "")
            filtered.append({
                "cotId": item.get("cotId", ""),
                "name": (item.get("title") or "").strip(),
                "address": (item.get("addr1") or "").strip(),
                "description": (item.get("catchPhrase") or "").strip(),
                "image_url": IMG_BASE + img_path if img_path else "",
                "cat1": cat1,
                "lat": None,
                "lng": None,
            })
        return filtered

    all_items.extend(process_items(raw_list))
    time.sleep(0.4)

    for page in range(2, total_pages + 1):
        try:
            data = fetch_list_page(session, page)
            raw = data.get("body", {}).get("result", [])
            batch = process_items(raw)
            all_items.extend(batch)

            if page % 10 == 0:
                print(f"  {page}/{total_pages} 페이지 완료 | 누적 {len(all_items)}건")

            if not raw:
                print(f"  page {page}: 빈 응답 — 중단")
                break

        except Exception as e:
            print(f"  page {page} 오류: {e}")

        time.sleep(0.4)

    print(f"목록 수집 완료: {len(all_items)}건 (식당/카페 제외)\n")

    # 2단계: 상세 API로 좌표 + 설명 수집
    print("=== 좌표/설명 수집 중 ===")
    success_coords = 0

    for i, item in enumerate(all_items):
        cot_id = item.pop("cotId", "")
        if cot_id:
            lat, lng, overview = fetch_detail(session, cot_id)
            item["lat"] = lat
            item["lng"] = lng
            # overView가 있으면 catchPhrase 대신 사용
            if overview:
                item["description"] = overview
            if lat:
                success_coords += 1

        if (i + 1) % 50 == 0:
            print(f"  {i+1}/{len(all_items)} 완료 | 좌표 획득: {success_coords}건")

        time.sleep(0.35)

    print(f"좌표 수집 완료: {success_coords}/{len(all_items)}건\n")

    # 3단계: 저장
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(all_items, f, ensure_ascii=False, indent=2)

    print(f"=== 완료 ===")
    print(f"저장: {OUT_PATH}")
    print(f"총 {len(all_items)}건")
    cat_counts = {}
    for item in all_items:
        c = item.get("cat1", "?")
        cat_counts[c] = cat_counts.get(c, 0) + 1
    print("카테고리별:", cat_counts)


if __name__ == "__main__":
    main()
