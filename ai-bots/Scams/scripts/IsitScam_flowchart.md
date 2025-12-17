## IsitScam Script Flow (Mockup)

```
[Start]
  |
  v
fetch_unread_scam (entrypoint)
  |
  |-- load_config -> merge bot-assets/config.json with shared defaults + OPENAI_API_KEY env
  |
  |-- IMAP login (gmail_user/app_password) -> select inbox -> search for unread Primary emails with subject containing "Scam"
  |     |
  |     |-- No matches -> log and exit
  |     '-- Fetch latest match -> parse email + subject
  |
  |-- Subject check: if subject does not start with "Scam" -> re-mark unread + exit
  |
  |-- extract_body -> collect_from_blocks (grab forwarded "From:" blocks) -> pick sender_for_ai + body_for_ai
  |
  |-- analyze_body via OpenAI chat completions (returns JSON: is_scam, confidence, signals, summary)
  |
  |-- Determine forwarder_email (Reply-To/From)
  |
  |-- Branch on analysis.is_scam
        |
        |-- True:
        |     |-- Copy message to "Scam" folder, mark original deleted, expunge
        |     '-- send_scam_notification to forwarder_email (summary, confidence, signals)
        |
        '-- False:
              |-- forward_message sanitized body to envelope sender (gmail_user)
              |-- Mark original deleted + expunge
  |
  '-- Log sender, subject, summary, and final action
```
