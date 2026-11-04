# 원본 양식 3종 × 원본/PDF/DOCX 비교

동아리 HWP, WE-Meet HWP 묶음, 캡스톤 HWPX에 동일한 가상 데이터로 정상·카페 장소 위반(R12) 각 1건을 채운다. 학생 제출본은 사용하지 않는다. 캡스톤은 회의비 구역만 남기며 WE-Meet은 원본 6쪽 묶음을 유지한다.

```bash
cd backend
uv run python experiments/formats/run.py generate
```

출력은 Git에서 제외하는 `backend/out/formats/`다. `club_normal.hwp`, `club_cafe.hwp`, `wemeet_normal.hwp`, `wemeet_cafe.hwp`, `capstone_normal.hwpx`, `capstone_cafe.hwpx`가 만들어진다. 재생성은 이 6개 원본을 덮어쓴다. 재생성했으면 변환본도 다시 저장해야 한다.

각 원본을 **한컴에서 열어** 같은 폴더·파일명으로 PDF와 DOCX를 각각 저장한다. 원본의 서명·영수증 그림과 회의내용이 보이는지도 확인한다. 코드로 새 표를 그린 PDF·DOCX는 이 실험에 쓰지 않는다. 회의내용은 WE-Meet·캡스톤의 안내에 맞춰 10문단으로 작성했다.

```bash
uv run python experiments/formats/run.py compare
```

18개 파일이 모두 있어야 비교를 시작한다. 없으면 누락 경로를 출력하고 종료 코드 2로 끝나며 API를 호출하지 않는다. 비교 시 Upstage를 실제 호출하고 `out/formats/cache/`에 가상 데이터 응답을 저장한다. `backend/.env`의 설정은 서비스 설정 로더가 읽으며 키를 출력하지 않는다.

- 정상: 미충족 없음, 종합 `pass`.
- 카페 장소: 미충족 R12만, 종합 `reject`.
- 양식·케이스별로 원본/PDF/DOCX의 전체 조건 결과가 같아야 통과한다. 확인필요 차이도 보고한다.
- 결과는 `out/formats/results.json`. 기대 또는 형식 간 결과가 다르면 종료 코드 1, 전부 같으면 0이다.
- **위밋·캡스톤 확정 기준을 검증하는 실험은 아니다.** 세 양식에 같은 동아리 임시 기준을 적용하여 형식에 따른 판정 차이를 본다.

## 2026-10-31 확인 상태

- HWPX KeyError 원인: 안내문(section0)의 표 안에 나온 양식명을 회의록 제목으로 오인했다. 실제 회의록은 section1이다. 본문 제목으로 구역을 고르고, 추출 후 header의 `secCnt`도 남긴 구역 수로 맞췄다.
- 원본 6개 생성 및 로컬 리더 확인 완료: 모두 양식 일치, 예시 글 잔류 없음, 참석자 4명·결제자 서명 및 영수증 그림 인식. 정상/위반 장소 값도 일치한다.
- 캡스톤 회귀 시험 5개: 회의일시 수정 후 장소 칸 유지, 글자·그림 재읽기, 영수증·서명 누락 및 타자 서명, 묶음 보존 확인.
- 후속 UI 자동화로 PDF 6개 저장 완료. 캡스톤은 추출 구역을 `section0.xml`로 재번호화해야 한컴에서 열리는 문제도 수정했다. WE-Meet 작성자 칸은 짧아진 글자 수를 넘는 원래 서식 위치를 제거해야 손상 경고가 사라졌다.
- 현재 한컴은 읽기 전용이며 DOCX 저장이 유료 구독으로 잠겨 있다. DOCX 6개 변환 및 전체 18개 비교는 미완료다.
- `uv run python experiments/formats/run.py compare --formats source pdf`로 12개 비교: 동아리·캡스톤 원본/PDF 8개와 WE-Meet PDF 2개는 기대대로 판정. 생성한 WE-Meet HWP 2개는 Upstage에서 형식 미지원 400 오류. 원래 빈 WE-Meet HWP는 Upstage가 읽었다. 따라서 생성기 호환성 문제를 더 확인해야 하며, 실제 메일이 비양식이라는 근거가 아니다. 결과: `out/formats/results_source_pdf.json`.
