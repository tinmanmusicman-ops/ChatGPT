# n8n Lead Vetting Flowchart

## Mermaid Flowchart

```mermaid
flowchart TD
    A[Webhook Trigger<br/>POST lead-vetting-prod<br/>Body: rowNumber] --> B[Code: Parse and Validate Payload]
    B --> C[Google Sheets: Read Row by rowNumber]
    C --> D[Code: Normalize Lead Row]
    D --> E{Website already in sheet?}

    E -- Yes --> F[Code: Use Existing Website]
    E -- No --> G[HTTP: OpenAI Discover Website]
    G --> H[Code: Use Discovered Website]

    F --> I[HTTP: Firecrawl Scrape Website]
    H --> I

    I --> J[Code: Build AI Prompt Context<br/>Includes ICP rules + threshold]
    J --> K[HTTP: OpenAI Evaluate Lead]
    K --> L[Code: Parse and Validate AI JSON<br/>if confidence < 70 => manual_review]
    L --> M[Code: Compose Sheet Update]
    M --> N[Google Sheets: Update Row]
    N --> O[Respond Success JSON]
```

## Simple Text Version

1. Receive `rowNumber`.
2. Validate it.
3. Read that exact row from `Leads`.
4. Normalize row fields.
5. If website missing, ask OpenAI to find one.
6. Scrape website with Firecrawl.
7. Send lead + scraped content to OpenAI for fit scoring.
8. Validate JSON result.
9. Force manual review if confidence below 70.
10. Write results back to same row.
11. Return success response.
