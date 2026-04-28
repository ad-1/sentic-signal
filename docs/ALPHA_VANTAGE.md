# Alpha Vantage API Notes

## Rate Limits
- **Free Tier:**
  - 25 requests per day
  - ~5 requests per minute
- **Premium Plans:**
  - Higher call volumes (e.g., 75+ requests per minute)
  - 500+ requests per day
- If the limit is exceeded, the API returns a `"Note"` field in the response, not a ban.
- Best practice: cache data locally to avoid duplicate requests and hitting limits.

## News Sentiment Endpoint
- Endpoint: `https://www.alphavantage.co/query?function=NEWS_SENTIMENT&tickers={TICKER}&apikey={API_KEY}`
- Returns up to 50 news items per request.
- Each request counts toward your rate limit, regardless of how many items are returned.
- Some tickers may return 0 news items due to lack of recent news or inconsistent coverage.
- If you see a `"Note"` in the response, you have likely hit a rate limit.

## API Key Handling
- Store your API key in an environment variable (e.g., `ALPHA_VANTAGE_KEY`).
- Do not log or expose your API key in code or output.
- The script should fail if the API key is not set.

## Troubleshooting
- If you get 0 news items for a ticker, possible reasons:
  - No recent news for that ticker
  - API data coverage is inconsistent
  - Temporary rate limit (check for `"Note"` in response)
- Always print or log the full API response for debugging if results are unexpected.

## Recommendations
- Add error handling for rate limits and missing API keys.
- Consider local caching and smarter scheduling for heavy usage.
- Upgrade to a premium plan for higher limits if needed.
