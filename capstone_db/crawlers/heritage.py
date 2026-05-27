import requests
import sqlite3
import time
import re
from bs4 import BeautifulSoup
from urllib.parse import urlencode

DB_PATH = "/Users/minhee/Desktop/DB/capstone_db/seoul_docent.db"
LIST_URL = "https://www.heritage.go.kr/heri/cul/culSelectRegionList.do"
DETAIL_URL = "https://www.heritage.go.kr/heri/cul/culSelectDetail.do"

# 서울 25개 구 + 주요 지명 키워드
KEYWORDS = [
    "종로구", "중구", "용산구", "성동구", "광진구", "동대문구", "중랑구",
    "성북구", "강북구", "도봉구", "노원구", "은평구", "서대문구", "마포구",
    "양천구", "강서구", "구로구", "금천구", "영등포구", "동작구", "관악구",
    "서초구", "강남구", "송파구", "강동구",
    "경복궁", "창덕궁", "덕수궁", "창경궁", "종묘", "숭례문", "흥인지문",
    "북한산", "남산", "인왕산", "한강", "청계천",
]

# 수집 대상 유형 (ccbaGcode)
TARGET_GCODES = {"CA": "유적건조물", "NH": "자연유산", "NE": "등록문화유산"}

# 유형 코드 매핑 (designation → gcode)
DESIGNATION_TO_GCODE = {
    "국보": "CA", "보물": "CA", "사적": "CA",
    "국가민속문화유산": "CA", "시도유형문화유산": "CA",
    "시도기념물": "CA", "시도민속문화유산": "CA",
    "명승": "NH", "천연기념물": "NH",
    "국가등록문화유산": "NE", "시도등록문화유산": "NE",
}


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def fetch_list(keyword):
    params = urlencode({"region": "11", "searchCondition": keyword, "pageIndex": 1, "pageUnit": 20})
    try:
        res = requests.get(f"{LIST_URL}?{params}",
                           headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        res.raise_for_status()
        return BeautifulSoup(res.text, "html.parser")
    except Exception as e:
        print(f"  목록 오류 ({keyword}): {e}")
        return None


def fetch_description(ccba_cpno):
    """ccbaCpno로 설명 HTML 직접 요청"""
    url = f"https://www.heritage.go.kr/DATA1/heritage/hub_img/html/cul_{ccba_cpno}.html"
    try:
        res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        res.encoding = "utf-8"
        res.raise_for_status()
        soup = BeautifulSoup(res.text, "html.parser")
        text = soup.get_text(separator=" ", strip=True)
        # "국가유산 설명" 이후 본문만 추출
        match = re.search(r'국가유산 설명\s*국가유산 설명\s*(.+)', text, re.DOTALL)
        return match.group(1).strip() if match else text
    except Exception:
        return ""


def parse_items(soup):
    items = []
    for a in soup.select("a[href*='culSelectDetail.do']"):
        href = a.get("href", "")
        url = "https://www.heritage.go.kr" + href if href.startswith("/") else href

        designation = ""
        desig_el = a.find("span")
        if desig_el:
            designation = desig_el.get_text(strip=True)

        name = ""
        name_el = a.select_one("strong")
        if name_el:
            name = re.sub(r'\(.*?\)', '', name_el.get_text(strip=True)).strip()

        location = ""
        for dt in a.select("dl dt"):
            if "소재지" in dt.get_text():
                dd = dt.find_next_sibling("dd")
                if dd:
                    location = dd.get_text(strip=True)

        gcode = DESIGNATION_TO_GCODE.get(designation, "")

        if name and "서울" in location and gcode:
            items.append({
                "name": name,
                "designation": designation,
                "gcode": gcode,
                "location": location,
                "url": url,
                "href_params": href.split("?")[1] if "?" in href else "",
            })
    return items


def find_or_create_place(conn, name, location):
    c = conn.cursor()
    row = c.execute(
        "SELECT place_id FROM places WHERE name LIKE ? AND place_id NOT LIKE 'HRT_%' LIMIT 1",
        (f"%{name}%",)
    ).fetchone()
    if row:
        return row[0]
    place_id = f"HRT_{re.sub(r'[^가-힣a-zA-Z0-9]', '', name)[:15]}"
    c.execute(
        "INSERT OR IGNORE INTO places (place_id, name, address, category) VALUES (?,?,?,?)",
        (place_id, name, location, "문화재")
    )
    conn.commit()
    return place_id


def run():
    conn = get_conn()
    c = conn.cursor()
    seen_urls = set(r[0] for r in c.execute("SELECT source_url FROM sources WHERE source_name='문화재청'").fetchall())
    total = 0

    print(f"=== 문화재청 수집 (서울 / 유적건조물·자연유산·등록문화유산) ===")
    print(f"기존 수집된 URL: {len(seen_urls)}건\n")

    for keyword in KEYWORDS:
        soup = fetch_list(keyword)
        if not soup:
            time.sleep(1)
            continue

        items = parse_items(soup)
        new_items = [i for i in items if i["url"] not in seen_urls]
        if not new_items:
            continue

        print(f"[{keyword}] {len(new_items)}건 신규")

        for item in new_items:
            seen_urls.add(item["url"])

            # ccbaCpno 추출 후 설명 가져오기
            cpno_match = re.search(r'ccbaCpno=(\w+)', item["href_params"])
            description = ""
            if cpno_match:
                description = fetch_description(cpno_match.group(1))
                time.sleep(0.7)

            gname = TARGET_GCODES.get(item["gcode"], item["gcode"])
            raw_text = f"[{gname}/{item['designation']}] {item['name']} | 소재지: {item['location']}"
            if description:
                raw_text += f" | {description}"

            place_id = find_or_create_place(conn, item["name"], item["location"])
            c.execute(
                "INSERT INTO sources (place_id, source_name, raw_text, source_url) VALUES (?,?,?,?)",
                (place_id, "문화재청", raw_text, item["url"])
            )
            total += 1

        conn.commit()
        time.sleep(1)

    conn.close()
    print(f"\n완료: 총 {total}건 신규 저장")


if __name__ == "__main__":
    run()
