// Cloudflare Email Worker: submit@jnuai-meetingfee.com 으로 온 메일 원본을 백엔드 웹훅으로 넘기고, 백업으로 Gmail에도 전달한다.
// - 첨부를 풀지 않고 원본(raw MIME)을 그대로 보낸다. 파싱은 백엔드(파이썬)가 한다 (무료 Worker는 CPU·메모리가 작음).
// - 웹훅이 실패해도 메일을 잃지 않게 BACKUP_TO로 먼저 전달한다.
// 환경 값: INTAKE_URL(vars), BACKUP_TO(vars), INTAKE_SECRET(secret)
export default {
  async email(message, env, ctx) {
    if (env.BACKUP_TO) {
      try {
        await message.forward(env.BACKUP_TO);
      } catch (e) {
        console.log("backup forward failed", String(e).slice(0, 100));
      }
    }
    const raw = await new Response(message.raw).arrayBuffer();
    for (let attempt = 0; attempt < 3; attempt++) {
      try {
        const res = await fetch(env.INTAKE_URL, {
          method: "POST",
          headers: { "X-Intake-Secret": env.INTAKE_SECRET, "Content-Type": "message/rfc822" },
          body: raw,
        });
        if (res.ok) {
          console.log("intake", res.status, (await res.text()).slice(0, 120));
          return;
        }
        console.log("intake error", res.status);
        if (res.status < 500) return; // 비밀 키 오류 등은 다시 보내도 같음
      } catch (e) {
        console.log("intake fetch failed", String(e).slice(0, 100));
      }
      await new Promise((r) => setTimeout(r, 2000 * (attempt + 1)));
    }
  },
};
