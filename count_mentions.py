import feedparser

url = "https://feeds.finance.yahoo.com/rss/2.0/headline?s=MU&region=US&lang=en-US"
feed = feedparser.parse(url)

news_msgs = []
for entry in feed.entries:
    news_msgs.append(entry.title)

keywords_count = {}
for message in news_msgs:
    words = message.split()
    for word in words:
        if word.isupper() and len(word) <= 5:
            keywords_count[word] = keywords_count.get(word, 0) + 1
for ticker, count in keywords_count.items():
    print(ticker, count)
