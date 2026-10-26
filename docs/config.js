// Study settings. Edit, commit, push; GitHub Pages updates in about a minute.
window.STUDY_CONFIG = {
  // Apps Script web app URL (ends in /exec). Leave "" for demo mode: answers stay in the browser.
  endpoint: "https://script.google.com/macros/s/AKfycbz3uAwZ1q6jucrAF1BK3SSDZwFqXS1NpJ9WEuj2RCUHkavGeFte-SMrM2hdjAJ0a7afiA/exec",

  title: "HF Plan Comparison",

  // Shown once before the first item. Plain HTML.
  intro: `
    <p>You will see one patient case at a time: the chart as it stood in the first 12 hours of admission, followed by two
       management plans set side by side in six domains. Each case takes about 8 minutes. Answers save as you submit each case,
       so you can stop and come back with the same link.</p>
    <ul>
      <li>Option 1 and Option 2 are two treatment plans for the same patient. Their order changes from case to case.</li>
      <li>For each domain, choose which option you prefer. Then rate any safety concern in each option from 0 to 4.</li>
      <li>Lines marked "details" expand to show the full reasoning or contingency text behind a plan item.</li>
      <li>Comments are optional but valuable: a safety concern, an unsupported fact, or a missed opportunity.</li>
    </ul>`,

  // Shown on the last screen, e.g. "Questions: jane@upenn.edu".
  contact: "Contact: njdong@engineering.upenn.edu"
};
