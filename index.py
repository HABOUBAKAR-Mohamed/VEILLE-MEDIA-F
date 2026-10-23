"""Tableau de bord Streamlit : veille média et réseaux sociaux France (fichier unique, corrigé)."""
import base64
import html
import json
import os
import re
import unicodedata
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import pandas as pd
import streamlit as st

# DOIT être le premier appel Streamlit
st.set_page_config(page_title="Veille média France", page_icon="📰", layout="wide")

# Les secrets Streamlit deviennent des variables d'environnement
for _k in ("ANTHROPIC_API_KEY", "YOUTUBE_API_KEY", "REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET",
           "BSKY_HANDLE", "BSKY_APP_PASSWORD"):
    try:
        if _k in st.secrets:
            os.environ.setdefault(_k, str(st.secrets[_k]))
    except Exception:
        pass

MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5")
UA = "veille-media-france/1.0 (veille affaires publiques)"

# =============================================================================
# PRESSE
# =============================================================================
GOOGLE_NEWS = "https://news.google.com/rss/search?q={q}&hl=fr&gl=FR&ceid=FR:fr"

FLUX_DIRECTS = {
    "Le Monde": "https://www.lemonde.fr/rss/une.xml",
    "Le Monde - Société": "https://www.lemonde.fr/societe/rss_full.xml",
    "Le Monde - Économie": "https://www.lemonde.fr/economie/rss_full.xml",
    "Le Figaro": "https://www.lefigaro.fr/rss/figaro_actualites.xml",
    "Le Figaro - Social": "https://www.lefigaro.fr/rss/figaro_social.xml",
    "Franceinfo": "https://www.francetvinfo.fr/titres.rss",
    "20 Minutes": "https://www.20minutes.fr/feeds/rss-une.xml",
}

THEMES = {
    "Transports": ["sncf", "ratp", "train", "metro", "aerien", "aiguilleur", "controleur", "tgv"],
    "Éducation": ["enseignant", "ecole", "college", "lycee", "universite", "education nationale"],
    "Santé": ["hopital", "soignant", "medecin", "infirmier", "urgences"],
    "Énergie": ["edf", "energie", "raffinerie", "carburant", "electricite"],
    "Fonction publique": ["fonctionnaire", "fonction publique", "service public"],
    "Retraites / Social": ["retraite", "assurance chomage", "salaire", "pouvoir d'achat", "reforme"],
    "Budget": ["budget", "plf", "plfss", "49.3", "austerite"],
}

ACTEURS = {
    "CGT": ["cgt"], "CFDT": ["cfdt"], "FO": ["force ouvriere", " fo "], "SUD": ["sud-rail", "solidaires", "sud "],
    "UNSA": ["unsa"], "CFE-CGC": ["cfe-cgc"], "Gouvernement": ["gouvernement", "premier ministre", "ministre"],
    "Assemblée / Sénat": ["assemblee", "senat", "depute", "senateur"], "Patronat": ["medef", "cpme", "patronat"],
}

TENSION = ["perturbation", "paralys", "bloqu", "annul", "retard", "manifest", "mobilis", "colere", "violence", "affrontement"]
APAISEMENT = ["accord", "negociation", "levee du preavis", "suspend", "fin de la greve", "reprise", "compromis"]


def norm(txt: str) -> str:
    if not txt:
        return ""
    txt = unicodedata.normalize("NFD", txt.lower())
    return "".join(c for c in txt if unicodedata.category(c) != "Mn")


def nettoyer(t: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t or ""))).strip()


def tags(texte: str, dico: dict) -> list:
    t = f" {texte} "
    return [k for k, mots in dico.items() if any(m in t for m in mots)]


def tendance(texte: str) -> str:
    n = norm(texte)
    t, a = sum(n.count(m) for m in TENSION), sum(n.count(m) for m in APAISEMENT)
    return "apaisement" if a > t else ("tension" if t else "neutre")


