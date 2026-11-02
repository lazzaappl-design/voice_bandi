#!/usr/bin/env python3
"""
Voice Bandi Monitor — raccolta settimanale di bandi/avvisi dalle fonti in sources.csv.

Cosa fa:
  1. legge l'elenco delle fonti (sources.csv);
  2. scarica ogni pagina (e, dove indicato, le pagine successive);
  3. estrae i link che sembrano bandi/avvisi e le date che trova vicino;
  4. confronta con la settimana precedente (state/state.json);
  5. scrive un report in italiano (output/report_AAAA-MM-GG.md + output/ultimo_report.md).

Non usa password né account: legge solo pagine pubbliche.
Uso:  python monitor.py            (tutte le fonti)
      python monitor.py --solo 3,8 (solo le fonti con id 3 e 8: utile per provare)
"""
import argparse, csv, datetime as dt, hashlib, json, os, re, sys, time
from urllib.parse import urljoin, urldefrag, urlparse

import requests
from bs4 import BeautifulSoup

BASE = os.path.dirname(os.path.abspath(__file__))
UA = "Mozilla/5.0 (compatible; VoiceBandiMonitor/1.0; uso interno monitoraggio bandi)"
PAUSA = 1.5          # secondi di pausa tra una richiesta e l'altra (cortesia verso i siti)
TIMEOUT = 45

# Parole-chiave tematiche (peso 2) e parole che indicano un bando (peso 1)
TEMI = ["anzian", "welfare", "fragilit", "longevit", "caregiver", "solitudin", "invecchiament",
        "innovazione sociale", "prossimit", "volontariat", "comunit", "partecipazione",
        "capacity", "aree interne", "non autosufficien", "senior", "ageing", "elderly",
        "community", "loneliness", "terzo settore", "inclusione", "cohousing",
        # bandi generalisti che includono anche gli anziani
        "sociale", "socio-sanitar", "domiciliar", "generazion", "isolamento", "benessere",
        "coesione", "povert", "famigli", "disabil", "persone fragili", "enti del terzo settore", "ets"]
BANDO = ["bando", "avviso", "call", "contribut", "scadenz", "candidatur", "finanziament",
         "richiest", "invito", "manifestazione di interesse", "selezione", "premio",
         "8xmille", "8x1000", "otto per mille", "progetti"]
SCARTA_HREF = ("mailto:", "tel:", "javascript:", "#")
SCARTA_URL = ("/tag/", "/taxonomy/", "/author/", "/category/", "/settore/", "/pagina/", "/page/", "/feed", "wp-json", "/search")
SCARTA_TESTO = ("esiti", "graduatori", "vincitor", "risultati", "podcast", "newsletter", "iscriviti", "rendicontazione")
SCARTA_DOMINI = ("facebook.com", "twitter.com", "x.com", "instagram.com", "linkedin.com",
                 "youtube.com", "wa.me", "t.me", "whatsapp.com")

