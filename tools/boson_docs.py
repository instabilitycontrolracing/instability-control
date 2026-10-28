import urllib.request, re, html, json, os
key = open(os.path.join(os.path.dirname(__file__), "boson_key.txt")).read().strip()
def get(url, auth=False):
    h = {"User-Agent": "Mozilla/5.0"}
    if auth: h["Authorization"] = "Bearer " + key
    try:
        return urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=30).read().decode("utf-8", "ignore")
    except Exception as e:
        return f"ERR {e}"
for u in ["https://docs.boson.ai/models/higgs-audio-tts/overview", "https://docs.boson.ai/models/higgs-audio-tts/voices"]:
    t = get(u)
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", t, flags=re.S)
    t = html.unescape(re.sub(r"<[^>]+>", " ", t)); t = re.sub(r"\s+", " ", t)
    print("=====", u, len(t)); print(t[:6000])
for u in ["https://api.boson.ai/v1/voices", "https://api.boson.ai/v1/audio/voices", "https://api.boson.ai/v1/models"]:
    print("=====", u); print(get(u, auth=True)[:3000])
