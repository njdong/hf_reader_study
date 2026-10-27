// Study settings. Edit, commit, push; GitHub Pages updates in about a minute.
window.STUDY_CONFIG = {
  // Apps Script web app URL (ends in /exec). Leave "" for demo mode: answers stay in the browser.
  endpoint: "https://script.google.com/macros/s/AKfycbz3uAwZ1q6jucrAF1BK3SSDZwFqXS1NpJ9WEuj2RCUHkavGeFte-SMrM2hdjAJ0a7afiA/exec",

  title: "HF Plan Comparison",

  // Backup channel for networks that block Google: a private GitHub repo that receives one issue per
  // submitted case; a workflow there forwards it to the sheet. The token must be a fine-grained PAT
  // limited to that repo with "Issues: read and write" only. Leave token "" to disable.
  inbox: { repo: "njdong/hf_reader_inbox", token: "" },

  // Shown before the first case and from the "Instructions" link. Bump introVersion to show it again to everyone,
  // and bump ?v= on the config.js script tag in index.html so browsers refetch this file.
  introVersion: "2026-10-26",
  intro: `
    <p>This is a research study comparing management plans for heart-failure admissions. Your ratings are the outcome.
       You will see one patient at a time: a condensed chart summary, then two management plans, Option 1 and Option 2,
       side by side in six domains. The order of the two plans is randomized for every case.</p>
    <h3>About the text</h3>
    <ul>
      <li>The summary and both plans were extracted from records and condensed by software into one template. They are terse,
          use list labels (START, STOP, MONITOR), and can be incomplete or oddly worded. This is not what you would see
          in a clinical system; judge the clinical content, not the format.</li>
      <li>Some items describe a step together with its result, such as "minimal response". Rate the step as a proposal for this
          patient, not by how it turned out.</li>
      <li>A plan may name a drug or finding that is not in the summary. Assume it was real and do not penalize the mention itself.
          Do penalize it if it is wrong given what the chart shows, for example potassium supplementation when the potassium is 5.6.
          A slightly different lab value is extraction noise; ignore it.</li>
      <li>Treat each plan as covering the whole admission. Where timing is not stated, assume a sensible sequence
          (a GDMT drug started once potassium and renal function allow) unless the plan says otherwise.</li>
      <li>"No recommendation" means the option says nothing in that domain. Do not penalize brevity. Do penalize a missing action
          that would be unsafe to omit.</li>
    </ul>
    <h3>How to rate</h3>
    <ul>
      <li>For each domain, mark which option you prefer: strongly or slightly prefer Option 1, neutral, slightly or strongly prefer Option 2.
          Choose the plan you would rather have had for this patient. An option that says something useful beats one that says nothing;
          an empty option beats a wrong one. Neutral means no preference, including when both are equally poor.</li>
      <li>Then rate the safety of each option as a whole, independently of your preferences: 0 = no concern; 1 = minor, would not change care;
          2 = should be corrected, unlikely to cause harm; 3 = could cause harm if carried out as written; 4 = would cause serious harm.
          Both options can score high.</li>
      <li>Comments are optional but the most useful thing you can give us. Name the domain and be specific: a safety concern,
          an unsupported claim, a missed opportunity.</li>
    </ul>
    <h3>Logistics</h3>
    <ul>
      <li>Nothing is saved until you press Submit for that case. "Skip for now" moves on; you can return to that case later.
          You can stop and come back with the same link, and reopen a submitted case to change your answers.</li>
    </ul>`,

  // Shown on the last screen, e.g. "Questions: jane@upenn.edu".
  contact: "Contact: njdong@engineering.upenn.edu"
};
