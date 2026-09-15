import truststore
truststore.inject_into_ssl()
import urllib.request
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
import json

rss_url = 'https://rss.blog.naver.com/trot-magazine.xml'
req = urllib.request.Request(rss_url, headers={'User-Agent': 'Mozilla/5.0'})
content = urllib.request.urlopen(req).read()
root = ET.fromstring(content)

items = root.findall('.//item')[:5]

samples = []
for item in items:
    title = item.find('title').text
    link = item.find('link').text
    category = item.find('category').text if item.find('category') is not None else ''
    log_no = link.split('/')[-1].split('?')[0]
    
    # fetch post html
    p_url = f'https://blog.naver.com/PostView.naver?blogId=trot-magazine&logNo={log_no}'
    p_req = urllib.request.Request(p_url, headers={'User-Agent': 'Mozilla/5.0'})
    p_html = urllib.request.urlopen(p_req).read().decode('utf-8')
    p_soup = BeautifulSoup(p_html, 'html.parser')
    
    # get sections
    main_c = p_soup.find('div', class_='se-main-container')
    text = main_c.get_text('\n', strip=True) if main_c else ''
    
    samples.append({
        'title': title,
        'category': category,
        'log_no': log_no,
        'text_len': len(text),
        'preview': text[:400],
        'full_text': text
    })

with open('blog_samples.json', 'w', encoding='utf-8') as f:
    json.dump(samples, f, ensure_ascii=False, indent=2)

print(f"Saved {len(samples)} blog samples successfully!")
for s in samples:
    cat = s['category']
    tit = s['title']
    length = s['text_len']
    print(f"[{cat}] {tit} ({length} chars)")
