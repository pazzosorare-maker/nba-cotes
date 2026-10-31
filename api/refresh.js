// Fonction Vercel du bouton « Actualiser ».
//   GET  /api/refresh : etat de la derniere actualisation (en cours ou non, date, resultat)
//   POST /api/refresh : declenche le workflow GitHub « refresh.yml » (cotes + donnees)
//
// Le jeton GitHub reste cote serveur (variables d'environnement Vercel) : le navigateur ne le voit jamais.
// Protection contre l'abus d'un bouton public : une seule actualisation a la fois, et un delai minimum
// entre deux actualisations (REFRESH_COOLDOWN_MIN, 15 min par defaut), planifiees comprises.
//
// Variables d'environnement :
//   GITHUB_REPO            proprietaire/depot, ex. monpseudo/nba-cotes
//   GITHUB_TOKEN           jeton « fine-grained » limite a ce depot, droit Actions : Read and write
//   GITHUB_BRANCH          branche du workflow (defaut : main)
//   REFRESH_COOLDOWN_MIN   delai minimum entre deux actualisations (defaut : 15)
//   FULL_REFRESH_MIN       delai apres lequel une actualisation redevient « complete » (defaut : 60)

const WORKFLOW_FILE = "refresh.yml";
const API = "https://api.github.com";

const minutes = (name, fallback) => {
  const value = Number(process.env[name]);
  return Number.isFinite(value) && value >= 0 ? value : fallback;
};

async function github(path, init = {}) {
  const response = await fetch(`${API}${path}`, {
    ...init,
    headers: {
      Accept: "application/vnd.github+json",
      Authorization: `Bearer ${process.env.GITHUB_TOKEN}`,
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "nba-cotes-refresh",
      ...(init.headers || {}),
    },
  });
  if (!response.ok && response.status !== 204) {
    const detail = await response.text().catch(() => "");
    throw new Error(`GitHub ${response.status} sur ${path} : ${detail.slice(0, 200)}`);
  }
  return response.status === 204 ? null : response.json();
}

// Le mode (fast/full) figure a la fin du titre du run : « Actualisation full ».
const modeOf = run => (/full\s*$/.test(run.display_title || run.name || "") ? "full" : "fast");

const summarize = run =>
  run && {
    id: run.id,
    status: run.status,            // queued | in_progress | completed
    conclusion: run.conclusion,    // success | failure | cancelled | null
    mode: modeOf(run),
    createdAt: run.created_at,
    updatedAt: run.updated_at,
  };

function sameSite(req) {
  const origin = req.headers.origin;
  if (!origin) return true;        // appel direct (outils, tests)
  try {
    return new URL(origin).host === req.headers.host;
  } catch (err) {
    return false;
  }
}

module.exports = async (req, res) => {
  res.setHeader("Cache-Control", "no-store");
  if (req.method !== "GET" && req.method !== "POST") {
    res.setHeader("Allow", "GET, POST");
    return res.status(405).json({ error: "method_not_allowed" });
  }
  const repo = process.env.GITHUB_REPO;
  if (!repo || !process.env.GITHUB_TOKEN) {
    return res.status(503).json({ error: "not_configured", message: "Actualisation non configuree sur ce site (GITHUB_REPO / GITHUB_TOKEN)." });
  }

  try {
    const { workflow_runs: runs = [] } = await github(`/repos/${repo}/actions/workflows/${WORKFLOW_FILE}/runs?per_page=20`);
    const active = runs.find(run => run.status !== "completed");
    const newest = runs[0];
    const now = Date.now();

    if (req.method === "GET") {
      return res.status(200).json({ running: Boolean(active), run: summarize(active || newest) || null });
    }

    if (!sameSite(req)) return res.status(403).json({ error: "forbidden" });

    if (active) {
      return res.status(202).json({ state: "running", run: summarize(active) });
    }

    const cooldownSeconds = minutes("REFRESH_COOLDOWN_MIN", 15) * 60;
    const sinceNewest = newest ? (now - Date.parse(newest.created_at)) / 1000 : Infinity;
    if (sinceNewest < cooldownSeconds) {
      return res.status(429).json({
        error: "cooldown",
        ageSeconds: Math.round(sinceNewest),
        retryInSeconds: Math.ceil(cooldownSeconds - sinceNewest),
      });
    }

    // Statistiques des joueurs (basketball-reference) : au plus une fois par FULL_REFRESH_MIN.
    const lastFull = runs.find(run => run.status === "completed" && run.conclusion === "success" && modeOf(run) === "full");
    const fullAgeSeconds = lastFull ? (now - Date.parse(lastFull.created_at)) / 1000 : Infinity;
    const mode = fullAgeSeconds > minutes("FULL_REFRESH_MIN", 60) * 60 ? "full" : "fast";

    await github(`/repos/${repo}/actions/workflows/${WORKFLOW_FILE}/dispatches`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ref: process.env.GITHUB_BRANCH || "main", inputs: { mode } }),
    });
    return res.status(202).json({ state: "started", mode, requestedAt: new Date(now).toISOString() });
  } catch (err) {
    console.error(err);
    return res.status(502).json({ error: "github_error", message: "Impossible de joindre GitHub pour le moment." });
  }
};
