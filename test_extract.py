import urllib.request
import re

url = 'https://www.erome.com/a/HYmUaHtl'
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
html = urllib.request.urlopen(req).read().decode('utf-8')

# Encontrar títulos
titles = re.findall(r'<title>(.*?)</title>', html)
print("Title:", titles)

# Encontrar mp4
mp4s = re.findall(r'<source src="([^"]+\.mp4)"', html)
if not mp4s:
    mp4s = re.findall(r'src="([^"]+\.mp4)"', html)

print("MP4s:", mp4s)
