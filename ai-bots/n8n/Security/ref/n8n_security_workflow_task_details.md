# n8n Security Workflow Task Details

Source JSON: `c:\ChatGPT\ai-bots\Security\n8n_security_gmail_to_sheet_exact.json`

Total Nodes: **16**
Total Connections: **16**

## External Resources
- Gmail API: list/get/modify endpoints
- Google Sheets API: header read + row append endpoints
- OAuth2 credentials in n8n for Google APIs
- n8n Code nodes for text extraction and cleaning logic

## Task-by-Task

### Manual Trigger
- Type: `n8n-nodes-base.manualTrigger` v`1`
- Purpose: Manual test entry point; starts one run from editor.
- Inbound: `none`
- Outbound: `Code - Load Config [branch=0]`

### Schedule Trigger
- Type: `n8n-nodes-base.scheduleTrigger` v`1.2`
- Purpose: Automated polling trigger every 5 minutes.
- Schedule: `every 5 minutes`
- Inbound: `none`
- Outbound: `Code - Load Config [branch=0]`

### Code - Load Config
- Type: `n8n-nodes-base.code` v`2`
- Purpose: Creates runtime config, Gmail query, and run timestamp.
- Code Size: `40 lines`
- Inbound: `Manual Trigger [branch=0], Schedule Trigger [branch=0]`
- Outbound: `HTTP - Sheets Read Header [branch=0]`

### HTTP - Sheets Read Header
- Type: `n8n-nodes-base.httpRequest` v`4.2`
- Purpose: Reads A1:B1 from target worksheet to validate header.
- HTTP Method: `GET`
- URL: `=https://sheets.googleapis.com/v4/spreadsheets/{{$json.config.spreadsheet_id}}/values:batchGet`
- Auth: `oAuth2Api`
- Timeout: `30000 ms`
- Query Parameters: `ranges=={{$json.config.worksheet_name}}!A1:B1`
- Inbound: `Code - Load Config [branch=0]`
- Outbound: `Code - Evaluate Header [branch=0]`

### Code - Evaluate Header
- Type: `n8n-nodes-base.code` v`2`
- Purpose: Compares header values against expected columns.
- Code Size: `17 lines`
- Inbound: `HTTP - Sheets Read Header [branch=0]`
- Outbound: `IF - Header Missing [branch=0]`

### IF - Header Missing
- Type: `n8n-nodes-base.if` v`2.2`
- Purpose: Branches to header write only when header is missing.
- Conditions: `1`
- Inbound: `Code - Evaluate Header [branch=0]`
- Outbound: `HTTP - Sheets Append Header [branch=0], Code - Rehydrate Config [branch=1]`

### HTTP - Sheets Append Header
- Type: `n8n-nodes-base.httpRequest` v`4.2`
- Purpose: Appends [Timestamp, Message Text] header row.
- HTTP Method: `POST`
- URL: `=https://sheets.googleapis.com/v4/spreadsheets/{{$json.config.spreadsheet_id}}/values/{{encodeURIComponent($json.config.worksheet_name + '!A1:B1')}}:append`
- Auth: `oAuth2Api`
- Timeout: `30000 ms`
- Query Parameters: `valueInputOption=USER_ENTERED; insertDataOption=INSERT_ROWS`
- Inbound: `IF - Header Missing [branch=0]`
- Outbound: `Code - Rehydrate Config [branch=0]`

### Code - Rehydrate Config
- Type: `n8n-nodes-base.code` v`2`
- Purpose: Restores config payload after branch merge.
- Code Size: `5 lines`
- Inbound: `IF - Header Missing [branch=1], HTTP - Sheets Append Header [branch=0]`
- Outbound: `HTTP - Gmail List Messages [branch=0]`

### HTTP - Gmail List Messages
- Type: `n8n-nodes-base.httpRequest` v`4.2`
- Purpose: Lists Gmail messages with unread/subject filters and max cap.
- HTTP Method: `GET`
- URL: `https://gmail.googleapis.com/gmail/v1/users/me/messages`
- Auth: `oAuth2Api`
- Timeout: `30000 ms`
- Query Parameters: `q=={{$json.config.query}}; maxResults=={{String($json.config.max_per_run)}}`
- Inbound: `Code - Rehydrate Config [branch=0]`
- Outbound: `Code - Expand Message IDs [branch=0]`

### Code - Expand Message IDs
- Type: `n8n-nodes-base.code` v`2`
- Purpose: Converts list to one item per message id/thread id.
- Code Size: `21 lines`
- Inbound: `HTTP - Gmail List Messages [branch=0]`
- Outbound: `HTTP - Gmail Get Message [branch=0]`

### HTTP - Gmail Get Message
- Type: `n8n-nodes-base.httpRequest` v`4.2`
- Purpose: Fetches full Gmail message payload for each id.
- HTTP Method: `GET`
- URL: `=https://gmail.googleapis.com/gmail/v1/users/me/messages/{{$json.messageId}}`
- Auth: `oAuth2Api`
- Timeout: `30000 ms`
- Query Parameters: `format=full`
- Inbound: `Code - Expand Message IDs [branch=0]`
- Outbound: `Code - Clean and Filter SC [branch=0]`

### Code - Clean and Filter SC
- Type: `n8n-nodes-base.code` v`2`
- Purpose: Extracts plain/html/subject text; cleans boilerplate; enforces SC marker; strips SC marker.
- Code Size: `219 lines`
- Inbound: `HTTP - Gmail Get Message [branch=0]`
- Outbound: `IF - Keep SC Messages [branch=0]`

### IF - Keep SC Messages
- Type: `n8n-nodes-base.if` v`2.2`
- Purpose: Keeps only messages that pass SC marker rule.
- Conditions: `1`
- Inbound: `Code - Clean and Filter SC [branch=0]`
- Outbound: `HTTP - Sheets Append Row [branch=0]`

### HTTP - Sheets Append Row
- Type: `n8n-nodes-base.httpRequest` v`4.2`
- Purpose: Appends [timestamp, cleaned message text] rows to sheet.
- HTTP Method: `POST`
- URL: `=https://sheets.googleapis.com/v4/spreadsheets/{{$json.config.spreadsheet_id}}/values/{{encodeURIComponent($json.config.worksheet_name + '!A:B')}}:append`
- Auth: `oAuth2Api`
- Timeout: `30000 ms`
- Query Parameters: `valueInputOption=USER_ENTERED; insertDataOption=INSERT_ROWS`
- Inbound: `IF - Keep SC Messages [branch=0]`
- Outbound: `IF - Mark As Read Needed [branch=0]`

### IF - Mark As Read Needed
- Type: `n8n-nodes-base.if` v`2.2`
- Purpose: Checks if mark-read action is enabled and target id exists.
- Conditions: `1`
- Inbound: `HTTP - Sheets Append Row [branch=0]`
- Outbound: `HTTP - Gmail Mark Read [branch=0]`

### HTTP - Gmail Mark Read
- Type: `n8n-nodes-base.httpRequest` v`4.2`
- Purpose: Removes UNREAD label from target Gmail message or thread.
- HTTP Method: `POST`
- URL: `=https://gmail.googleapis.com/gmail/v1/users/me/{{$json.mark_type === 'thread' ? 'threads' : 'messages'}}/{{$json.mark_target_id}}/modify`
- Auth: `oAuth2Api`
- Timeout: `30000 ms`
- Inbound: `IF - Mark As Read Needed [branch=0]`
- Outbound: `none`