def telecharger(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _txt(el, nom):
    x = el.find(nom)
    return (x.text or "").strip() if x is not None and x.text else ""


def _date(s):
    if not s:
        return None
    try:
        d = parsedate_to_datetime(s)
    except Exception:
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def lire_flux(url):
    """Lit un flux RSS ou Atom (bibliothèque standard uniquement). Renvoie [] si le flux est indisponible."""
    try:
        racine = ET.fromstring(telecharger(url))
    except Exception:
        return []
    out = []
    for it in racine.iter("item"):
        src = it.find("source")
        out.append({"title": _txt(it, "title"), "link": _txt(it, "link"), "summary": _txt(it, "description"),
                    "date": _date(_txt(it, "pubDate") or _txt(it, "{http://purl.org/dc/elements/1.1/}date")),
                    "source": (src.text or "").strip() if src is not None and src.text else ""})
    atom = "{http://www.w3.org/2005/Atom}"
    for en in racine.iter(atom + "entry"):
        lien = en.find(atom + "link")
        out.append({"title": _txt(en, atom + "title"), "link": lien.get("href", "") if lien is not None else "",
                    "summary": _txt(en, atom + "summary") or _txt(en, atom + "content"),
                    "date": _date(_txt(en, atom + "published") or _txt(en, atom + "updated")), "source": ""})
    return out


def collecter_presse(mots, jours):
    seuil = datetime.now(timezone.utc) - timedelta(days=jours)
    requetes = [(f"Google Actualités : {m}", GOOGLE_NEWS.format(q=urllib.parse.quote(f"{m} when:{jours}d"))) for m in mots]
    requetes += list(FLUX_DIRECTS.items())
    mots_n = [norm(m) for m in mots]
    cles = {w for m in mots_n for w in m.split() if len(w) > 3}
    articles = []
    for nom, url in requetes:
        for e in lire_flux(url):
            d = e["date"]
            if d and d < seuil:
                continue
            titre = nettoyer(e["title"])
            resume = nettoyer(e["summary"])
            texte = norm(f"{titre} {resume}")
            if mots_n and not any(all(w in texte for w in m.split() if len(w) > 3) for m in mots_n):
                continue
            source = e["source"] or nom.split(" - ")[0]
            if nom.startswith("Google") and " - " in titre:  # Google ajoute « - Média » au titre
                titre, source = titre.rsplit(" - ", 1)
            articles.append({
                "date": d.isoformat() if d else "", "source": source.strip(), "titre": titre,
                "resume": resume[:400], "url": e["link"],
                "themes": tags(texte, THEMES), "acteurs": tags(f" {texte} ", ACTEURS),
                "tendance": tendance(f"{titre} {resume}"),
                "score": sum(texte.count(w) for w in cles),
            })
    vus, uniques = set(), []
    for a in sorted(articles, key=lambda x: (x["date"], x["score"]), reverse=True):
        cle = norm(a["titre"])[:80]
        if cle not in vus:
            vus.add(cle)
            uniques.append(a)
    return uniques


# =============================================================================
# RÉSEAUX SOCIAUX (API gratuites)
# =============================================================================
INSTANCES_MASTODON = ["mastodon.social", "piaille.fr", "mamot.fr", "framapiaf.org"]
SUBREDDITS = ["france", "French", "actualite"]


def http(url, headers=None, data=None, timeout=30):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def iso(d):
    return d.astimezone(timezone.utc).isoformat()


def parse_iso(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def post(plateforme, date, texte, url, engagement):
    return {"plateforme": plateforme, "date": date, "texte": texte[:500], "url": url, "engagement": engagement,
            "hashtags": sorted({h.lower() for h in re.findall(r"#(\w+)", texte)}), "tendance": tendance(texte)}


def collecter_mastodon(hashtags, seuil):
    out = []
    for inst in INSTANCES_MASTODON:
        for tag in hashtags:
            try:
                for s in http(f"https://{inst}/api/v1/timelines/tag/{urllib.parse.quote(norm(tag))}?limit=40"):
                    d = parse_iso(s["created_at"])
                    if d < seuil or s.get("language") not in (None, "fr"):
                        continue
                    eng = s["reblogs_count"] + s["favourites_count"] + s["replies_count"]
                    out.append(post("Mastodon", iso(d), nettoyer(s["content"]), s["url"], eng))
            except Exception:
                continue
    return out


def collecter_reddit(mots, seuil, jours):
    cid, sec = os.environ.get("REDDIT_CLIENT_ID"), os.environ.get("REDDIT_CLIENT_SECRET")
    base, hdr = "https://www.reddit.com", {}
    try:
        if cid and sec:
            auth = base64.b64encode(f"{cid}:{sec}".encode()).decode()
            tok = http("https://www.reddit.com/api/v1/access_token", {"Authorization": f"Basic {auth}"},
                       b"grant_type=client_credentials")["access_token"]
            base, hdr = "https://oauth.reddit.com", {"Authorization": f"Bearer {tok}"}
    except Exception:
        pass
    periode = "day" if jours <= 1 else "week" if jours <= 7 else "month"
    out = []
    for sub in SUBREDDITS:
        for m in mots:
            try:
                q = urllib.parse.urlencode({"q": m, "restrict_sr": 1, "sort": "new", "t": periode, "limit": 100})
                for c in http(f"{base}/r/{sub}/search.json?{q}", hdr)["data"]["children"]:
                    p = c["data"]
                    d = datetime.fromtimestamp(p["created_utc"], timezone.utc)
                    if d >= seuil:
                        out.append(post("Reddit", iso(d), f'{p["title"]}. {p.get("selftext", "")}',
                                        "https://www.reddit.com" + p["permalink"], p["score"] + p["num_comments"]))
            except Exception:
                continue
    return out


def collecter_bluesky(mots, seuil):
    h, pw = os.environ.get("BSKY_HANDLE"), os.environ.get("BSKY_APP_PASSWORD")
    if not (h and pw):
        return []
    out = []
    try:
        jwt = http("https://bsky.social/xrpc/com.atproto.server.createSession", {"Content-Type": "application/json"},
                   json.dumps({"identifier": h, "password": pw}).encode())["accessJwt"]
        for m in mots:
            q = urllib.parse.urlencode({"q": m, "lang": "fr", "sort": "latest", "limit": 100, "since": iso(seuil)})
            for p in http(f"https://bsky.social/xrpc/app.bsky.feed.searchPosts?{q}",
                          {"Authorization": f"Bearer {jwt}"}).get("posts", []):
                rec = p["record"]
                d = parse_iso(rec["createdAt"])
                if d >= seuil:
                    url = f'https://bsky.app/profile/{p["author"]["handle"]}/post/{p["uri"].split("/")[-1]}'
                    eng = p.get("likeCount", 0) + p.get("repostCount", 0) + p.get("replyCount", 0)
                    out.append(post("Bluesky", iso(d), rec.get("text", ""), url, eng))
    except Exception:
        pass
    return out


def collecter_youtube(mots, seuil):
    cle = os.environ.get("YOUTUBE_API_KEY")
    if not cle:
        return []
    out = []
    for m in mots:
        try:
            q = urllib.parse.urlencode({"part": "snippet", "q": m, "type": "video", "regionCode": "FR",
                                        "relevanceLanguage": "fr", "order": "date", "maxResults": 50,
                                        "publishedAfter": iso(seuil), "key": cle})
            items = http(f"https://www.googleapis.com/youtube/v3/search?{q}").get("items", [])
            ids = ",".join(i["id"]["videoId"] for i in items)
            if not ids:
                continue
            stats = {v["id"]: v["statistics"] for v in http(
                "https://www.googleapis.com/youtube/v3/videos?" +
                urllib.parse.urlencode({"part": "statistics", "id": ids, "key": cle}))["items"]}
            for i in items:
                st_, sn = stats.get(i["id"]["videoId"], {}), i["snippet"]
                eng = int(st_.get("likeCount", 0)) + int(st_.get("commentCount", 0))
                out.append(post("YouTube", sn["publishedAt"], f'{nettoyer(sn["title"])}. {nettoyer(sn["description"])}',
                                f'https://www.youtube.com/watch?v={i["id"]["videoId"]}', eng))
        except Exception:
            continue
    return out


# =============================================================================
# NOTE DE SYNTHÈSE (Claude, optionnel)
# =============================================================================
def synthese_claude(articles):
    cle = os.environ.get("ANTHROPIC_API_KEY=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")
    if not cle:
        return ""
    corpus = "\n".join(f"- [{a['date'][:16]}] {a['source']} : {a['titre']} — {a['resume'][:200]}" for a in articles[:60])
    consigne = (
        "Tu es analyste en affaires publiques. À partir de ces titres de presse française, rédige en français "
        "une note de veille : 1) état de la situation, 2) acteurs et positions, "
        "3) signaux annonçant un arbitrage ou une négociation, 4) points de vigilance. "
        "Appuie-toi uniquement sur le corpus et signale les incertitudes.\n\n" + corpus
    )
    try:
        res = http("https://api.anthropic.com/v1/messages",
                   {"x-api-key": cle, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                   json.dumps({"model": MODEL, "max_tokens": 2000,
                               "messages": [{"role": "user", "content": consigne}]}).encode(), timeout=120)
        return "".join(b.get("text", "") for b in res.get("content", []))
    except Exception as e:
        return f"Erreur lors de la génération de la note : {e}"


# =============================================================================
# DONNÉES
# =============================================================================
def to_df(rows, listes, defauts):
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    for c, v in defauts.items():
        if c not in df:
            df[c] = v
    df["date"] = pd.to_datetime(df["date"], utc=True, errors="coerce")
    for c in listes:
        if c not in df:
            df[c] = [[] for _ in range(len(df))]
        df[c + "_txt"] = df[c].apply(lambda v: ", ".join(v) if isinstance(v, list) else "")
    return df


# --- Barre latérale ------------------------------------------------------------
st.sidebar.title("Paramètres")
mots = tuple(m.strip() for m in st.sidebar.text_area("Mots-clés (un par ligne)", "grève").splitlines() if m.strip())
jours = st.sidebar.slider("Période (jours)", 1, 14, 3)
sources = st.sidebar.multiselect("Réseaux sociaux", ["Mastodon", "Reddit", "Bluesky", "YouTube"], default=["Mastodon"])
st.sidebar.caption("Les clés API se configurent dans les secrets Streamlit. Une source sans clé est ignorée.")
st.sidebar.divider()
fa = st.sidebar.file_uploader("…ou charger articles.json", type="json")
fs = st.sidebar.file_uploader("…ou charger social.json", type="json")
st.sidebar.divider()
live = st.sidebar.toggle("Temps réel (actualisation automatique)", value=False)
interval = st.sidebar.slider("Fréquence (minutes)", 2, 30, 5, disabled=not live)
seuil_alerte = st.sidebar.slider("Alerte si tension ≥ (%)", 30, 100, 60)
if st.sidebar.button("Actualiser maintenant"):
    st.cache_data.clear()

TTL = max(60, interval * 60 - 5) if live else 900


@st.cache_data(ttl=TTL, show_spinner="Collecte de la presse…")
def get_presse(mots: tuple, jours: int):
    return collecter_presse(list(mots), jours)


@st.cache_data(ttl=TTL, show_spinner="Collecte des réseaux sociaux…")
def get_social_libre(mots: tuple, jours: int, sources: tuple):
    seuil = datetime.now(timezone.utc) - timedelta(days=jours)
    hashtags = [norm(m).replace(" ", "") for m in mots]
    posts = []
    if "Mastodon" in sources:
        posts += collecter_mastodon(hashtags, seuil)
    if "Reddit" in sources:
        posts += collecter_reddit(list(mots), seuil, jours)
    if "Bluesky" in sources:
        posts += collecter_bluesky(list(mots), seuil)
    return posts


@st.cache_data(ttl=max(TTL, 1800), show_spinner=False)  # la recherche YouTube coûte 100 unités de quota
def get_youtube(mots: tuple, jours: int):
    return collecter_youtube(list(mots), datetime.now(timezone.utc) - timedelta(days=jours))


def get_social(mots, jours, sources):
    posts = get_social_libre(mots, jours, sources)
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
    # --- Chargement ---
    if fa:
        arts = json.loads(fa.getvalue()).get("articles", [])
    elif mots:
        arts = get_presse(mots, jours)
    else:
        st.warning("Saisissez au moins un mot-clé.")
        return
    if fs:
        posts = json.loads(fs.getvalue()).get("posts", [])
    elif sources and mots:
        posts = get_social(mots, jours, tuple(sources))
    else:
        posts = []

    dfA = to_df(arts, ["themes", "acteurs"], {"resume": "", "source": "", "titre": "", "tendance": "neutre", "url": ""})
    dfS = to_df(posts, ["hashtags"], {"texte": "", "plateforme": "", "engagement": 0, "tendance": "neutre", "url": ""})

    # --- Nouveautés ---
    urls = {a.get("url", "") for a in arts} | {p.get("url", "") for p in posts}
    deja = st.session_state.get("vus", set())
    nouveaux = (urls - deja) if deja else set()
    st.session_state["vus"] = deja | urls
    if live and nouveaux:
        st.toast(f"{len(nouveaux)} nouveau(x) contenu(x)", icon="🔔")
    st.caption(f"Dernière actualisation : {datetime.now().strftime('%H:%M:%S')}"
               + (f" · prochaine dans {interval} min" if live else " · mode manuel"))

    # --- Filtres ---
    c1, c2, c3 = st.columns([2, 2, 3])
    themes = sorted({t for l in dfA["themes"] for t in l}) if not dfA.empty else []
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
            dfS = dfS[dfS["tendance"].isin(td)]
        if q:
            dfS = dfS[dfS["texte"].str.lower().str.contains(q, regex=False)]
        if th:  # les thèmes ne s'appliquent qu'à la presse
            dfS = dfS.iloc[0:0]

    # --- Indicateurs ---
    tout = pd.concat([dfA["tendance"] if not dfA.empty else pd.Series(dtype=str),
                      dfS["tendance"] if not dfS.empty else pd.Series(dtype=str)])
    k = st.columns(5)
    k[0].metric("Articles", len(dfA))
    k[1].metric("Médias", dfA["source"].nunique() if not dfA.empty else 0)
    k[2].metric("Publications sociales", len(dfS))
    part_tension = 100 * (tout == "tension").mean() if len(tout) else 0
    k[3].metric("En tension", f"{round(part_tension)} %" if len(tout) else "–")
    k[4].metric("Engagement social", f"{int(dfS['engagement'].sum()):,}".replace(",", " ") if not dfS.empty else 0)

    if len(tout) and part_tension >= seuil_alerte:
        st.warning(f"Alerte : {round(part_tension)} % des contenus sont en tension (seuil {seuil_alerte} %).")
    if nouveaux:
        st.info(f"{len(nouveaux)} nouveau(x) contenu(x) depuis la dernière actualisation.")

    if dfA.empty and dfS.empty:
        st.info("Aucune donnée disponible. Vérifiez vos mots-clés ou votre connexion, ou chargez des fichiers JSON.")
        return

    t1, t2, t3, t4 = st.tabs(["Vue d’ensemble", "Presse", "Réseaux sociaux", "Note de synthèse (Claude)"])

    with t1:
        a, b = st.columns(2)
        jour = pd.concat([
            dfA[["date"]].assign(type="Presse") if not dfA.empty else pd.DataFrame(columns=["date", "type"]),
            dfS[["date"]].assign(type="Réseaux") if not dfS.empty else pd.DataFrame(columns=["date", "type"]),
        ])
        jour = jour.dropna(subset=["date"])
        if not jour.empty:
            jour["jour"] = pd.to_datetime(jour["date"], utc=True).dt.strftime("%Y-%m-%d")
            a.subheader("Volume par jour")
            a.bar_chart(jour.groupby(["jour", "type"]).size().unstack(fill_value=0))
        b.subheader("Tendances")
        b.bar_chart(tout.value_counts())
        c, d = st.columns(2)
        if not dfA.empty:
            c.subheader("Thèmes (presse)")
            c.bar_chart(dfA.explode("themes")["themes"].dropna().value_counts().head(10))
            d.subheader("Acteurs cités (presse)")
            d.bar_chart(dfA.explode("acteurs")["acteurs"].dropna().value_counts().head(10))
        if not dfS.empty and "hashtags" in dfS:
            st.subheader("Hashtags dominants")
            h = dfS.explode("hashtags")["hashtags"].dropna().value_counts().head(20)
            st.write("  ".join(f"`#{t}` {n}" for t, n in h.items()) or "Aucun hashtag")

    with t2:
        if dfA.empty:
            st.info("Aucun article.")
        else:
            v = dfA.sort_values("date", ascending=False)[["date", "source", "titre", "themes_txt", "acteurs_txt", "tendance", "url"]]
            st.dataframe(v, hide_index=True, column_config={
                "url": st.column_config.LinkColumn("Lien", display_text="ouvrir"),
                "themes_txt": "Thèmes", "acteurs_txt": "Acteurs"})
            st.download_button("Télécharger en CSV", v.to_csv(index=False, sep=";").encode("utf-8-sig"), "articles.csv")

    with t3:
        if dfS.empty:
            st.info("Aucune publication (sources sans clé ignorées, ou aucun résultat).")
        else:
            v = dfS.sort_values("engagement", ascending=False)[["date", "plateforme", "texte", "engagement", "tendance", "url"]]
            st.dataframe(v, hide_index=True,
                         column_config={"url": st.column_config.LinkColumn("Lien", display_text="ouvrir")})
            st.download_button("Télécharger en CSV", v.to_csv(index=False, sep=";").encode("utf-8-sig"), "social.csv")

    with t4:
        st.write("Claude rédige une note d’analyse à partir des articles actuellement filtrés. "
                 "Nécessite `ANTHROPIC_API_KEY` ; l’API est facturée à l’usage.")
        if st.button("Générer la note"):
            if not os.environ.get("ANTHROPIC_API_KEY"):
                st.error("ANTHROPIC_API_KEY absente des secrets.")
            elif dfA.empty:
                st.warning("Aucun article à analyser.")
            else:
                with st.spinner("Analyse en cours…"):
                    rows = dfA.assign(date=dfA["date"].astype(str)).to_dict("records")
                    st.session_state["note"] = synthese_claude(rows)
        if st.session_state.get("note"):
            st.markdown(st.session_state["note"])
            st.download_button("Télécharger la note", st.session_state["note"], "synthese.md")


dashboard()
