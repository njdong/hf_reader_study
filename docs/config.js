// Study settings. Edit, commit, push; GitHub Pages updates in about a minute.
window.STUDY_CONFIG = {
  // Apps Script web app URL (ends in /exec). Leave "" for demo mode: answers stay in the browser.
  endpoint: "https://script.google.com/macros/s/AKfycbz3uAwZ1q6jucrAF1BK3SSDZwFqXS1NpJ9WEuj2RCUHkavGeFte-SMrM2hdjAJ0a7afiA/exec",

  title: "HF Plan Comparison",

  // Shown once before the first item. Plain HTML.
  intro: `
    <p>You will compare two treatment plans for the same patient, one clinical domain at a time.
       Each item takes about a minute. Answers save as you go, so you can stop and come back with the same link.</p>
    <ul>
      <li>Option 1 and Option 2 are two AI-generated plans. Their order changes from item to item.</li>
      <li><mark class="d">Highlighted text</mark> is where the plans differ. <span class="pill">both</span> marks identical content. — means the plan does not address that row.</li>
      <li>Choose the plan you prefer for that domain. Comments are optional.</li>
    </ul>`,

  // Shown on the last screen, e.g. "Questions: jane@upenn.edu".
  contact: "Contact: njdong@engineering.upenn.edu"
};
