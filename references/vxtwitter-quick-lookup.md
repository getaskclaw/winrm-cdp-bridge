# vxtwitter API — Quick Single-Tweet Lookups

When you need to look up one or two tweets by URL, **don't fire up CDP or OpenCLI**. The vxtwitter API at `api.vxtwitter.com` returns a clean JSON response for any public tweet, no auth needed.

## Endpoint

```
https://api.vxtwitter.com/<username>/status/<tweet_id>
```

## Usage

```bash
curl -s "https://api.vxtwitter.com/jxnlco/status/2056139571641872765" | python3 -m json.tool
```

## Response shape

```json
{
    "date": "Sun May 17 22:27:29 +0000 2026",
    "likes": 734,
    "replies": 50,
    "retweets": 49,
    "text": "jason from the codex team here, heres a draft on codex maxxing...",
    "tweetID": "2056139571641872765",
    "tweetURL": "https://twitter.com/jxnlco/status/2056139571641872765",
    "user_name": "jason",
    "user_screen_name": "jxnlco",
    "user_profile_image_url": "https://pbs.twimg.com/...",
    "hasMedia": false,
    "mediaURLs": [],
    "hashtags": [],
    "lang": "en",
    "possibly_sensitive": false,
    "qrt": null,
    "replyingTo": null,
    "communityNote": null
}
```

Key fields: `text`, `likes`, `replies`, `retweets`, `date`, `user_name`, `user_screen_name`, `hasMedia`, `mediaURLs`, `hashtags`, `lang`, `replyingTo` (if a reply), `qrt` (quote tweet data), `communityNote`.

## When to use

- **Quick preview** of a tweet the user linked — get text + engagement stats in under 2 seconds
- **Verifying tweet content** before building a scraper or signal
- **Checking tweet metadata** (likes, replies, retweets) without loading X

## When NOT to use

- **Bulk collection** — each call is one tweet. Use CDP scroll harvest or X API v2 for volume
- **Logged-in-only content** — this is a public endpoint, won't show private/protected tweets or age-restricted content
- **Real-time** — the API caches for some time; very recent tweets may show stale data
- **Historical** — deleted tweets return an error, not historical data
