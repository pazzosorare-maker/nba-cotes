/* Elements communs a toutes les pages : bouton « Actualiser » et mention legale.

   Le bouton appelle /api/refresh (fonction Vercel, voir api/refresh.js), qui lance l'actualisation des
   cotes et des donnees des joueurs sur GitHub. Quand les nouvelles donnees sont en ligne, la page se
   recharge (les selections de joueur et d'equipe sont gardees par le navigateur).
   En local (start.bat), cette fonction n'existe pas : le bouton l'indique et ne fait rien d'autre. */
(() => {
  const POLL_MS = 8000;
  const MAX_WAIT_RUN_MS = 25 * 60 * 1000;      // une actualisation complete dure quelques minutes
  const MAX_WAIT_START_MS = 90 * 1000;         // delai max entre la demande et le demarrage du workflow
  const MAX_WAIT_DEPLOY_MS = 5 * 60 * 1000;    // delai max entre la fin du workflow et la mise en ligne

  const style = document.createElement("style");
  style.textContent = `
    nav.tabs .refresh-btn { margin-left: auto; cursor: pointer; font: inherit; font-size: 13px; padding: 6px 12px;
      color: var(--text, #e8eaed); background: var(--bg, #0f1216); border: 1px solid var(--accent, #ff6a13); border-radius: 6px; }
    nav.tabs .refresh-btn:hover:not(:disabled) { background: var(--accent, #ff6a13); color: #0f1216; }
    nav.tabs .refresh-btn:disabled { cursor: progress; opacity: 0.7; border-color: var(--border, #262b33); }
    nav.tabs .refresh-btn .spin { display: inline-block; }
    nav.tabs .refresh-btn.busy .spin { animation: refresh-spin 1s linear infinite; }
    @keyframes refresh-spin { to { transform: rotate(360deg); } }
    @media (prefers-reduced-motion: reduce) { nav.tabs .refresh-btn.busy .spin { animation: none; } }
    .refresh-status { min-height: 18px; margin: -10px 0 14px; font-size: 12px; color: var(--muted, #8b93a1); }
    .refresh-status.is-error { color: #f0876e; }
    .site-note { margin: 22px auto 0; max-width: 780px; font-size: 11px; line-height: 1.5; color: var(--muted, #8b93a1); text-align: center; }
  `;
  document.head.append(style);

  const nav = document.querySelector("nav.tabs");
  const button = document.createElement("button");
  button.type = "button";
  button.className = "refresh-btn";
  button.innerHTML = '<span class="spin" aria-hidden="true">↻</span> Actualiser';
  button.title = "Met a jour les cotes Winamax et les donnees des joueurs";
  const status = document.createElement("div");
  status.className = "refresh-status";
  status.setAttribute("role", "status");
  status.setAttribute("aria-live", "polite");
  if (nav) {
    nav.append(button);
    nav.after(status);
  }

  const say = (text, isError = false) => {
    status.textContent = text;
    status.classList.toggle("is-error", isError);
  };
  const busy = on => {
    button.disabled = on;
    button.classList.toggle("busy", on);
  };
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
  const minutesText = seconds => (seconds < 90 ? "moins de 2 min" : `${Math.round(seconds / 60)} min`);

  async function api(method) {
    const response = await fetch("/api/refresh", { method, cache: "no-store" });
    let body = null;
    try { body = await response.json(); } catch (err) { /* reponse sans JSON : page 404 d'un serveur local */ }
    return { response, body };
  }

  // Horodatage des cotes actuellement affichees : il change des que les nouvelles donnees sont en ligne.
  async function oddsStamp() {
    try {
      const response = await fetch(`data/nba_odds.json?t=${Date.now()}`, { cache: "no-store" });
      return response.ok ? (await response.json()).scrapedAt : null;
    } catch (err) {
      return null;
    }
  }

  async function refresh() {
    busy(true);
    say("Demande d'actualisation...");
    try {
      const stampBefore = await oddsStamp();
      const requestedAt = Date.now();
      let started;
      try {
        started = await api("POST");
      } catch (err) {
        say("Actualisation impossible : serveur injoignable.", true);
        return;
      }
      const { response, body } = started;
      if (response.status === 404 || !body) { say("L'actualisation n'est disponible que sur la version en ligne du site.", true); return; }
      if (response.status === 429) {
        say(`Les donnees sont deja a jour (actualisees il y a ${minutesText(body.ageSeconds)}). Nouvelle actualisation possible dans ${minutesText(body.retryInSeconds)}.`);
        return;
      }
      if (!response.ok) { say(body.message || "Actualisation impossible pour le moment.", true); return; }
      const alreadyRunning = body.state === "running";

      // 1) attendre la fin du workflow
      const began = Date.now();
      let finished = false;
      while (Date.now() - began < MAX_WAIT_RUN_MS) {
        await sleep(POLL_MS);
        let poll;
        try { poll = await api("GET"); } catch (err) { continue; }   // coupure passagere : on reessaie
        const run = poll.body && poll.body.run;
        const isOurs = run && (alreadyRunning || Date.parse(run.createdAt) >= requestedAt - 15000);
        if (poll.body && poll.body.running) {
          say(`Actualisation en cours (${Math.round((Date.now() - began) / 1000)} s)...`);
          continue;
        }
        if (isOurs) {
          if (run.conclusion !== "success") {
            say("L'actualisation a echoue : les donnees affichees sont les dernieres disponibles.", true);
            return;
          }
          finished = true;
          break;
        }
        if (Date.now() - began > MAX_WAIT_START_MS) {
          say("L'actualisation n'a pas demarre : reessayez dans quelques minutes.", true);
          return;
        }
        say("En attente du demarrage...");
      }
      if (!finished) { say("L'actualisation prend plus de temps que prevu : rechargez la page dans quelques minutes.", true); return; }

      // 2) attendre que les nouvelles donnees soient en ligne
      const deployStart = Date.now();
      while (Date.now() - deployStart < MAX_WAIT_DEPLOY_MS) {
        say("Mise en ligne des nouvelles donnees...");
        const stamp = await oddsStamp();
        if (stamp && stamp !== stampBefore) {
          say("Donnees a jour, rechargement...");
          await sleep(400);
          location.reload();
          return;
        }
        await sleep(POLL_MS);
      }
      say("Actualisation terminee : si rien n'a change, il n'y a pas de nouvelles cotes. Rechargez la page pour verifier.");
    } finally {
      busy(false);
    }
  }
  button.addEventListener("click", refresh);

  // mention legale commune (le site est public)
  const note = document.createElement("p");
  note.className = "site-note";
  note.textContent = "Site non officiel, sans lien avec Winamax ni la NBA. Donnees issues de sources publiques, fournies a titre informatif : "
    + "ce ne sont pas des conseils de pari et rien ne garantit leur exactitude. Jouer comporte des risques : endettement, isolement, dependance. "
    + "Interdit aux mineurs. Aide : joueurs-info-service.fr.";
  (document.querySelector(".wrap") || document.body).append(note);
})();
