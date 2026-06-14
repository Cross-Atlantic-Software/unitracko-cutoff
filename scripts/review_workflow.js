export const meta = {
  name: 'review-aggregator',
  description: 'Adversarial review of the new cutoff-aggregator code + catalog quality, per-finding verification',
  phases: [
    { title: 'Review', detail: 'one agent per dimension' },
    { title: 'Verify', detail: 'adversarially confirm each finding' },
  ],
}

const FINDING_ITEM = {
  type: 'object',
  additionalProperties: false,
  properties: {
    title: { type: 'string' },
    file: { type: 'string' },
    location: { type: 'string' },
    severity: { type: 'string', enum: ['critical', 'high', 'medium', 'low'] },
    description: { type: 'string' },
    suggested_fix: { type: 'string' },
  },
  required: ['title', 'file', 'severity', 'description', 'suggested_fix'],
}
const FINDINGS = {
  type: 'object',
  additionalProperties: false,
  properties: { findings: { type: 'array', items: FINDING_ITEM } },
  required: ['findings'],
}
const VERDICT = {
  type: 'object',
  additionalProperties: false,
  properties: {
    isReal: { type: 'boolean' },
    severity: { type: 'string', enum: ['critical', 'high', 'medium', 'low', 'not-a-bug'] },
    reasoning: { type: 'string' },
  },
  required: ['isReal', 'severity', 'reasoning'],
}

const ROOT = 'D:/Backup/python/uni'
const DIMENSIONS = [
  { key: 'scrape', prompt: 'Review ' + ROOT + '/cutoffs/scrape.py for CORRECTNESS bugs only. Focus: the regex column-matching in map_table (could _CLOSING wrongly match an opening-rank column? does the lone-rank fallback pick the right column? MultiIndex flatten; comma/NA coercion via normalize; tolerant never-raise contract). Read the file and cutoffs/schema.py. Report only real bugs with evidence.' },
  { key: 'catalog', prompt: 'Review ' + ROOT + '/cutoffs/catalog.py for CORRECTNESS bugs only. Focus: ordered category regex (any rule wrongly shadowing another given the real exam names?), _classify_level, state regex false positives (e.g. Delhi/Goa substrings), merge_enrichment join-by-name and pick() precedence (Body preserves existing; Level/Metric/Notes prefer enrichment), probe bucket->status mapping. Read the file. Report only real bugs with evidence.' },
  { key: 'adapters', prompt: 'Review adapter files under ' + ROOT + '/cutoffs/adapters/ (_pdf.py, _js.py, generic.py, kcet.py, wbjee.py, mhtcet.py) plus cutoffs/source.py and cutoffs/registry.py. Focus: does GenericHTMLSource satisfy the ABC (per-instance meta vs class meta in __init_subclass__)? PDF/JS lazy-import + tolerant contract; mhtcet fetch_latest fallback; do all registered adapters return the unified schema? Report only real bugs with evidence.' },
  { key: 'ui', prompt: 'Review ' + ROOT + '/app.py for RUNTIME correctness against Streamlit 1.58 and the cutoffs query layer. Focus: st.column_config usage, width=stretch, the trend-chart query/groupby (could it KeyError or crash on empty/NA?), session_state keys, auto-ingest on first run, point-scrape tab. Also skim cutoffs/query.py for filter composition. Report only real bugs with evidence.' },
  { key: 'quality', prompt: 'Audit DATA quality of the exam catalog. Read ' + ROOT + '/cutoffs/catalog.py classification rules and consider the real Indian exams. Identify concrete MISCLASSIFICATIONS the keyword rules will produce (an exam that should be Medical but lands in Engineering; a state mis-detected; a wrong level). Give specific exam-name examples with wrong vs right value as findings.' },
]

phase('Review')
const reviewed = await pipeline(
  DIMENSIONS,
  d => agent(d.prompt, { label: 'review:' + d.key, phase: 'Review', schema: FINDINGS }),
  (review, d) => {
    const fs = (review && review.findings) || []
    if (!fs.length) return []
    return parallel(fs.map(f => () =>
      agent(
        'Adversarially VERIFY this code-review finding. Read the actual file under D:/Backup/python/uni and try to REFUTE it. ' +
        'Only confirm isReal=true if you can point to the specific code that exhibits the bug. Default to isReal=false if uncertain or if it is a stylistic nit.\n\n' +
        'Finding: ' + JSON.stringify(f),
        { label: 'verify:' + d.key, phase: 'Verify', schema: VERDICT }
      ).then(v => ({ ...f, verdict: v }))
    ))
  }
)

const all = reviewed.flat().filter(Boolean)
const confirmed = all.filter(f => f.verdict && f.verdict.isReal)
log('reviewed ' + all.length + ' findings; ' + confirmed.length + ' confirmed real')
return { confirmed, all_count: all.length }
