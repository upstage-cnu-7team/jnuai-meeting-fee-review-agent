"""본문 대용량 첨부 링크(네이버) 받기 — 2026-10-30 전자파 동아리 36MB HWP."""
import httpx

from app.mail import links

URL = "https://bigfile.mail.naver.com/download?fid=abcDEF123/xyz=="
BODY = (f"대용량 첨부 1개 36MB\n[증빙_전자파.hwp] 증빙_전자파.hwp 38238208<{URL}> ~ 2026/11/29 [다운로드] <{URL}> "
        "[MYBOX 저장] <https://mybox.naver.com/saveFile?service=mail&resource=x>")
HWP = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"0" * 100


def client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_find_links_only_download_once():
    assert links.find_links(BODY) == [URL]


def test_fetch_uses_content_disposition_name():
    def ok(req):
        return httpx.Response(200, content=HWP, headers={
            "content-disposition": "attachment; filename=\"x.hwp\"; filename*=UTF-8''%EC%A6%9D%EB%B9%99_%EC%A0%84%EC%9E%90%ED%8C%8C.hwp"})
    files, notes = links.fetch_all(BODY, set(), client(ok))
    assert files == [("증빙_전자파.hwp", HWP)] and notes == []
    # 이미 받은 이름이면 다시 더하지 않는다 (재검수)
    assert links.fetch_all(BODY, {"증빙_전자파.hwp"}, client(ok))[0] == []


def test_expired_link_is_manager_note_not_student_fault():
    def gone(req):
        return httpx.Response(200, content=b"<html>expired</html>", headers={"content-type": "text/html"})
    files, notes = links.fetch_all(BODY, set(), client(gone))
    assert files == [] and "학생 미제출이 아니" in notes[0]
