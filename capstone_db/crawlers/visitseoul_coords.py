"""
visitseoul.net 명소 좌표 재수집
- 목록 60페이지 → name: href 매핑
- 상세 페이지에서 좌표 추출 (2가지 패턴)
  1. JSON-LD: "latitude": "37.xxx"
  2. JS 변수: var lat = '37.xxx'; var lng = '127.xxx';
- 데이터_수집/명소.json 의 lat, lng 업데이트
"""

import requests
import re
import json
import time
from bs4 import BeautifulSoup

BASE = "https://korean.visitseoul.net"
JSON_PATH = "/Users/minhee/Desktop/DB/데이터_수집/명소.json"
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}

SEOUL_LAT = (37.3, 37.8)
SEOUL_LNG = (126.7, 127.3)


def is_seoul(lat, lng):
    return SEOUL_LAT[0] <= lat <= SEOUL_LAT[1] and SEOUL_LNG[0] <= lng <= SEOUL_LNG[1]


def get_list_page(page_num):
    url = f"{BASE}/attractions?curPage={page_num}"
    try:
        res = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(res.text, "html.parser")
        items = {}
        for a in soup.find_all("a", href=re.compile(r"/attractions/.+/KOP")):
            href = a["href"]
            name_tag = a.find("span", class_="title")
            if name_tag:
                name = name_tag.get_text(strip=True)
                items[name] = href
        return items
    except Exception as e:
        print(f"  목록 오류 (page {page_num}): {e}")
        return {}


def get_coords(href):
    url = BASE + href
    try:
        res = requests.get(url, headers=HEADERS, timeout=15)
        text = res.text

        # 패턴 1: JSON-LD GeoCoordinates
        lat_m = re.search(r'"latitude"\s*:\s*"([0-9.]+)"', text)
        lng_m = re.search(r'"longitude"\s*:\s*"([0-9.]+)"', text)
        if lat_m and lng_m:
            lat, lng = float(lat_m.group(1)), float(lng_m.group(1))
            if is_seoul(lat, lng):
                return lat, lng

        # 패턴 2: JS 변수 var lat = '37.xxx';
        lat_m = re.search(r"var\s+lat\s*=\s*'([0-9.]+)'", text)
        lng_m = re.search(r"var\s+lng\s*=\s*'([0-9.]+)'", text)
        if lat_m and lng_m:
            lat, lng = float(lat_m.group(1)), float(lng_m.group(1))
            if is_seoul(lat, lng):
                return lat, lng

    except Exception as e:
        print(f"  좌표 오류 ({href}): {e}")
    return None, None


def main():
    # 1단계: 목록 60페이지 → name: href 매핑
    print("=== 목록 페이지 수집 중 ===")
    name_to_href = {}
    for page in range(1, 61):
        items = get_list_page(page)
        name_to_href.update(items)
        if page % 10 == 0:
            print(f"  {page}/60 완료 | 누적 {len(name_to_href)}건")
        time.sleep(0.3)
    print(f"총 {len(name_to_href)}개 매핑 완료\n")

    # 2단계: JSON 읽기
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        rows = json.load(f)

    # 3단계: 좌표 없는 것만 대상
    targets = [r for r in rows if not r.get("lat") or not r.get("lng")]
    print(f"좌표 없는 장소: {len(targets)}건\n=== 좌표 수집 중 ===")

    updated = 0
    not_found = []

    for i, row in enumerate(targets):
        name = row["name"]
        href = name_to_href.get(name)
        if not href:
            not_found.append(name)
            continue

        lat, lng = get_coords(href)
        if lat and lng:
            row["lat"] = str(lat)
            row["lng"] = str(lng)
            updated += 1

        if (i + 1) % 50 == 0:
            print(f"  {i+1}/{len(targets)} 완료 | 업데이트: {updated}건")

        time.sleep(0.3)

    # 4단계: JSON 저장
    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)

    print(f"\n=== 완료 ===")
    print(f"좌표 업데이트: {updated}/{len(targets)}건")
    if not_found:
        print(f"매핑 실패 ({len(not_found)}건): {not_found[:10]}")


if __name__ == "__main__":
    main()
