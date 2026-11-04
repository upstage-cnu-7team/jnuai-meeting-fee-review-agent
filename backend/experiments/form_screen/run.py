"""메일 첨부 양식 필터 실험. API 호출·메일 재전송·개인정보 복사 없음.

uv run python experiments/form_screen/run.py --output out/form_screen_before.json
실제 파일은 --real-positive <경로...>로 선택하여 메모리에서만 검사한다.
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from docx import Document  # noqa: E402
from app.review import readers  # noqa: E402
from tools.hwpkit import write_cfb  # noqa: E402
from tools.aicollege_samples import HwpFiller  # noqa: E402


def docx(lines):
    d, out = Document(), io.BytesIO()
    for line in lines:
        d.add_paragraph(line)
    d.save(out)
    return out.getvalue()


NEGATIVE_TEXTS = [
    ["동아리 활동 계획서", "팀명 가상팀", "다음 학기 일정과 예산을 논의할 회의를 진행할 예정입니다."],
    ["일반 회의록", "참석자 4명", "영수증은 다음 주까지 별도로 제출하기로 하였습니다."],
    ["도서 구매 요청서", "팀명 가상팀", "회의에서 선정한 인공지능 교재 4권을 신청합니다."],
    ["온라인강의 신청서", "팀명 가상팀", "이름 가상학생 학번 202400000", "수강 영수증 첨부 예정"],
    ["멘토링 결과보고서", "팀명 가상팀 소속 가상학부 이름 가상학생 서명", "회의 결과를 검토하고 결제자에게 연락함"],
    ["재료 구매 신청서", "팀명 가상팀 이름 가상학생 서명", "회의 준비용 재료비 사용 비용 영수증 제출"],
    ["연구비카드 매출전표", "결제자 가상학생", "사용 비용 60,000원 영수증 승인번호 12345678"],
    ["출장비 지출 증빙", "소속 가상학부 학번 202400000 이름 가상학생 서명", "회의 참석자 명단과 영수증을 첨부함"],
    ["장학금 신청서", "팀명 소속 학번 이름 서명 사용 비용 결제자", "회의 참석 이력이 있음"],
    ["회의비 지출 증빙 양식 작성 안내", "팀명 회의명 회의일시 회의장소 회의내용 참석자 명단 소속 학번 이름 서명 영수증 사용 비용 결제자", "해당 칸을 모두 작성하여 제출하세요."],
    ["캡스톤디자인 회의비 지출 증빙", "관련 문의는 담당자에게 연락하시기 바랍니다."],
    ["동아리 회계 정산 보고서", "팀명 회의명 회의일시 회의장소 회의내용 참석자 명단 소속 학번 이름 서명 영수증 사용 비용 결제자", "위 단어는 검색어 목록이며 증빙 양식이 아닙니다."],
]


def corpus():
    # 양식에 위반·미기재가 있어도 접수 단계에서 버리면 안 된다.
    for folder in (ROOT / "experiments/real_form/files", ROOT / "out/formats"):
        for p in sorted(folder.glob("*")):
            if p.suffix in (".hwp", ".hwpx", ".docx", ".pdf"):
                yield f"positive/{folder.name}/{p.stem}/{p.suffix[1:]}", True, [(p.name, p.read_bytes())]
    for i, lines in enumerate(NEGATIVE_TEXTS, 1):
        yield f"negative/text/{i:02}", False, [("other.docx", docx(lines))]
    forms = ROOT / "forms/aicollege"
    guide = forms / "별첨1_회의비_참고사항.hwp"
    yield "negative/original/club_guide", False, [("guide.hwp", guide.read_bytes())]
    # 실제 캡스톤 묶음의 안내·도서/강의/재료·멘토링 구역. 회의비 구역은 제외한다.
    template = next(forms.glob("*캡스톤*.hwpx"))
    for section in (0, 2, 3):
        with zipfile.ZipFile(template) as z:
            b = io.BytesIO()
            with zipfile.ZipFile(b, "w") as out:
                for name in z.namelist():
                    if not name.startswith("Contents/section"):
                        out.writestr(name, z.read(name))
                out.writestr("Contents/section0.xml", z.read(f"Contents/section{section}.xml"))
        yield f"negative/original/capstone_section{section}", False, [("other.hwpx", b.getvalue())]
    # WE-Meet 묶음의 회의비 외 구역. 원본 스트림만 재포장하며 학생 정보 없음.
    f = HwpFiller(next(forms.glob("*WE-Meet*.hwp")).read_bytes())
    for section in (1, 2):
        streams = {n: v for n, v in f.streams.items() if not n.startswith("BodyText/")}
        streams["BodyText/Section0"] = f.streams[f"BodyText/Section{section}"]
        yield f"negative/original/wemeet_section{section}", False, [("other.hwp", write_cfb(streams))]
    # 첨부가 섞여 있어도 회의비 양식 하나가 있으면 접수한다.
    positive = ROOT / "experiments/real_form/files/B00_정상.hwp"
    yield "positive/mixed", True, [("other.docx", docx(NEGATIVE_TEXTS[0])), ("minutes.hwp", positive.read_bytes())]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--real-positive", nargs="*", type=Path, default=[])
    args = parser.parse_args()
    cases = list(corpus())
    for i, p in enumerate(args.real_positive, 1):
        cases.append((f"positive/private/{i:02}", True, [("private" + p.suffix, p.read_bytes())]))
    rows, tp, fp, tn, fn, deferred = [], 0, 0, 0, 0, 0
    for label, expected, files in cases:
        formats = [readers.classify(data, name)[0] for name, data in files]
        needs_ocr = any(fmt in ("scan", "image") for fmt in formats)
        accepted = readers.screen(files) is None
        if needs_ocr:
            deferred += 1
        else:
            tp += expected and accepted
            fn += expected and not accepted
            fp += not expected and accepted
            tn += not expected and not accepted
        rows.append({"case": label, "expected": expected, "accepted": accepted, "needs_ocr": needs_ocr})
    report = {"total": len(rows), "tp": tp, "fp": fp, "tn": tn, "fn": fn, "deferred_ocr": deferred,
              "precision": tp / (tp + fp) if tp + fp else None,
              "recall": tp / (tp + fn) if tp + fn else None,
              "private_files": len(args.real_positive), "rows": rows}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "rows"}, ensure_ascii=False))
    print("errors", [r["case"] for r in rows if not r["needs_ocr"] and r["expected"] != r["accepted"]])


if __name__ == "__main__":
    main()
