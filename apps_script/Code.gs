/**
 * HF reader study: response collector.
 *
 * Setup (once):
 *   1. Create a Google Sheet. Extensions → Apps Script. Replace Code.gs with this file. Save.
 *   2. Run setup() once from the editor (approve the permission prompt). It creates two tabs:
 *        responses   one row per submitted item
 *        evaluators  paste evaluator codes in column A (from out/evaluators.csv)
 *   3. Deploy → New deployment → type "Web app".
 *        Execute as: Me      Who has access: Anyone
 *      Copy the URL that ends in /exec into docs/config.js (endpoint).
 *   4. After editing this code later: Deploy → Manage deployments → Edit → Version: New version.
 *      (Keeps the same URL. A "New deployment" would create a new URL.)
 */

var RESPONSES = 'responses';
var EVALUATORS = 'evaluators';
var HEADERS = [
  'received_at', 'study', 'items_version', 'evaluator', 'item_id', 'case_id', 'domain', 'position',
  'left_system', 'choice', 'score_A', 'comment', 'seconds_on_item', 'submitted_at', 'page_version', 'user_agent'
];
// choice is relative to the screen; score_A is relative to the systems (+2 = strongly prefers system A).
var CHOICE_SCORE = { strong_1: -2, slight_1: -1, neutral: 0, slight_2: 1, strong_2: 2 };

function setup() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var r = ss.getSheetByName(RESPONSES) || ss.insertSheet(RESPONSES);
  if (r.getLastRow() === 0) r.appendRow(HEADERS);
  r.setFrozenRows(1);
  var e = ss.getSheetByName(EVALUATORS) || ss.insertSheet(EVALUATORS);
  if (e.getLastRow() === 0) e.appendRow(['code', 'name (optional)', 'role (optional)']);
  e.setFrozenRows(1);
}

function doPost(e) {
  var d;
  try {
    d = JSON.parse(e.postData.contents);
  } catch (err) {
    return out_({ ok: false, error: 'bad_json' });
  }
  var code = String(d.evaluator || '').trim();
  if (!isEvaluator_(code)) return out_({ ok: false, error: 'unknown_evaluator' });
  if (!(d.choice in CHOICE_SCORE)) return out_({ ok: false, error: 'bad_choice' });
  var itemId = String(d.item_id || '');
  if (!/^[A-Za-z0-9_]+-[a-z]+$/.test(itemId)) return out_({ ok: false, error: 'bad_item' });

  var left = d.left_system === 'B' ? 'B' : 'A';
  var raw = CHOICE_SCORE[d.choice];          // + means the reader preferred Option 2
  var scoreA = left === 'A' ? -raw : raw;    // + means the reader preferred system A

  var row = [
    new Date(), text_(d.study, 64), text_(d.items_version, 40), code, itemId,
    text_(d.case_id, 32), text_(d.domain, 32), num_(d.position),
    left, d.choice, scoreA, text_(d.comment, 5000), num_(d.seconds),
    text_(d.submitted_at, 40), text_(d.page_version, 40), text_(d.user_agent, 300)
  ];
  var lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    sheet_(RESPONSES).appendRow(row);
  } finally {
    lock.releaseLock();
  }
  return out_({ ok: true });
}

// GET ?r=CODE  ->  {ok, done: [item ids already submitted by this evaluator]}
function doGet(e) {
  var code = String((e && e.parameter && e.parameter.r) || '').trim();
  if (!isEvaluator_(code)) return out_({ ok: false, error: 'unknown_evaluator' });
  var sh = sheet_(RESPONSES);
  var n = sh.getLastRow();
  var done = {};
  if (n > 1) {
    var col = HEADERS.indexOf('evaluator') + 1;
    var vals = sh.getRange(2, col, n - 1, 2).getValues();   // evaluator, item_id
    for (var i = 0; i < vals.length; i++) {
      if (String(vals[i][0]) === code) done[vals[i][1]] = true;
    }
  }
  return out_({ ok: true, done: Object.keys(done) });
}

function isEvaluator_(code) {
  if (!code) return false;
  var sh = sheet_(EVALUATORS);
  var n = sh.getLastRow();
  if (n < 2) return false;
  var vals = sh.getRange(2, 1, n - 1, 1).getValues();
  for (var i = 0; i < vals.length; i++) {
    if (String(vals[i][0]).trim() === code) return true;
  }
  return false;
}

function sheet_(name) {
  var sh = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(name);
  if (!sh) throw new Error('Missing sheet "' + name + '". Run setup() once.');
  return sh;
}

// Plain text only: trims length and stops values like "=SUM(...)" from becoming formulas.
function text_(v, max) {
  var s = v == null ? '' : String(v).slice(0, max);
  return /^[=+\-@]/.test(s) ? "'" + s : s;
}

function num_(v) {
  var x = Number(v);
  return isFinite(x) ? x : '';
}

function out_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}
