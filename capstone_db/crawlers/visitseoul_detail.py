"""
visitseoul.net 명소 상세 설명 재수집
- 목록 60페이지 → name: KOP_ID 매핑
- 상세 페이지 div.text-area 에서 전체 설명 수집
- 데이터_수집/명소.csv 의 detail_desc 컬럼 업데이트
"""

import requests
import re
import csv
import time
from bs4 import BeautifulSoup

BASE = "https://korean.visitseoul.net"
CSV_PATH = "/Users/minhee/Desktop/DB/데이터_수집/명소.csv"
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}


def get_list_page(page_num):
    """목록 페이지에서 name → (kop_id, href) 매핑 반환"""
    url = f"{BASE}/attractions?curPage={page_num}"
    try:
        res = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(res.text, "html.parser")
        items = {}
        for a in soup.find_all("a", href=re.compile(r"/attractions/.+/KOP")):
            href = a["href"]
            kop_id = re.search(r"(KOP\w+)", href)
            name_tag = a.find("span", class_="title")
            if kop_id and name_tag:
                name = name_tag.get_text(strip=True)
                items[name] = (kop_id.group(1), href)
        return items
    except Exception as e:
        print(f"  목록 오류 (page {page_num}): {e}")
        return {}


def get_detail_text(href):
    """상세 페이지 div.text-area 전체 텍스트 반환"""
    url = BASE + href
    try:
        res = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(res.text, "html.parser")
        area = soup.find("div", class_="text-area")
        if area:
            paras = [p.get_text(strip=True) for p in area.find_all("p") if p.get_text(strip=True)]
            text = "\n".join(paras) if paras else area.get_text(separator=" ", strip=True)
            return re.split(r'.{1,20}에 대해 자주 묻는 질문', text)[0].strip()
    except Exception as e:
        print(f"  상세 오류 ({href}): {e}")
    return None


def main():
    # 1단계: 목록 페이지 60개 → name: href 매핑
    print("=== 목록 페이지 수집 중 ===")
    name_to_href = {}
    for page in range(1, 61):
        items = get_list_page(page)
        name_to_href.update(items)
        if page % 10 == 0:
            print(f"  {page}/60 페이지 완료 | 누적 {len(name_to_href)}건")
        time.sleep(0.3)
    print(f"총 {len(name_to_href)}개 장소 매핑 완료\n")

    # 2단계: 기존 CSV 읽기
    with open(CSV_PATH, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    fieldnames = list(rows[0].keys())

    # 3단계: 상세 페이지 수집
    print("=== 상세 설명 수집 중 ===")
    updated = 0
    not_found = []

    for i, row in enumerate(rows):
        name = row["name"]
        mapping = name_to_href.get(name)
        if not mapping:
            not_found.append(name)
            continue

        _, href = mapping
        text = get_detail_text(href)
        if text:
            row["detail_desc"] = text
            updated += 1

        if (i + 1) % 50 == 0:
            print(f"  {i+1}/{len(rows)} 완료 | 업데이트: {updated}건")

        time.sleep(0.3)

    # 4단계: CSV 저장
    with open(CSV_PATH, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\n=== 완료 ===")
    print(f"업데이트: {updated}건 / 전체 {len(rows)}건")
    if not_found:
        print(f"매핑 실패 ({len(not_found)}건): {not_found[:10]}")


if __name__ == "__main__":
    main()
