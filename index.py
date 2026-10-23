# ==========================================
# FICHIER : README.md
# ==========================================
"""
# Veille média France

Collecte la presse française (Google Actualités + flux RSS) et les réseaux sociaux accessibles par API gratuite
(Mastodon, Reddit, Bluesky, YouTube), classe les contenus (thèmes, acteurs, tendance) et les affiche dans un
tableau de bord Streamlit. Une note de synthèse peut être rédigée par Claude (optionnel).

## Collecte par agents IA

Le mode par défaut du tableau de bord est **Agents IA (Claude)**. Au lieu d'exécuter des requêtes fixes, Claude pilote la collecte avec des outils (`collecter_presse`, `collecter_reseaux`, recherche web en option) :
1. il lance une collecte large sur vos mots-clés ;
2. il repère les acteurs, textes de loi et sujets émergents, puis relance des requêtes ciblées ;
3. il croise les sources et rend des **signaux** structurés (type, niveau faible/moyen/fort, acteurs, échéance, pourquoi c'est important pour un arbitrage ou une position parlementaire, sources) dans l'onglet "Signaux (agent IA)".

Le journal de l'agent (requêtes effectuées) est consultable pour auditer sa démarche. En ligne de commande :

Points d'attention :
- l'agent s'appuie uniquement sur ce que les outils renvoient, mais ses analyses peuvent comporter des erreurs : vérifiez les sources liées avant toute décision. Le mode "Scripts (sans IA)" reste disponible, gratuit.

## Installation locale

git clone https://github.com/<votre-compte>/veille-media-france.git
cd veille-media-france
python -m venv .venv && source .venv/bin/activate       # Windows : .venv\\Scripts\\activate
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # puis renseignez les clés voulues
streamlit run app.py

## Clés API (toutes optionnelles, une source sans clé est ignorée)

| Service | Variables | Où l'obtenir |
|---|---|---|
| Claude (note de synthèse) | `ANTHROPIC_API_KEY` | console Anthropic (facturation à l'usage) |
| YouTube | `YOUTUBE_API_KEY` | Google Cloud, YouTube Data API v3 (quota gratuit) |
| Reddit | `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET` | reddit.com/prefs/apps (type « script ») |
| Bluesky | `BSKY_HANDLE`, `BSKY_APP_PASSWORD` | Paramètres > Mots de passe d'application |
| Mastodon | aucune | timelines publiques par hashtag |

La presse ne demande aucune clé.

## Déploiement en ligne (Streamlit Community Cloud)

1. Poussez le dépôt sur GitHub (voir ci-dessous).
2. Sur share.streamlit.io : *New app*, choisissez le dépôt, branche `main`, fichier `app.py`.
3. *Advanced settings > Secrets* : collez le contenu de `.streamlit/secrets.toml.example` avec vos clés.
4. Déployez. Ne commitez jamais `secrets.toml` ni `.env` (déjà dans `.gitignore`).

## Mode temps réel

Dans la barre latérale, activez **Temps réel** et choisissez une fréquence (2 à 30 minutes). Le tableau de bord se
rafraîchit seul, sans recharger la page, et affiche :
- l'heure de la dernière actualisation et une notification pour les **nouveaux contenus** (colonne « nouveau » dans les tableaux) ;
- une **alerte** quand la part de contenus en tension dépasse le seuil réglé.

Précisions sur le « temps réel » : c'est une interrogation périodique (polling) des flux RSS et des API, pas un flux
continu. La presse via Google Actualités est en général décalée de quelques minutes à plusieurs dizaines de minutes.
La recherche YouTube est limitée à une actualisation toutes les 30 minutes pour ménager le quota gratuit
(10 000 unités par jour, 100 unités par recherche). Reddit et Bluesky appliquent aussi des limites de débit :
évitez une fréquence inférieure à 5 minutes avec beaucoup de mots-clés.
Sur Streamlit Community Cloud, une app inactive se met en veille : ce mode convient à un écran de suivi ouvert,
pas à une surveillance 24 h/24. Pour cela, hébergez l'app sur un serveur permanent.

## Publier sur Git

git init
git add .
git commit -m "Veille média France : agents de collecte et tableau de bord"
git branch -M main
git remote add origin https://github.com/<votre-compte>/veille-media-france.git
git push -u origin main

## Utilisation en ligne de commande

python -m veille.presse --mots "budget 2027" "49.3" --jours 3 --analyse
python -m veille.social --mots "grève" --hashtags greve manifestation --jours 3

Les fichiers sont écrits dans `veille_sortie/` et peuvent être chargés dans le tableau de bord (barre latérale).

## Structure

app.py              tableau de bord Streamlit
veille/agent.py     agent IA (Claude) qui pilote la collecte et rend des signaux
veille/presse.py    collecte presse, classification, note Claude
veille/social.py    collecte Mastodon, Reddit, Bluesky, YouTube
.streamlit/         thème et modèle de secrets

## Limites et bonnes pratiques

- X, Facebook, Instagram et TikTok n'ont pas d'API gratuite exploitable : non couverts.
- Seuls titres, résumés et liens sont collectés (pas de contournement de paywall). Respectez les conditions des plateformes.
- Aucun nom d'auteur n'est conservé pour les réseaux sociaux (RGPD).
- La tonalité (tension / apaisement) est un comptage de mots-clés : un indicateur, pas une mesure d'opinion.
- Les URL des flux RSS directs peuvent changer ; un flux en échec est ignoré.
"""


