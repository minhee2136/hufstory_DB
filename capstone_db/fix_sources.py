"""
서울역사아카이브, 문화재청 sources 데이터 정제 스크립트
- 서울역사아카이브: raw_text 정제 + place_id 재매핑
- 문화재청: HRT_ place를 기존 DB places에 매핑
"""
import sqlite3
import re

DB_PATH = "/Users/minhee/Desktop/DB/capstone_db/seoul_docent.db"


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


# ── 서울역사아카이브 raw_text 정제 ────────────────────────────────

def clean_archive_text(raw):
    """
    '[제\xa0\xa0목 :] 제\xa0\xa0목 : 서울 안내-명동편 시\xa0\xa0기 : 1961 ...'
    → '서울 안내-명동편 (1961) [종로구] 제목 우측에 있는...'
    """
    text = raw.replace('\xa0', ' ')
    text = re.sub(r' {2,}', ' ', text)

    # 맨 앞 [제 목 :] 브라켓 제거
    text = re.sub(r'^\s*\[[^\]]+\]\s*', '', text)

    # 필드 추출 (브라켓 제거 후)
    title   = re.search(r'목\s*:\s*(.+?)\s*(?:시\s*기|$)', text)
    year    = re.search(r'기\s*:\s*(\S+)', text)
    loc     = re.search(r'소\s*:\s*(.+?)\s*(?:아카이브|$)', text)
    content = re.search(r'용\s*:\s*\.+\s*(.+)', text)

    title   = title.group(1).strip()   if title   else ""
    year    = year.group(1).strip()    if year    else ""
    loc     = loc.group(1).strip()     if loc     else ""
    content = content.group(1).strip() if content else ""

    parts = []
    if title:   parts.append(title)
    if year:    parts.append(f"({year})")
    if loc:     parts.append(f"[{loc}]")
    if content: parts.append(content)

    return " ".join(parts) if parts else text.strip()


STOPWORDS = {
    '서울', '한국', '조선', '대한', '안내', '자료', '조사', '기록',
    '사진', '문화', '역사', '생활', '지역', '전경', '전시', '연구',
}

def extract_title_keyword(raw):
    """raw_text에서 제목 추출 후 핵심 키워드 반환"""
    text = raw.replace('\xa0', ' ')
    text = re.sub(r' {2,}', ' ', text)
    text = re.sub(r'^\s*\[[^\]]+\]\s*', '', text)
    title = re.search(r'목\s*:\s*(.+?)\s*(?:시\s*기|$)', text)
    if not title:
        return None
    t = title.group(1).strip()
    words = re.findall(r'[가-힣]{2,}', t)
    # 불용어 제외하고 첫 번째 의미 있는 단어 반환
    for w in words:
        if w not in STOPWORDS:
            return w
    return None


def fix_archive(conn):
    c = conn.cursor()
    rows = c.execute(
        "SELECT source_id, place_id, raw_text FROM sources WHERE source_name='서울역사아카이브'"
    ).fetchall()

    updated = 0
    remapped = 0

    for source_id, old_place_id, raw_text in rows:
        # 1. 텍스트 정제
        cleaned = clean_archive_text(raw_text)

        # 2. 장소 재매핑 — 제목 키워드로 places 검색
        new_place_id = old_place_id
        keyword = extract_title_keyword(raw_text)
        if keyword and len(keyword) >= 2:
            row = c.execute(
                "SELECT place_id FROM places WHERE name LIKE ? AND place_id NOT LIKE 'ARC_%' LIMIT 1",
                (f"%{keyword}%",)
            ).fetchone()
            if row and row[0] != old_place_id:
                new_place_id = row[0]
                remapped += 1

        c.execute(
            "UPDATE sources SET raw_text=?, place_id=? WHERE source_id=?",
            (cleaned, new_place_id, source_id)
        )
        updated += 1

    conn.commit()
    print(f"서울역사아카이브: {updated}건 텍스트 정제, {remapped}건 place 재매핑")


# ── 문화재청 place 매핑 ────────────────────────────────────────────

def fix_heritage(conn):
    c = conn.cursor()
    # HRT_ place_id를 가진 sources
    rows = c.execute("""
        SELECT s.source_id, s.place_id, s.raw_text
        FROM sources s
        WHERE s.source_name='문화재청' AND s.place_id LIKE 'HRT_%'
    """).fetchall()

    remapped = 0
    for source_id, place_id, raw_text in rows:
        # raw_text에서 문화재명 추출: "[국보] 서울 숭례문 | ..."
        name_match = re.search(r'\] (.+?) \|', raw_text)
        if not name_match:
            continue
        heritage_name = name_match.group(1).strip()

        # "서울 " 접두어 제거 후 검색
        search_name = re.sub(r'^서울\s+', '', heritage_name)
        keyword = search_name[:6]  # 앞 6글자로 검색

        row = c.execute(
            "SELECT place_id FROM places WHERE name LIKE ? AND place_id NOT LIKE 'HRT_%' LIMIT 1",
            (f"%{keyword}%",)
        ).fetchone()

        if row:
            c.execute(
                "UPDATE sources SET place_id=? WHERE source_id=?",
                (row[0], source_id)
            )
            remapped += 1

    conn.commit()

    # 매핑된 HRT_ places 정리 (sources가 없는 것만)
    c.execute("""
        DELETE FROM places
        WHERE place_id LIKE 'HRT_%'
        AND place_id NOT IN (SELECT DISTINCT place_id FROM sources)
    """)
    conn.commit()
    print(f"문화재청: {remapped}건 기존 place로 재매핑")


if __name__ == "__main__":
    conn = get_conn()
    fix_archive(conn)
    fix_heritage(conn)
    conn.close()

    # 결과 확인
    conn = get_conn()
    c = conn.cursor()
    print("\n=== 정제 후 샘플 ===")
    print("[서울역사아카이브]")
    for r in c.execute("""
        SELECT p.name, s.raw_text FROM sources s
        JOIN places p ON p.place_id=s.place_id
        WHERE s.source_name='서울역사아카이브' LIMIT 3
    """).fetchall():
        print(f"  [{r[0]}] {r[1][:80]}")

    print("\n[문화재청]")
    for r in c.execute("""
        SELECT p.name, s.raw_text FROM sources s
        JOIN places p ON p.place_id=s.place_id
        WHERE s.source_name='문화재청' LIMIT 3
    """).fetchall():
        print(f"  [{r[0]}] {r[1][:80]}")
    conn.close()
