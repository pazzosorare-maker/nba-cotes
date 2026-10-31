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

class GithubError extends Error {
  constructor(status, path) {
    super(`GitHub ${status} sur ${path}`);
    this.status = status;
  }
}

// Message sans secret, assez precis pour corriger la configuration.
function hintFor(status) {
  if (status === 401) return "GitHub refuse le jeton (invalide, expire ou mal copie) : verifiez GITHUB_TOKEN dans Vercel.";
  if (status === 403) return "Le jeton n'a pas le droit « Actions : Read and write » sur ce depot, ou GitHub limite les appels.";
  if (status === 404) return "Depot ou workflow introuvable : verifiez GITHUB_REPO (pseudo/depot) et la presence de .github/workflows/refresh.yml sur la branche principale.";
  return "Impossible de joindre GitHub pour le moment.";
}

async function statusOf(path) {
  try {
    const response = await fetch(`${API}${path}`, {
      headers: {
        Accept: "application/vnd.github+json",
        Authorization: `Bearer ${process.env.GITHUB_TOKEN}`,
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "nba-cotes-refresh",
      },
    });
    return response.status;
  } catch (err) {
    return 0;
  }
}

// GET /api/refresh?check=1 : controle pas a pas de la configuration (aucun secret n'est renvoye).
async function checkConfiguration(repo) {
  const token = process.env.GITHUB_TOKEN || "";
  const report = {
    repo,
    repoFormatOk: /^[\w.-]+\/[\w.-]+$/.test(repo),
    tokenLooksValid: /^(github_pat_|ghp_)[\w]+$/.test(token),
    branch: process.env.GITHUB_BRANCH || "main",
  };
  if (!report.repoFormatOk) {
    return { ...report, diagnosis: "GITHUB_REPO doit avoir la forme pseudo/depot, sans https://, sans .git, sans espace." };
  }
  if (!report.tokenLooksValid) {
    return { ...report, diagnosis: "GITHUB_TOKEN a un format inattendu : il doit commencer par github_pat_ et ne contenir ni espace ni retour a la ligne." };
  }
  report.repoStatus = await statusOf(`/repos/${repo}`);
  report.workflowStatus = await statusOf(`/repos/${repo}/actions/workflows/${WORKFLOW_FILE}`);
  report.runsStatus = await statusOf(`/repos/${repo}/actions/workflows/${WORKFLOW_FILE}/runs?per_page=1`);
  const { repoStatus: r, workflowStatus: w, runsStatus: s } = report;
  if (r === 401 || w === 401 || s === 401) report.diagnosis = hintFor(401);
  else if (r === 404) report.diagnosis = "Depot introuvable avec ce jeton : GITHUB_REPO est faux (pseudo/depot, majuscules comprises), ou le jeton n'a pas acces a ce depot (« Only select repositories » : choisissez-le).";
  else if (w === 404) report.diagnosis = "Le depot est bon mais .github/workflows/refresh.yml est absent de la branche principale : creez ce fichier sur GitHub.";
  else if (s === 403 || w === 403 || r === 403) report.diagnosis = hintFor(403);
  else if (r === 200 && w === 200 && s === 200) report.diagnosis = "Configuration correcte : depot, workflow et jeton sont bons. Si le bouton echoue encore, verifiez que le jeton a bien « Actions : Read and write » (le declenchement l'exige) et que la branche (GITHUB_BRANCH, main par defaut) existe.";
  else report.diagnosis = "Reponses inattendues de GitHub : voir les codes ci-dessus.";
  return report;
}

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
    console.error(`GitHub ${response.status} sur ${path} : ${detail.slice(0, 200)}`);
    throw new GithubError(response.status, path);
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

  if (req.method === "GET" && new URL(req.url || "/", "http://x").searchParams.has("check")) {
    return res.status(200).json(await checkConfiguration(repo));
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
    return res.status(502).json({ error: "github_error", githubStatus: err.status || 0, message: hintFor(err.status) });
  }
};
