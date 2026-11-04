import base64, json, os, sys, time
from openai import OpenAI
c = OpenAI(api_key=os.environ["UPSTAGE_API_KEY"], base_url="https://api.upstage.ai/v1/information-extraction")
schema = json.load(open(sys.argv[1]))
for path in sys.argv[2:]:
    b64 = base64.b64encode(open(path, "rb").read()).decode()
    t = time.time()
    r = c.chat.completions.create(model="information-extract", messages=[{"role": "user", "content": [{"type": "image_url", "image_url": {"url": f"data:application/octet-stream;base64,{b64}"}}]}],
                                  response_format={"type": "json_schema", "json_schema": {"name": "meeting", "schema": schema}})
    out = json.loads(r.choices[0].message.content)
    json.dump(out, open(path + ".ie.json", "w"), ensure_ascii=False, indent=1)
    print(path.rsplit("/", 1)[1], f"{time.time()-t:.1f}s")
    time.sleep(1.1)  # 동기 1초 1건 제한
