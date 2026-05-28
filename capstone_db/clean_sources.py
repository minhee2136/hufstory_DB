"""
sources.raw_text 클리닝
- 한자(CJK) 제거: 한글명(漢字) → 한글명
- 영어 제거: [a-zA-Z]
- 빈 괄호 제거: () → 제거
- 연속 공백 정리
"""

import sqlite3
import re

DB_PATH = "/Users/minhee/Desktop/DB/capstone_db/seoul_docent.db"

# CJK 유니코드 범위
CJK_PATTERN = re.compile(
    r'[\u2E80-\u2EFF'   # CJK Radicals Supplement
    r'\u3400-\u4DBF'    # CJK Extension A
    r'\u4E00-\u9FFF'    # CJK Unified Ideographs
    r'\uF900-\uFAFF'    # CJK Compatibility Ideographs
    r'\u20000-\u2A6DF]' # CJK Extension B (surrogate)
)

def clean_text(text):
    if not text:
        return text

    # 1. (한자만 있는 괄호) 제거: e.g. (僧伽山) → ""
    text = re.sub(r'\([^\S\n]*[^\u0000-\u007F\uAC00-\uD7A3\u1100-\u11FF\u3130-\u318F\s]+[^\S\n]*\)', '', text)

    # 2. 남은 한자 제거
    text = CJK_PATTERN.sub('', text)

    # 3. 영어 제거 (단, 숫자·특수문자·한글은 유지)
    text = re.sub(r'[a-zA-Z]+', '', text)

    # 4. 빈 괄호 제거
    text = re.sub(r'\(\s*\)', '', text)

    # 5. 연속 공백 정리
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = text.strip()

    return text


def run():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    c = conn.cursor()

    rows = c.execute("SELECT source_id, raw_text FROM sources").fetchall()
    print(f"총 {len(rows)}건 처리 시작\n")

    updated = 0
    for source_id, raw_text in rows:
        cleaned = clean_text(raw_text)
        if cleaned != raw_text:
            c.execute("UPDATE sources SET raw_text=? WHERE source_id=?", (cleaned, source_id))
            updated += 1

    conn.commit()
    conn.close()
    print(f"완료: {updated}건 수정됨 (변경 없음: {len(rows)-updated}건)")


if __name__ == "__main__":
    # 샘플 테스트
    samples = [
        "전북특별자치도 김제시 승가산(僧伽山)에 있는 삼국시대 고구려의 승려 보덕이 창건한 사찰.",
        "조선시대 한양도성(漢陽都城)의 정문으로 남쪽에 있다고 해서 남대문이라고도 불렀다.",
        "[유적건조물/국보] 서울 숭례문(崇禮門) | 소재지: Seoul 중구",
        "1961∼1963년 해체·수리 때 성종 10년(1479)에도 큰 공사가 있었다.",
    ]
    print("=== 샘플 테스트 ===")
    for s in samples:
        print(f"전: {s}")
        print(f"후: {clean_text(s)}")
        print()

    answer = input("실제 DB 업데이트 진행? (y/n): ")
    if answer.lower() == 'y':
        run()
