"""
서울시 관광 자연.csv URL 기반 본문 설명 수집
- 콘텐츠URL → div.text-area 본문 추출
- FAQ 섹션 제거
- 데이터_수집/자연.json 저장
"""

import requests
import csv
import json
import re
import time
from bs4 import BeautifulSoup

CSV_PATH = "/Users/minhee/Desktop/DB/데이터_수집/서울시 관광 자연.csv"
OUT_PATH = "/Users/minhee/Desktop/DB/데이터_수집/자연.json"
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}


def get_detail(url):
    try:
        res = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(res.text, "html.parser")
        area = soup.find("div", class_="text-area")
        if not area:
            return None, None

        # p 태그 단위로 추출 (단어 사이 불필요한 \n 방지)
        paras = [p.get_text(strip=True) for p in area.find_all("p") if p.get_text(strip=True)]
        text = "\n".join(paras) if paras else area.get_text(separator=" ", strip=True)
        # FAQ 제거
        text = re.split(r'.{1,20}에 대해 자주 묻는 질문', text)[0].strip()

        # 좌표 (JS 변수)
        lat_m = re.search(r"var\s+lat\s*=\s*'([0-9.]+)'", res.text)
        lng_m = re.search(r"var\s+lng\s*=\s*'([0-9.]+)'", res.text)
        lat = float(lat_m.group(1)) if lat_m else None
        lng = float(lng_m.group(1)) if lng_m else None

        # 서울 범위 확인
        if lat and not (37.3 <= lat <= 37.8 and 126.7 <= lng <= 127.3):
            lat, lng = None, None

        return text, (lat, lng)
    except Exception as e:
        print(f"  오류 ({url}): {e}")
        return None, None


def main():
    with open(CSV_PATH, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    print(f"총 {len(rows)}건 수집 시작\n")

    results = []
    success = 0

    for i, row in enumerate(rows):
        name = row["상호명"].strip()
        address = row.get("신주소", "").strip() or row.get("주소", "").strip()
        url = row.get("콘텐츠URL", "").strip()

        detail_desc, coords = get_detail(url) if url else (None, (None, None))
        lat, lng = coords

        results.append({
            "name": name,
            "address": address,
            "lat": str(lat) if lat else "",
            "lng": str(lng) if lng else "",
            "detail_desc": detail_desc or "",
        })

        if detail_desc:
            success += 1

        if (i + 1) % 30 == 0:
            print(f"  {i+1}/{len(rows)} 완료 | 성공: {success}건")

        time.sleep(0.3)

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\n=== 완료 ===")
    print(f"설명 수집: {success}/{len(rows)}건")
    print(f"저장: {OUT_PATH}")


if __name__ == "__main__":
    main()
