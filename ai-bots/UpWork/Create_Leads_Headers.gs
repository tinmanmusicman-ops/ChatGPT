/**
 * One-click setup for the Leads sheet headers used by
 * ai-bots/UpWork/n8n_lead_vetting_workflow.json
 */
function setLeadsHeaders() {
  var spreadsheetId = "1y1bvxJIiJB-XhdJAJkFH1ngyOrWB29RwJeiFALiQCWw";
  var sheetName = "Leads";

  var headers = [
    "rowNumber",
    "company",
    "website",
    "industry",
    "country",
    "notes",
    "status",
    "eligibility",
    "icp_classification",
    "tier",
    "confidence_score",
    "reasoning",
    "enriched_website",
    "manual_review",
    "manual_review_reason",
    "error_code",
    "processed_at_utc",
    "request_id"
  ];

  var ss = SpreadsheetApp.openById(spreadsheetId);
  var sheet = ss.getSheetByName(sheetName);
  if (!sheet) {
    throw new Error("Sheet not found: " + sheetName);
  }

  // Write A1:R1
  sheet.getRange(1, 1, 1, headers.length).setValues([headers]);
}

/**
 * Optional helper: fill rowNumber column for existing rows.
 * Row 1 is header, numbering starts at row 2.
 */
function fillRowNumbers() {
  var spreadsheetId = "1y1bvxJIiJB-XhdJAJkFH1ngyOrWB29RwJeiFALiQCWw";
  var sheetName = "Leads";

  var ss = SpreadsheetApp.openById(spreadsheetId);
  var sheet = ss.getSheetByName(sheetName);
  if (!sheet) {
    throw new Error("Sheet not found: " + sheetName);
  }

  var lastRow = sheet.getLastRow();
  if (lastRow < 2) {
    return;
  }

  var values = [];
  for (var row = 2; row <= lastRow; row++) {
    values.push([row]);
  }

  // Column A from row 2 downward
  sheet.getRange(2, 1, values.length, 1).setValues(values);
}
