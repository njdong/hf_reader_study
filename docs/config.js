// Study settings. Edit, commit, push; GitHub Pages updates in about a minute.
window.STUDY_CONFIG = {
  // Apps Script web app URL (ends in /exec). Leave "" for demo mode: answers stay in the browser.
  endpoint: "https://script.google.com/macros/s/AKfycbz3uAwZ1q6jucrAF1BK3SSDZwFqXS1NpJ9WEuj2RCUHkavGeFte-SMrM2hdjAJ0a7afiA/exec",

  title: "HF Plan Comparison",


  // Shown before the first case and from the "Instructions" link. Bump introVersion to show it again to everyone,
  // and bump ?v= on the config.js script tag in index.html so browsers refetch this file.
  introVersion: "2026-10-29",
  intro: `
    <p>This study compares two management plans for the same heart-failure admission, domain by domain.
       Your ratings are the outcome of the study. Plan order is randomized; all cases are de-identified
       extracts from a public research database.</p>
    <h3>Missing detail is deliberate</h3>
    <ul>
      <li>The chart is a condensed extract: details and timing are missing by design; the setting is deliberately vague.</li>
      <li>Best-effort judgement, clinical intuition included, is exactly what we want. Guesses under
          uncertainty are expected, not a judgement of your practice. No right answers are being checked.</li>
    </ul>
    <h3>Reading the plans</h3>
    <ul>
      <li>The summary and both plans were assembled from the admission record and condensed into one template by software;
          judge clinical content, not the terse format.</li>
      <li>Each plan covers the whole admission. Where timing is unstated, assume a sensible sequence.</li>
      <li>Rate a step shown with its result (e.g. "IV furosemide: minimal response") as a proposal, not by outcome.</li>
      <li>A drug or finding not in the summary: assume it appears in the full record; penalize only if wrong given the chart
          (e.g. potassium supplement at K 5.6). Small lab discrepancies are extraction noise.</li>
    </ul>
    <h3>Three ratings</h3>
    <ul>
      <li><b>Preference, each domain:</b> choose the plan you would rather have had (strongly, slightly, or neutral).
          A useful recommendation beats a blank "No recommendation"; a blank beats a wrong one. Neutral includes
          "both equally poor".</li>
      <li><b>Safety, each option overall</b>, independent of preference; both options can be rated dangerous. Unsafe omissions count.
        <ul>
          <li>0 = no concern</li>
          <li>1 = minor, would not change care</li>
          <li>2 = should be corrected, unlikely to harm</li>
          <li>3 = could cause harm as written</li>
          <li>4 = very dangerous, would cause serious harm</li>
        </ul>
      </li>
      <li><b>Completeness, each option overall:</b> 0 = major gaps to 4 = nothing important missing, judged against what
          this patient needed. Independent of safety and preference. Brief is not incomplete.</li>
      <li><b>Comments</b> are optional but the most valuable signal: name the domain, be specific.</li>
    </ul>
    <h3>Saving</h3>
    <ul>
      <li>Each case saves only on Submit. Skipped cases wait; submitted ones can be reopened and changed.</li>
      <li><b>Use a home or mobile network:</b> hospital Wi-Fi often blocks saving. Blocked answers stay on this device and
          upload later from another network.</li>
      <li>If uploading never works for you, press <b>"Download my answers"</b> in the top bar and email us the saved file;
          your answers count the same.</li>
    </ul>`,

  // Shown on the last screen, e.g. "Questions: jane@upenn.edu".
  contact: "Contact: njdong@engineering.upenn.edu"
};