# ==========================================
# FICHIER : requirements.txt
# ==========================================
"""
streamlit>=1.50
feedparser>=6.0
anthropic>=0.60
pandas>=2.0
"""


# ==========================================
# FICHIER : .gitignore
# ==========================================
"""
__pycache__/
*.pyc
.venv/
.env
.streamlit/secrets.toml
veille_sortie/
donnees/*
!donnees/.gitkeep
.DS_Store
"""


# ==========================================
# FICHIER : .env.example
# ==========================================
"""
# Copiez en .env (jamais commité) ou exportez ces variables. Toutes les clés sont optionnelles.
ANTHROPIC_API_KEY=
YOUTUBE_API_KEY=Key=AIzaSyBc_CM9lnUdTgIX7xoF8lZqpzvrt6z_wuM
REDDIT_CLIENT_ID=
REDDIT_CLIENT_SECRET=
BSKY_HANDLE=
BSKY_APP_PASSWORD=
"""


# ==========================================
# FICHIER : .streamlit/config.toml
# ==========================================
"""
[theme]
primaryColor = "#1f4e8c"

[server]
headless = true
"""


# ==========================================
# FICHIER : .streamlit/secrets.toml.example
# ==========================================
"""
# Local : copiez en .streamlit/secrets.toml (ignoré par git)
# Streamlit Community Cloud : collez ce contenu dans App settings > Secrets
ANTHROPIC_API_KEY = ""
YOUTUBE_API_KEY = "AIzaSyBc_CM9lnUdTgIX7xoF8lZqpzvrt6z_wuM"
REDDIT_CLIENT_ID = ""
REDDIT_CLIENT_SECRET = ""
BSKY_HANDLE = ""
BSKY_APP_PASSWORD = ""
"""


# ==========================================
# FICHIER : app.py
# ==========================================
"""Tableau de bord Streamlit : veille média et réseaux sociaux France."""
import json
import os
from datetime import datetime, timedelta, timezone

import pandas as pd
import streamlit as st

# Les secrets Streamlit (Cloud ou .streamlit/secrets.toml) deviennent des variables d'environnement.
for _k in ("ANTHROPIC_API_KEY", "YOUTUBE_API_KEY", "REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET",
           "BSKY_HANDLE", "BSKY_APP_PASSWORD"):
    try:
        if _k in st.secrets:
            os.environ.setdefault(_k, str(st.secrets[_k]))
    except Exception:
        pass

from veille import agent, presse, social  # noqa: E402

st.set_page_config(page_title="Veille média France", page_icon="📰", layout="wide")


def to_df(rows, listes):
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"], utc=True, errors="coerce")
    for c in listes:
        df[c + "_txt"] = df[c].apply(lambda v: ", ".join(v) if isinstance(v, list) else "")
    return df


# --- Barre latérale ------------------------------------------------------------
st.sidebar.title("Paramètres")
mots = tuple(m.strip() for m in st.sidebar.text_area("Mots-clés (un par ligne)", "grève").splitlines() if m.strip())
jours = st.sidebar.slider("Période (jours)", 1, 14, 3)
sources = st.sidebar.multiselect("Réseaux sociaux", ["Mastodon", "Reddit", "Bluesky", "YouTube"],
                                 default=["Mastodon", "Reddit", "Bluesky", "YouTube"])
hashtags = tuple(h.strip().lstrip("#") for h in st.sidebar.text_input(
    "Hashtags (séparés par des virgules)", "").split(",") if h.strip()) or tuple(
    social.norm(m).replace(" ", "") for m in mots)
agent_mode = st.sidebar.radio(
    "Mode de collecte", ["Agents IA (Claude)", "Scripts (sans IA)"],
    help="Agents IA : Claude choisit et affine lui-même ses requêtes, croise les sources et extrait des signaux "
         "(facturé à l'usage). Scripts : collecte fixe, gratuite.") == "Agents IA (Claude)"
web = st.sidebar.checkbox("Autoriser la recherche web de Claude", value=False, disabled=not agent_mode,
                          help="Ajoute l'outil de recherche web de l'API (facturé en plus).")
st.sidebar.caption("Les clés API se configurent dans les secrets (voir README). Une source sans clé est ignorée.")
st.sidebar.divider()
fa = st.sidebar.file_uploader("…ou charger articles.json", type="json")
fs = st.sidebar.file_uploader("…ou charger social.json", type="json")
st.sidebar.divider()
live = st.sidebar.toggle("Temps réel (actualisation automatique)", value=False)
interval = st.sidebar.slider("Fréquence (minutes)", 2, 30, 5, disabled=not live)
seuil_alerte = st.sidebar.slider("Alerte si tension ≥ (%)", 30, 100, 60)
if st.sidebar.button("Actualiser maintenant"):
    st.cache_data.clear()

