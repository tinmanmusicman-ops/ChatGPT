const base = $items('08 rehydrate_config', 0, 0)[0]?.json;
if (!base?.config) throw new Error('E_CFG_MISSING: config unavailable');

const cfg = base.config;
const runTimestamp = base.runTimestamp;
const debugDeep = cfg.debug_deep !== false;
const debugTrace = [];

function preview(text, max = 180) {
  const t = String(text || '');
  return t.length > max ? `${t.slice(0, max)}...` : t;
}

function logStage(stage, data = {}) {
  if (!debugDeep) return;
  const entry = {
    stage,
    at: new Date().toISOString(),
    ...data,
  };
  debugTrace.push(entry);
  console.log(`[RegEx][${stage}] ${JSON.stringify(entry)}`);
}

const RE_SCRIPT_STYLE = /<\s*(script|style)[^>]*>[\s\S]*?<\s*\/\s*\1\s*>/gi;
const RE_TAG = /<[^>]+>/g;
const RE_BR = /<\s*br\s*\/?>/gi;
const RE_P = /<\s*\/\s*p\s*>/gi;
const RE_QUOTED = /^\s*(On .+ wrote:|> .+|>.+|-----Original Message-----|From: .+|Sent: .+|Subject: .+)\s*$/m;
const RE_SIGNATURE = /^\s*(--|\u2014)\s*$/mi;
const RE_ANGLE_URL = /<\s*https?:\/\/[^>]+>/gi;

const BOILERPLATE_PHRASES = [
  'HELP CENTER',
  'HELP FORUM',
  "This email was sent to you because you indicated that you'd like to receive email notifications for text messages",
  'update your email notification settings',
  'Google LLC',
  'Amphitheatre Pkwy',
  'Mountain View CA',
  'YOUR ACCOUNT',
];

const BOILERPLATE_PATTERNS = [
  /^\s*help\s+center\s*$/i,
  /^\s*help\s+forum\s*$/i,
  /this email was sent to you because you indicated that you.*receive email notifications for text messages/i,
  /if you don't want to receive such.*/i,
  /update your email notification settings/i,
  /google\s+llc/i,
  /amphitheatre\s+pkwy/i,
  /mountain\s+view\s+ca/i,
  /^\s*your\s+account\s*$/i,
  /^>+\s*.*$/i,
];

const BOILERPLATE_START_PATTERNS = [
  /this email was sent to you because you indicated/i,
  /if you don't want to receive/i,
  /help\s+center/i,
  /help\s+forum/i,
  /update your email notification settings/i,
  /google\s+llc/i,
  /amphitheatre/i,
  /mountain\s+view\s+ca/i,
  /your\s+account/i,
];

function findFooterIndex(text) {
  let earliest = null;
  for (const pat of BOILERPLATE_START_PATTERNS) {
    const m = text.match(pat);
    if (m && m.index !== undefined) {
      if (earliest === null || m.index < earliest) earliest = m.index;
    }
  }
  return earliest;
}

function truncateAtFooter(text) {
  const earliest = findFooterIndex(text);
  if (earliest !== null) return text.slice(0, earliest).trimEnd();
  return text;
}

function dropBoilerplateLines(lines) {
  const kept = [];
  let droppedPhrase = 0;
  let droppedPattern = 0;
  for (const ln of lines) {
    const up = String(ln || '').trim();
    if (!up) {
      kept.push(ln);
      continue;
    }
    if (BOILERPLATE_PHRASES.some((p) => up.toUpperCase().includes(String(p).toUpperCase()))) {
      droppedPhrase += 1;
      continue;
    }
    if (BOILERPLATE_PATTERNS.some((p) => p.test(up))) {
      droppedPattern += 1;
      continue;
    }
    kept.push(ln);
  }
  let text = kept.join('\n');
  text = text.replace(/^(?:\s*\n)+/, '').replace(/(?:\s*\n)+$/, '');
  return {
    lines: text.split('\n'),
    droppedPhrase,
    droppedPattern,
  };
}

