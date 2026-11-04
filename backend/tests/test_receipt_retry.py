"""영수증이 없는 회의록도 추출이 중단되지 않고, 영수증 칸만 재추출한다."""
from app.review import pipeline, readers
from minutes_review.model import Cell, Document, Image, Page, Table


def test_no_receipt_does_not_crash_extraction(monkeypatch):
    ie = {"team_name": "가상팀", "receipt_total": None}
    monkeypatch.setattr(pipeline.upstage, "extract", lambda data, cache: ie)
    assert pipeline.extract_all(b"document", None, object()) == ie


def test_receipt_retry_uses_receipt_cell_not_signature(monkeypatch):
    doc = Document("hwp", "synthetic.hwp", [Page(1, tables=[Table([
        [Cell("서명", [Image(b"signature")])],
        [Cell("영 수 증")], [Cell("", [Image(None), Image(b"receipt")])],
    ])])])
    assert readers.receipt_image(doc) == b"receipt"
    calls = []

    def extract(data, cache):
        calls.append(data)
        return {"receipt_total": 12000, "merchant_name": "가상점"} if data == b"receipt" else {"team_name": "가상팀"}

    monkeypatch.setattr(pipeline.upstage, "extract", extract)
    out = pipeline.extract_all(b"document", doc, object())
    assert calls == [b"document", b"receipt"]
    assert out["receipt_total"] == 12000
    assert out["team_name"] == "가상팀"


def test_signature_alone_is_not_a_receipt():
    doc = Document("hwp", "synthetic.hwp", [Page(1, tables=[Table([
        [Cell("서명")], [Cell("", [Image(b"signature")])],
        [Cell("영수증")], [Cell("")],
    ])])])
    assert readers.receipt_image(doc) is None


def test_multiple_minutes_are_identified_and_warned(monkeypatch):
    from app.graph import review_graph

    monkeypatch.setattr(readers, "classify", lambda data, name: ("hwp", None))
    monkeypatch.setattr(readers, "is_minutes", lambda doc, fmt: True)
    monkeypatch.setattr(review_graph.pages, "render_pages", lambda *args: [])
    out = review_graph.load_files({"files": [
        {"file_id": "first", "name": "first.hwp", "data": b"first"},
        {"file_id": "second", "name": "second.hwp", "data": b"second"},
    ]})
    assert out["minutes"]["file_id"] == "first"
    assert [m["file_id"] for m in out["minutes_all"]] == ["first", "second"]
    assert [f["kind"] for f in out["file_info"]] == ["minutes", "minutes"]
    assert "회의록마다 따로 판정" in out["notes"][0]


def test_each_minutes_is_judged(monkeypatch):
    """회의록이 여러 개면 회의록마다 따로 판정한다: 0원 회의록의 영수증 미첨부와 영수증 있는 회의록이 섞여도 각각 보인다 (2026-11-03 VCCC)."""
    from app.graph import review_graph
    from app.review import pipeline

    ies = {"a": {"meeting_date": "2026-10-27"}, "b": {"meeting_date": "2026-10-30"}}
    monkeypatch.setattr(pipeline, "extract_all", lambda data, doc, cache, name: ies[name])
    monkeypatch.setattr(pipeline, "marks_for", lambda fmt, doc, data, name, ie, cache: {"receipt_image": name == "b"})
    monkeypatch.setattr(review_graph.upstage, "solar", lambda ie, cache: {})
    monkeypatch.setattr(pipeline, "form_check_item", lambda doc, ocr, fid: {"check_id": "F00", "name": "양식", "result": "met", "severity": "reject"})
    monkeypatch.setattr(pipeline, "judge_file", lambda ie, sj, marks, at, rs, fid: [
        {"check_id": "R01", "name": "영수증 첨부", "result": "met" if marks["receipt_image"] else "unmet", "severity": "needs_fix"},
        {"check_id": "R18", "name": "제외", "result": "excluded", "severity": "needs_fix"}])
    files = [{"file_id": n, "name": n, "data": b"", "format": "hwp", "doc": None} for n in ("a", "b")]
    s = {"minutes": files[0], "minutes_all": files, "cache": None}
    s.update(review_graph.extract(s))
    s.update(review_graph.read_local(s))
    s.update(review_graph.judge_solar(s))
    out = review_graph.judge_code({**s, "rule_sets": {"club": {"id": "rs", "conditions": []}}, "program": "club", "received_at": None})
    by = {c["check_id"]: c for c in out["checks"]}
    assert by["R01-1"]["result"] == "unmet" and by["R01-1"]["name"] == "[10/27 회의록] 영수증 첨부"
    assert by["R01-2"]["result"] == "met" and by["F00-2"]["name"].startswith("[10/30 회의록]")
    assert [c["check_id"] for c in out["checks"]].count("R18") == 1
    assert out["verdict"] == "needs_fix"