# Cache aligné sur la fréquence : en mode temps réel, chaque cycle récupère des données fraîches.
TTL = max(60, interval * 60 - 5) if live else 900


@st.cache_data(ttl=TTL, show_spinner="Collecte de la presse…")
def get_presse(mots: tuple, jours: int):
    return presse.collecter(list(mots), jours)


@st.cache_data(ttl=TTL, show_spinner="Collecte des réseaux sociaux…")
def get_social_libre(mots: tuple, hashtags: tuple, jours: int, sources: tuple):
    seuil = datetime.now(timezone.utc) - timedelta(days=jours)
    posts = []
    if "Mastodon" in sources:
        posts += social.mastodon(list(hashtags), seuil)
    if "Reddit" in sources:
        posts += social.reddit(list(mots), seuil, jours)
    if "Bluesky" in sources:
        posts += social.bluesky(list(mots), seuil)
    return posts


@st.cache_data(ttl=max(TTL, 1800), show_spinner=False)  # la recherche YouTube coûte 100 unités de quota
def get_youtube(mots: tuple, jours: int):
    return social.youtube(list(mots), datetime.now(timezone.utc) - timedelta(days=jours))


@st.cache_data(ttl=max(TTL, 900), show_spinner="L’agent IA mène la veille (1 à 2 minutes)…")
def get_agent(mots: tuple, jours: int, sources: tuple, web: bool):
    return agent.run_agent(list(mots), jours, plateformes=list(sources), web=web)


def get_social(mots, hashtags, jours, sources):
    posts = get_social_libre(mots, hashtags, jours, sources)
    if "YouTube" in sources:
        posts = posts + get_youtube(mots, jours)
    vus, uniques = set(), []
    for p in sorted(posts, key=lambda x: x["date"], reverse=True):
        if p["url"] not in vus:
            vus.add(p["url"])
            uniques.append(p)
    return uniques

st.title("Veille média France")


@st.fragment(run_every=interval * 60 if live else None)
def dashboard():
    # --- Données -----------------------------------------------------------------------
    signaux, journal = None, []
    if fa or fs:
        arts = json.loads(fa.getvalue()).get("articles", []) if fa else []
        posts = json.loads(fs.getvalue()).get("posts", []) if fs else []
    else:
        if not mots:
            st.warning("Saisissez au moins un mot-clé.")
            return
        if agent_mode:
            if not os.environ.get("ANTHROPIC_API_KEY"):
                st.error("Le mode Agents IA nécessite ANTHROPIC_API_KEY (voir README). "
                         "Choisissez « Scripts (sans IA) » pour une collecte gratuite.")
                return
            try:
                res = get_agent(mots, jours, tuple(sources), web)
            except Exception as e:
                st.error(f"Erreur de l’agent : {e}")
                return
            arts, posts, signaux, journal = res["articles"], res["posts"], res["resultats"], res["journal"]
        else:
            arts = get_presse(mots, jours)
            posts = get_social(mots, hashtags, jours, tuple(sources)) if sources else []

    dfA, dfS = to_df(arts, ["themes", "acteurs"]), to_df(posts, ["hashtags"])

    # --- Nouveautés et alerte ---
    urls = {a["url"] for a in arts} | {p["url"] for p in posts}
    deja = st.session_state.get("vus", set())
    nouveaux = (urls - deja) if deja else set()
    st.session_state["vus"] = deja | urls
    if live and nouveaux:
        st.toast(f"{len(nouveaux)} nouveau(x) contenu(x)", icon="🔔")
    st.caption(f"Dernière actualisation : {datetime.now().strftime('%H:%M:%S')}"
               + (f" · prochaine dans {interval} min" if live else " · mode manuel"))
    for d in (dfA, dfS):
        if not d.empty:
            d["nouveau"] = d["url"].isin(nouveaux)

    # --- Filtres ---------------------------------------------------------------------------
    c1, c2, c3 = st.columns([2, 2, 3])
    themes = sorted({t for l in dfA.get("themes", []) for t in l}) if not dfA.empty else []
    th = c1.multiselect("Thèmes", themes)
    td = c2.multiselect("Tendance", ["tension", "apaisement", "neutre"])
    q = c3.text_input("Recherche").lower()

    if not dfA.empty:
        if th:
            dfA = dfA[dfA["themes"].apply(lambda l: any(t in l for t in th))]
        if td:
            dfA = dfA[dfA["tendance"].isin(td)]
        if q:
            dfA = dfA[(dfA["titre"] + " " + dfA["resume"]).str.lower().str.contains(q, regex=False)]
    if not dfS.empty:
        if td:
            dfS = dfS[dfS["tendance"].
