"""
Phase 3 — 도슨트 해설 생성
place + 모든 sources.raw_text → Groq API → stories 테이블 저장
"""
import sqlite3
import time
import sys
from groq import Groq

DB_PATH = "/Users/minhee/Desktop/DB/capstone_db/seoul_docent.db"
GROQ_API_KEY = "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"
MODEL = "llama-3.3-70b-versatile"

# 주제별 프롬프트 힌트
THEMES = {
    "생활사": "이 장소의 옛 생활 모습, 일상, 장인, 상인, 골목 풍경",
    "독립운동": "이 장소와 연결된 독립운동, 항일 역사, 인물과 사건",
    "지명유래": "이 장소 이름의 유래, 지명 변천, 조선시대부터 현재까지",
    "시장": "이 장소의 시장, 상업, 교역, 물건과 사람들의 이야기",
    "인물": "이 장소와 얽힌 역사적 인물, 그들의 삶과 자취",
}

SYSTEM_PROMPT = """당신은 서울의 역사와 문화를 생생하게 전달하는 도슨트입니다.
딱딱한 정보 전달이 아닌, 과거와 현재를 연결하는 이야기꾼 말투로 해설을 작성하세요.

예시 톤:
"조선시대 이 골목은 구리 냄새가 났대요. 놋그릇, 구리 장식품을 두드리는 소리가
하루 종일 울렸고, 관아에서 물건 사러 나온 관리들과 시장 상인들이 뒤섞였죠.
지금도 을지로 3, 4가 골목 안으로 들어가면 비슷해요. 철판 두드리는 소리, 공구 냄새.
500년 전 구리 장인들이 지금은 철물 장인으로 바뀌었을 뿐."

규칙:
- 3~5문단, 각 문단 2~4문장
- 과거 이야기로 시작해 현재와 연결
- 구체적인 감각(냄새, 소리, 풍경) 묘사 포함
- 마지막 문단: 방문자에게 지금 이 장소에서 느낄 수 있는 것
- 출력: 해설 텍스트만 (제목, 번호, 마크다운 불필요)"""


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def ensure_stories_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS stories (
            story_id INTEGER PRIMARY KEY AUTOINCREMENT,
            place_id TEXT NOT NULL,
            theme TEXT NOT NULL,
            docent_text TEXT,
            next_place_hint TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (place_id) REFERENCES places(place_id)
        )
    """)
    conn.commit()


def get_places_with_sources(conn, min_sources=1, limit=None, offset=0):
    """sources가 있는 places 조회 (좌표 있는 것 우선)"""
    sql = """
        SELECT p.place_id, p.name, p.address, p.district, p.category,
               p.lat, p.lng,
               GROUP_CONCAT(s.raw_text, '\n---\n') AS all_sources,
               COUNT(s.source_id) AS source_count
        FROM places p
        JOIN sources s ON p.place_id = s.place_id
        GROUP BY p.place_id
        HAVING source_count >= ?
        ORDER BY (p.lat IS NOT NULL) DESC, source_count DESC
    """
    params = [min_sources]
    if limit:
        sql += " LIMIT ? OFFSET ?"
        params += [limit, offset]

    return conn.execute(sql, params).fetchall()


def get_existing_themes(conn, place_id):
    """해당 place에 이미 생성된 주제 목록 반환"""
    rows = conn.execute(
        "SELECT theme FROM stories WHERE place_id=?", (place_id,)
    ).fetchall()
    return {r[0] for r in rows}


def build_prompt(name, address, district, theme, sources_text):
    # 소스 텍스트가 너무 길면 앞부분만 사용 (토큰 절약)
    max_chars = 3000
    if len(sources_text) > max_chars:
        sources_text = sources_text[:max_chars] + "\n... (이하 생략)"

    theme_hint = THEMES.get(theme, "")
    location = f"{district or ''} {address or ''}".strip() or "서울"

    return f"""다음 장소에 대한 도슨트 해설을 작성해주세요.

장소명: {name}
위치: {location}
주제: {theme} ({theme_hint})

참고 자료:
{sources_text}

위 자료를 바탕으로 {theme} 주제의 도슨트 해설을 작성하세요."""


def generate_story(client, name, address, district, theme, sources_text):
    prompt = build_prompt(name, address, district, theme, sources_text)
    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.7,
            max_tokens=800,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"    API 오류: {e}")
        return None


def run(limit=None, offset=0, min_sources=1):
    client = Groq(api_key=GROQ_API_KEY)
    conn = get_conn()
    ensure_stories_table(conn)
    c = conn.cursor()

    places = get_places_with_sources(conn, min_sources=min_sources,
                                     limit=limit, offset=offset)
    print(f"대상 장소: {len(places)}건 (min_sources={min_sources}, 주제 5개씩)")

    success = 0
    fail = 0

    for i, row in enumerate(places, 1):
        place_id, name, address, district, category, lat, lng, sources_text, source_count = row

        existing_themes = get_existing_themes(conn, place_id)
        remaining = [t for t in THEMES if t not in existing_themes]

        if not remaining:
            print(f"[{i}/{len(places)}] {name} — 모든 주제 완료, 스킵")
            continue

        print(f"[{i}/{len(places)}] {name} (소스 {source_count}건, 남은 주제 {len(remaining)}개)")

        for theme in remaining:
            print(f"  └ {theme}", end=" ", flush=True)
            story = generate_story(client, name, address, district, theme, sources_text or "")

            if story:
                c.execute(
                    "INSERT INTO stories (place_id, theme, docent_text) VALUES (?,?,?)",
                    (place_id, theme, story)
                )
                conn.commit()
                success += 1
                print("✓")
            else:
                fail += 1
                print("✗")

            time.sleep(2.1)

    conn.close()
    print(f"\n완료: 성공 {success}건 / 실패 {fail}건")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="도슨트 해설 생성")
    parser.add_argument("--limit", type=int, default=None, help="처리 건수 제한")
    parser.add_argument("--offset", type=int, default=0, help="시작 오프셋")
    parser.add_argument("--min-sources", type=int, default=1, help="최소 소스 수")
    args = parser.parse_args()

    run(limit=args.limit, offset=args.offset, min_sources=args.min_sources)
