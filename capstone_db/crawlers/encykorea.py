import requests
import sqlite3
import time
import pandas as pd
import re
from urllib.parse import urlencode

API_KEY = "3HCjWHehPQh1G6RH2A3G8B776Umi7jcT4dZ024qVbSQ="
BASE_URL = "https://devin.aks.ac.kr:8080/api"
DB_PATH = "/Users/minhee/Desktop/DB/capstone_db/seoul_docent.db"
headers = {"X-API-Key": API_KEY}

VALID_FIELDS = {
    "역사/근대사", "역사/현대사", "역사/조선시대", "역사/고려시대",
    "역사/삼국시대·남북국시대", "예술·체육/건축", "생활/주생활",
    "생활/식생활", "생활/민속·인류", "종교·철학/불교", "종교·철학/유교",
    "사회/사회구조", "지리/자연지리", "지리/인문지리"
}

EXTRA_KEYWORDS = [
    "종로", "을지로", "청계천", "인사동", "명동", "남대문",
    "경복궁", "창덕궁", "북촌", "서촌", "광화문", "정동",
    "마포", "용산", "한강", "남산", "독립문", "탑골공원",
    "성균관", "창경궁", "덕수궁", "종묘", "사직단", "운현궁"
]


def clean_name(name):
    return re.sub(r'\(.*?\)', '', str(name)).strip()


def fetch_ency(keyword):
    try:
        query = urlencode({"q": keyword, "p": 1, "ps": 5})
        res = requests.get(
            f"{BASE_URL}/articles/search?{query}",
            headers=headers,
            timeout=60
        )
        items = res.json().get('items', [])
        return [i for i in items if i['field'] in VALID_FIELDS and i.get('definition')]
    except Exception as e:
        print(f"  API 오류: {e}")
        return []


def run(places_csv="/Users/minhee/Desktop/DB/데이터_수집/places.csv"):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    c = conn.cursor()
    total = 0

    # 기존 지명 보강
    df = pd.read_csv(places_csv)
    targets = df[
        (df['source'] == '서울역사편찬원') &
        (df['location_confidence'] == 'A') &
        (df['description'].fillna('').str.len() < 200)
    ].head(300)

    print("=== 기존 지명 보강 ===")
    for _, row in targets.iterrows():
        keyword = clean_name(row['canonical_name'])
        if len(keyword) < 2:
            continue
        for item in fetch_ency(keyword):
            text = (item.get('definition', '') + ' ' + item.get('summary', '')).strip()
            exists = c.execute(
                'SELECT 1 FROM sources WHERE place_id=? AND source_name=?',
                (row['place_id'], '한국민족문화대백과')
            ).fetchone()
            if not exists:
                c.execute(
                    'INSERT INTO sources (place_id, source_name, raw_text, source_url) VALUES (?,?,?,?)',
                    (row['place_id'], '한국민족문화대백과', text, item.get('url', ''))
                )
                total += 1
                print(f"  [{keyword}] 저장")
        conn.commit()
        time.sleep(2)

    # 추가 핵심 키워드
    print("\n=== 추가 핵심 키워드 ===")
    for keyword in EXTRA_KEYWORDS:
        existing = c.execute(
            'SELECT place_id FROM places WHERE name LIKE ?', (f'%{keyword}%',)
        ).fetchone()
        if existing:
            place_id = existing[0]
        else:
            place_id = f"EKC_{keyword}"
            c.execute(
                'INSERT OR IGNORE INTO places (place_id, name, category) VALUES (?,?,?)',
                (place_id, keyword, '지명')
            )
        for item in fetch_ency(keyword):
            text = (item.get('definition', '') + ' ' + item.get('summary', '')).strip()
            exists = c.execute(
                'SELECT 1 FROM sources WHERE place_id=? AND source_name=?',
                (place_id, '한국민족문화대백과')
            ).fetchone()
            if not exists:
                c.execute(
                    'INSERT INTO sources (place_id, source_name, raw_text, source_url) VALUES (?,?,?,?)',
                    (place_id, '한국민족문화대백과', text, item.get('url', ''))
                )
                total += 1
                print(f"  [{keyword}] 저장")
        conn.commit()
        time.sleep(2)

    conn.close()
    print(f"\n완료: 총 {total}건 저장")


if __name__ == "__main__":
    run()
