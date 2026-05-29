import sqlite3
import json
import re


def clean_text(text: str) -> str:
    if not text:
        return text

    # 1. 국가유산포털/문화재청 메타데이터 헤더 제거
    # 형태: "[유적건조물/사적] 장소명 | 소재지: ... | 분류: ... | 지정일: ...\n본문..."
    # 또는: "[유형] 장소명 | 소재지: ... | 본문 계속..."  (한 줄에 이어지는 경우)
    lines = text.split('\n')
    cleaned_lines = []
    for line in lines:
        # [분류] 로 시작하고 | 소재지: 패턴이 있는 줄은 본문 부분만 추출
        if re.match(r'^\[.+?\]', line) and '소재지:' in line:
            # 마지막 | 이후 텍스트가 본문인 경우 (문화재청 형태)
            parts = line.split('|')
            # "소재지:", "분류:", "지정일:" 패턴이 아닌 마지막 부분 찾기
            body = ''
            for part in parts:
                part = part.strip()
                if not re.match(r'^(\[.+?\].+|소재지:|분류:|지정일:)', part) and len(part) > 10:
                    body = part
            cleaned_lines.append(body)
        else:
            cleaned_lines.append(line)
    text = '\n'.join(cleaned_lines)

    # 남은 "소재지: ... | 분류: ... | 지정일: ..." 패턴 제거
    text = re.sub(r'소재지:[^\n|]+(\|[^\n|]+)*', '', text)
    text = re.sub(r'분류:[^\n|]+', '', text)
    text = re.sub(r'지정일:\s*\d+', '', text)

    # 2. 이미지 캡션 제거
    # "이미지 XXX XXX ..." 로 시작하는 캡션 블록 전체 제거
    text = re.sub(r'이미지\s+.+', '', text, flags=re.DOTALL)
    # "장소명 장소명_설명 (촬영년도 : 2015년)" 반복 블록 제거 (이미지 없어도)
    text = re.sub(r'(?:[가-힣\w\s]{1,20}\(촬영년도\s*:\s*\d+년\)\s*){1,}', '', text)
    # 남은 언더스코어 파일명 패턴
    text = re.sub(r'[가-힣\w]*_[가-힣\w]+', '', text)

    # 3. 서울역사아카이브 태그/메타 제거
    text = re.sub(r'\[[가-힣\w\s:]+\]', '', text)
    # 짧은 줄에 연도만 있는 경우 (예: "서울 역 일대 (1984-10-15)")
    text = re.sub(r'^[가-힣\s]{1,20}\(\d{4}(?:-\d{2}-\d{2})?\)\s*$', '', text, flags=re.MULTILINE)

    # 4. "더보기" 제거
    text = re.sub(r'더보기', '', text)

    # 5. 중국어/일본어 특수문자 제거
    text = re.sub(r'[。，、·「」『』【】〔〕※…]', '', text)
    # 연속 3자 이상 CJK 한자 (중국어 문장) 제거
    text = re.sub(r'[\u4e00-\u9fff]{3,}', '', text)

    # 6. 영문 알파벳 제거
    text = re.sub(r'[A-Za-z]+', '', text)

    # 7. 빈 괄호 및 `(,` 처럼 내용 없는 괄호 정리
    text = re.sub(r'\(\s*,?\s*\)', '', text)
    text = re.sub(r'\(\s*\)', '', text)
    # `(,` 또는 `( –` 처럼 여는 괄호 뒤에 바로 특수문자만 오는 것 제거
    text = re.sub(r'\(\s*[,\.\-–\s]+', ' ', text)
    # 대응되는 여는 괄호 없이 남은 닫는 괄호 제거
    def remove_unmatched_close(s):
        result = list(s)
        depth = 0
        for i, ch in enumerate(result):
            if ch == '(':
                depth += 1
            elif ch == ')':
                if depth == 0:
                    result[i] = ''
                else:
                    depth -= 1
        return ''.join(result)
    text = remove_unmatched_close(text)

    # 8. 연속된 특수문자/구두점 덩어리 제거
    text = re.sub(r'(?:[,\.\-\(\)\–\|\s]{3,})', ' ', text)

    # 9. 공백/줄바꿈 정리
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'[ \t]{2,}', ' ', text)
    text = text.strip()

    return text


def main():
    conn = sqlite3.connect('capstone_db/seoul_docent.db')
    cur = conn.cursor()

    cur.execute('SELECT place_id, sources FROM places WHERE sources IS NOT NULL')
    rows = cur.fetchall()

    updated = 0
    for place_id, sources_raw in rows:
        src_dict = json.loads(sources_raw)
        cleaned = {k: clean_text(v) for k, v in src_dict.items()}
        # 클리닝 후 빈 문자열이 된 것은 None으로
        cleaned = {k: (v if v else None) for k, v in cleaned.items()}

        new_json = json.dumps(cleaned, ensure_ascii=False)
        if new_json != sources_raw:
            cur.execute('UPDATE places SET sources = ? WHERE place_id = ?',
                        (new_json, place_id))
            updated += 1

    conn.commit()
    conn.close()
    print(f'클리닝 완료: {updated}건 수정')


if __name__ == '__main__':
    main()