MESI = {"gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4, "maggio": 5, "giugno": 6,
        "luglio": 7, "agosto": 8, "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12}
RE_NUM = re.compile(r"\b(\d{1,2})[/.\-](\d{1,2})[/.\-](20\d{2}|\d{2})\b")
RE_TXT = re.compile(r"\b(\d{1,2})\s+(" + "|".join(MESI) + r")\s+(20\d{2})\b", re.I)


def oggi():
    return dt.date.today()


def trova_date(testo):
    """Restituisce le date (ISO) trovate nel testo, con anno 2024-2030."""
    out = set()
    for g, m, a in RE_NUM.findall(testo):
        a = int(a) + (2000 if int(a) < 100 else 0)
        try:
            out.add(dt.date(a, int(m), int(g)))
        except ValueError:
            pass
    for g, mese, a in RE_TXT.findall(testo):
        try:
            out.add(dt.date(int(a), MESI[mese.lower()], int(g)))
        except ValueError:
            pass
    return sorted(d for d in out if 2024 <= d.year <= 2030)


def punteggio(testo):
    t = testo.lower()
    return 2 * sum(1 for k in TEMI if k in t) + sum(1 for k in BANDO if k in t)


def scarica(url):
    """Ritorna (codice_http, html, errore)."""
    ultimo = None
    for tentativo in range(3):
        try:
            r = requests.get(url, headers={"User-Agent": UA, "Accept-Language": "it-IT,it;q=0.9"},
                             timeout=TIMEOUT)
            if r.status_code == 200:
                r.encoding = r.apparent_encoding if not r.encoding or r.encoding.lower() == "iso-8859-1" else r.encoding
                return r.status_code, r.text, None
            ultimo = f"HTTP {r.status_code}"
            if r.status_code in (403, 404, 410):
                return r.status_code, "", ultimo
        except requests.RequestException as e:
            ultimo = type(e).__name__
        time.sleep(4 * (tentativo + 1))
    return 0, "", ultimo


def analizza(url, html):
    """Estrae testo pulito e link candidati da una pagina."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "nav", "footer", "header", "form"]):
        tag.decompose()
    testo = re.sub(r"\s+", " ", soup.get_text(" ")).strip()
    link = {}
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.lower().startswith(SCARTA_HREF):
            continue
        assoluto, _ = urldefrag(urljoin(url, href))
        if any(d in urlparse(assoluto).netloc for d in SCARTA_DOMINI):
            continue
        if any(x in assoluto.lower() for x in SCARTA_URL):
            continue
        m_anno = re.search(r"/uploads/(20\d\d)/", assoluto)
        if m_anno and int(m_anno.group(1)) < oggi().year:
            continue
        if any(x in (assoluto + " " + a.get_text(" ")).lower() for x in SCARTA_TESTO):
            continue
        etichetta = re.sub(r"\s+", " ", a.get_text(" ")).strip()
        contesto = ""
        genitore = a.find_parent(["li", "article", "div", "tr", "p"])
        if genitore is not None:
            contesto = re.sub(r"\s+", " ", genitore.get_text(" ")).strip()[:400]
        base = f"{etichetta} {assoluto} {contesto}"
        if len(etichetta) < 12 and not assoluto.lower().endswith(".pdf"):
            continue
        sc = punteggio(base)
        if sc == 0:
            continue
        date = trova_date(etichetta + " " + contesto)
        if assoluto not in link or sc > link[assoluto]["punteggio"]:
            link[assoluto] = {"testo": etichetta[:200] or assoluto, "punteggio": sc,
                              "date": [d.isoformat() for d in date], "contesto": contesto[:300]}
    return testo, link


def leggi_fonti(path, solo):
    with open(path, newline="", encoding="utf-8") as f:
        righe = list(csv.DictReader(f))
    if solo:
        ids = set(solo.split(","))
        righe = [r for r in righe if r["id"] in ids]
    return righe


def carica_stato(path):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fonti", default=os.path.join(BASE, "sources.csv"))
    ap.add_argument("--stato", default=os.path.join(BASE, "state", "state.json"))
    ap.add_argument("--out", default=os.path.join(BASE, "output"))
    ap.add_argument("--solo", default="")
    a = ap.parse_args()

    os.makedirs(os.path.dirname(a.stato), exist_ok=True)
    os.makedirs(a.out, exist_ok=True)
    fonti = leggi_fonti(a.fonti, a.solo)
    stato = carica_stato(a.stato)
    adesso = oggi()

    nuovi, modificate, problemi, censimento = [], [], [], []
    for i, f in enumerate(fonti, 1):
        sid, nome, url = f["id"], f["nome"], f["url"]
        print(f"[{i}/{len(fonti)}] {nome} ...", flush=True)
        pagine = [url]
        try:
            mp = int(f.get("max_pagine") or 1)
        except ValueError:
            mp = 1
        pat = (f.get("pattern_pagina") or "").strip()
        for n in range(2, mp + 1):
            if pat:
                pagine.append(url.rstrip("/") + "/" + pat.format(n=n))

        precedente = stato.get(sid, {})
        primo_giro = not precedente.get("ultimo_ok")
        testi, tutti, esiti = [], {}, []
        for p in pagine:
            codice, html, err = scarica(p)
            esiti.append((p, codice, err))
            if codice == 200:
                t, l = analizza(p, html)
                testi.append(t)
                tutti.update(l)
            time.sleep(PAUSA)

        ok = any(c == 200 for _, c, _ in esiti)
        rec = {"nome": nome, "url": url, "categoria": f["categoria"]}
        if not ok:
            fall = precedente.get("fallimenti", 0) + 1
            stato[sid] = {**precedente, **rec, "fallimenti": fall}
            problemi.append((f, f"non raggiungibile ({esiti[0][2]}) — fallimenti consecutivi: {fall}"))
            continue

        testo = " ".join(testi)
        h = hashlib.sha1(testo.encode("utf-8")).hexdigest()
        if len(testo) < 800 and not tutti:
            problemi.append((f, "pagina quasi vuota: contenuto probabilmente caricato via JavaScript "
                                "(questa fonte va controllata a mano o con uno strumento diverso)"))
        vecchi = precedente.get("link", {})
        for u, d in tutti.items():
            if u not in vecchi:
                voce = {**d, "url": u, "fonte": nome, "categoria": f["categoria"], "id": sid}
                (censimento if primo_giro else nuovi).append(voce)
                d["prima_vista"] = adesso.isoformat()
            else:
                d["prima_vista"] = vecchi[u].get("prima_vista", adesso.isoformat())
        if not primo_giro and precedente.get("hash") and precedente["hash"] != h:
            modificate.append(f)
        stato[sid] = {**rec, "hash": h, "link": tutti, "ultimo_ok": adesso.isoformat(), "fallimenti": 0}

    with open(a.stato, "w", encoding="utf-8") as fh:
        json.dump(stato, fh, ensure_ascii=False, indent=1)

    def scaduto(v):
        return bool(v["date"]) and max(dt.date.fromisoformat(x) for x in v["date"]) < adesso

    def futura(v):
        return any(dt.date.fromisoformat(x) >= adesso for x in v["date"])

    def ordina(lst):
        return sorted(lst, key=lambda v: (not futura(v), -v["punteggio"]))

    nuovi = [v for v in nuovi if not scaduto(v)]
    censimento = [v for v in censimento if not scaduto(v)]
    righe = [f"# Report bandi Voice — {adesso.strftime('%d/%m/%Y')}", ""]
    righe += [f"Fonti lette: {len(fonti) - len(problemi)} su {len(fonti)} · "
              f"nuovi link candidati: {len(nuovi)} · pagine modificate: {len(modificate)} · "
              f"fonti con problemi: {len(problemi)}", ""]
    righe += ["> Questi sono **candidati automatici**: vanno verificati sulla fonte primaria prima di entrare "
              "in dashboard. Il programma non valuta l'eleggibilità di Voice.", ""]

    def sezione(titolo, lista, limite=None):
        righe.append(f"## {titolo}")
        righe.append("")
        if not lista:
            righe.append("_Nessuno._")
            righe.append("")
            return
        for v in (ordina(lista)[:limite] if limite else ordina(lista)):
            d = ", ".join(dt.date.fromisoformat(x).strftime("%d/%m/%Y") for x in v["date"]) or "—"
            mark = "⏰ " if futura(v) else ""
            righe.append(f"- {mark}**{v['testo']}** — {v['fonte']} ({v['categoria']}) · date: {d} · "
                         f"punteggio {v['punteggio']}  \n  {v['url']}")
        righe.append("")

    sezione("Nuovi candidati questa settimana", nuovi)
    righe.append("## Pagine già note ma modificate")
    righe.append("")
    righe += [f"- {f['nome']} — {f['url']}" for f in modificate] or ["_Nessuna._"]
    righe.append("")
    righe.append("## Fonti con problemi (da sistemare)")
    righe.append("")
    righe += [f"- **{f['nome']}** (id {f['id']}): {m}  \n  {f['url']}" for f, m in problemi] or ["_Nessuna._"]
    righe.append("")
    if censimento:
        sezione("Censimento iniziale (prima lettura delle fonti nuove — primi 60 per rilevanza)", censimento, 60)

    testo_rep = "\n".join(righe)
    for nome_f in (f"report_{adesso.isoformat()}.md", "ultimo_report.md"):
        with open(os.path.join(a.out, nome_f), "w", encoding="utf-8") as fh:
            fh.write(testo_rep)
    with open(os.path.join(a.out, f"candidati_{adesso.isoformat()}.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["tipo", "fonte", "categoria", "titolo", "url", "date", "punteggio"])
        for tipo, lst in (("nuovo", nuovi), ("censimento", censimento)):
            for v in ordina(lst):
                w.writerow([tipo, v["fonte"], v["categoria"], v["testo"], v["url"],
                            ";".join(v["date"]), v["punteggio"]])
    print(f"\nFatto. Report: {os.path.join(a.out, 'ultimo_report.md')}")


if __name__ == "__main__":
    sys.exit(main())
