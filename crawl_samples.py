import truststore
truststore.inject_into_ssl()
import urllib.request
import re
import json
from youtube_transcript_api import YouTubeTranscriptApi

queries = ['영웅대학', '박서진 서진대학', '트론매거진']

headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}

ytt = YouTubeTranscriptApi()

for q in queries:
    print(f"\n==================== QUERY: {q} ====================")
    url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(q)}"
    req = urllib.request.Request(url, headers=headers)
    try:
        html = urllib.request.urlopen(req).read().decode('utf-8')
    except Exception as e:
        print("Search error:", e)
        continue

    # Find video details from ytInitialData
    data_match = re.search(r'var ytInitialData = ({.*?});</script>', html)
    if not data_match:
        # try another regex
        video_ids = list(dict.fromkeys(re.findall(r'"videoId":"([a-zA-Z0-9_-]{11})"', html)))
    else:
        video_ids = list(dict.fromkeys(re.findall(r'"videoId":"([a-zA-Z0-9_-]{11})"', data_match.group(1))))

    print(f"Found {len(video_ids)} video ids")
    count = 0
    for vid in video_ids:
        if count >= 3:
            break
        # inspect video
        v_url = f"https://www.youtube.com/watch?v={vid}"
        try:
            v_req = urllib.request.Request(v_url, headers=headers)
            v_html = urllib.request.urlopen(v_req).read().decode('utf-8')
            title_m = re.search(r'<title>(.*?)</title>', v_html)
            title = title_m.group(1) if title_m else "No Title"
            
            # check channel
            channel_m = re.search(r'"ownerChannelName":"(.*?)"', v_html)
            channel = channel_m.group(1) if channel_m else ""

            # Check if shorts or regular
            is_short = "/shorts/" in v_html or "shorts" in v_html
            
            # try get transcript
            t_list = ytt.list(vid)
            transcript = t_list.find_transcript(['ko'])
            t_data = transcript.fetch()
            script_text = ' '.join([item.text for item in t_data])
            
            print(f"\n--- [VID: {vid}] ---")
            print(f"Title: {title}")
            print(f"Channel: {channel}")
            print(f"Script ({len(script_text)} chars): {script_text[:300]}...")
            
            with open(f"sample_{vid}.txt", "w", encoding="utf-8") as f:
                f.write(f"Title: {title}\nChannel: {channel}\n\n{script_text}")
            count += 1
        except Exception as e:
            # skip if no transcript or error
            continue
