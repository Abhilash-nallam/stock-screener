import feedparser, urllib.parse, re
POS=["order win","new order","contract","profit rises","profit jumps","guidance raised","approval","capacity expansion","acquisition","buyback","dividend","upgrade","strong results","record revenue","inflow","expansion"]
NEG=["fraud","default","resigns","resignation","probe","investigation","penalty","downgrade","loss widens","guidance cut","pledge","insolvency","recall","ban","weak results","accounting"]
def company_news(company, limit=6):
    q=urllib.parse.quote(f'"{company}" India company stock')
    url=f"https://news.google.com/rss/search?q={q}&hl=en-IN&gl=IN&ceid=IN:en"
    feed=feedparser.parse(url); items=[]
    for e in feed.entries[:limit]:
        title=re.sub("<.*?>","",e.get("title",""))
        text=title.lower(); p=sum(w in text for w in POS); n=sum(w in text for w in NEG)
        sentiment=(p-n)/max(1,p+n)
        items.append({"title":title,"link":e.get("link",""),"published":e.get("published",""),
                      "sentiment":sentiment})
    return items