function postFilters(text, sourceTag) {
  const input = String(text || '');
  let out = input.replace(RE_ANGLE_URL, ' ');
  const footerIndex = findFooterIndex(out);
  out = truncateAtFooter(out);
  const dropped = dropBoilerplateLines(out.split('\n'));
  out = dropped.lines.join('\n');
  out = out.replace(/\bIf you don't.*$/i, '').replace(/\bsuch\s*\.$/i, '');
  logStage('post_filters', {
    source: sourceTag,
    input_len: input.length,
    output_len: out.length,
    footer_index: footerIndex,
    dropped_phrase_lines: dropped.droppedPhrase,
    dropped_pattern_lines: dropped.droppedPattern,
    preview: preview(out),
  });
  return out;
}

function htmlToCleanText(html) {
  const input = String(html || '');
  let out = input;
  out = out.replace(RE_SCRIPT_STYLE, ' ');
  out = out.replace(RE_BR, '\n').replace(RE_P, '\n').replace(RE_ANGLE_URL, ' ').replace(RE_TAG, ' ');
  out = truncateAtFooter(out);
  out = out.replace(/\r\n/g, '\n');

  const lines = out.split('\n');
  const cleaned = [];
  let removedQuoted = 0;
  let signatureStop = false;
  for (const ln of lines) {
    if (RE_QUOTED.test(ln)) {
      removedQuoted += 1;
      continue;
    }
    if (RE_SIGNATURE.test(ln)) {
      signatureStop = true;
      break;
    }
    cleaned.push(ln);
  }

  const dropped = dropBoilerplateLines(cleaned);
  out = dropped.lines.join('\n');
  out = out.replace(/[\u200B\u200C\u200D\uFEFF]/g, '');
  out = out.replace(/\n{3,}/g, '\n\n').replace(/[ \t]{2,}/g, ' ');
  out = out
    .split('\n')
    .map((ln) => ln.trim())
    .join('\n')
    .replace(/\n{3,}/g, '\n\n')
    .replace(/\b(such\s*\.)$/i, '')
    .replace(/\bIf you don't.*$/i, '');
  out = out.trim();

  logStage('html_to_clean_text', {
    input_len: input.length,
    output_len: out.length,
    removed_quoted_lines: removedQuoted,
    signature_stop: signatureStop,
    dropped_phrase_lines: dropped.droppedPhrase,
    dropped_pattern_lines: dropped.droppedPattern,
    preview: preview(out),
  });
  return out;
}

function b64urlDecode(data) {
  if (!data) return '';
  const normalized = String(data).replace(/-/g, '+').replace(/_/g, '/');
  const pad = '='.repeat((4 - (normalized.length % 4)) % 4);
  return Buffer.from(normalized + pad, 'base64').toString('utf8');
}

function extractFromPayload(payload) {
  if (!payload) return { text: '', source: 'none', plain_count: 0, html_count: 0 };
  const out = { textPlain: [], textHtml: [] };
  let partCount = 0;

  const walk = (part) => {
    if (!part) return;
    partCount += 1;
    const mime = String(part.mimeType || '').toLowerCase();
    const bodyData = part.body?.data;
    if (mime === 'text/plain' && bodyData) out.textPlain.push(b64urlDecode(bodyData));
    if (mime === 'text/html' && bodyData) out.textHtml.push(b64urlDecode(bodyData));
    if (Array.isArray(part.parts)) part.parts.forEach(walk);
  };

  walk(payload);

  logStage('payload_walk', {
    part_count: partCount,
    plain_count: out.textPlain.length,
    html_count: out.textHtml.length,
  });

  if (out.textPlain.length) {
    return {
      text: postFilters(out.textPlain[0], 'text/plain'),
      source: 'text/plain',
      plain_count: out.textPlain.length,
      html_count: out.textHtml.length,
    };
  }
  if (out.textHtml.length) {
    return {
      text: postFilters(htmlToCleanText(out.textHtml[0]), 'text/html'),
      source: 'text/html',
      plain_count: out.textPlain.length,
      html_count: out.textHtml.length,
    };
  }
  return { text: '', source: 'none', plain_count: 0, html_count: 0 };
}

logStage('start', {
  message_id: String($json.id || ''),
  thread_id: String($json.threadId || ''),
  has_payload: Boolean($json.payload),
  has_snippet: Boolean($json.snippet),
  has_subject: Boolean($json.subject),
});

const payload = $json.payload || {};
const extractedResult = extractFromPayload(payload);
let extracted = extractedResult.text;

logStage('extract_result', {
  source: extractedResult.source,
  plain_count: extractedResult.plain_count,
  html_count: extractedResult.html_count,
  extracted_len: String(extracted || '').length,
  preview: preview(extracted),
});

if (!extracted) {
  const fallbackText = String($json.snippet || $json.subject || '(no content)');
  extracted = postFilters(fallbackText, 'snippet_or_subject');
  logStage('fallback_used', {
    fallback_len: fallbackText.length,
    output_len: extracted.length,
    preview: preview(extracted),
  });
}

const beforePrefixStrip = extracted;
extracted = extracted.replace(/^\s*Google Voice[:\-\s]*/i, '');
if (beforePrefixStrip !== extracted) {
  logStage('prefix_strip_google_voice', {
    before_len: beforePrefixStrip.length,
    after_len: extracted.length,
    before_preview: preview(beforePrefixStrip),
    after_preview: preview(extracted),
  });
}

const SC_PATTERN = /\bSC\b/;
const hasMarker = SC_PATTERN.test(extracted);
logStage('marker_check', {
  has_marker: hasMarker,
  final_len: extracted.length,
  final_preview: preview(extracted),
});

return [{
  json: {
    id: String($json.id || ''),
    threadId: String($json.threadId || ''),
    keep: hasMarker,
    reason: hasMarker ? '' : 'No SC marker',
    extracted_text: extracted,
    config: cfg,
    runTimestamp,
    debug_deep_enabled: debugDeep,
    debug_trace: debugTrace,
  }
}];
