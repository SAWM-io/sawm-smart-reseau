#!/usr/bin/env python3
"""Build the combined measured report (optional dependency: reportlab)."""
import argparse
import json
import math
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor, black, white
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph, Table, TableStyle

W, H = A4
M = 44
POLICIES = ["fifo", "deadline_first", "ewma", "odvl", "ewma_odvl"]
LABELS = ["FIFO", "Échéance", "EWMA", "ODVL", "EWMA + ODVL"]
COLORS = [HexColor(x) for x in ("#c4c4c4", "#888888", "#535353", "#bbbbbb", "#161616")]
SCENARIOS = {"stable": "Charge régulière", "burst": "Arrivées en rafales", "slow_service": "Service ralenti"}


def read(path):
    return json.loads(path.read_text())


def build(source, destination):
    network = read(source / "network-benchmark.json")
    delivery = read(source / "delivery-benchmark/report.json")
    clouds = [read(source / part / "cloud-report.json") for part in (
        "network-cloud", "delivery-cloud", "network-results-cloud", "delivery-results-cloud")]
    destination.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(destination), pagesize=A4)
    c.setTitle("SAWM & Basira | Réseau intelligent et résilience applicative")
    c.setAuthor("SAWM - laboratoire de validation")
    body = ParagraphStyle("Body", fontName="Helvetica", fontSize=10, leading=15, textColor=HexColor("#333333"))
    small = ParagraphStyle("Small", parent=body, fontSize=8, leading=11)
    page = 0

    def para(text, y, style=body, x=M, width=W-2*M):
        p = Paragraph(text, style)
        _, height = p.wrap(width, H)
        if y-height < 45:
            raise ValueError("paragraph_outside_page")
        p.drawOn(c, x, y-height)
        return y-height-12

    def title(kicker, heading):
        nonlocal page
        page += 1
        c.setFillColor(black)
        c.setFont("Helvetica", 9)
        c.drawString(M, H-42, "S A W M   /   B A S I R A")
        c.setFont("Helvetica", 8)
        c.setFillColor(HexColor("#777777"))
        c.drawRightString(W-M, H-42, "LABORATOIRE CIVIL  /  27.10.2026")
        c.setStrokeColor(HexColor("#dddddd")); c.line(M, H-56, W-M, H-56)
        c.setFont("Helvetica", 9); c.drawString(M, H-84, kicker.upper())
        c.setFillColor(black); c.setFont("Helvetica-Bold", 24)
        c.drawString(M, H-118, heading)

    def finish():
        c.setFillColor(HexColor("#777777")); c.setFont("Helvetica", 8)
        c.drawString(M, 24, "API publiques Basira / TSST / ODVL / SAWM  |  Mesures locales reproductibles")
        c.drawRightString(W-M, 24, str(page))
        c.showPage()

    def table(rows, widths, y):
        formatted = [[Paragraph(escape(str(cell)), small) for cell in row] for row in rows]
        t = Table(formatted, colWidths=widths, hAlign="LEFT")
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), HexColor("#eeeeee")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LINEBELOW", (0, 0), (-1, 0), .7, black),
            ("LINEBELOW", (0, 1), (-1, -1), .35, HexColor("#dddddd")),
            ("LEFTPADDING", (0,0), (-1,-1), 8), ("RIGHTPADDING", (0,0), (-1,-1), 8),
            ("TOPPADDING", (0,0), (-1,-1), 9), ("BOTTOMPADDING", (0,0), (-1,-1), 9),
        ]))
        _, height = t.wrap(W-2*M, H)
        if y-height < 45: raise ValueError("table_outside_page")
        t.drawOn(c, M, y-height)
        return y-height-20

    delivered = delivery["comparison"]["durable"]["delivered_unique"]
    planned = delivery["planned_messages_per_channel"]
    receipts = sum(r["unique_receipts"] for r in network["trials"])
    errors = sum(r["errors"] for r in network["trials"])
    title("Deux programmes actifs", "Réseau intelligent")
    y = para("<b>et résilience applicative avec SAWM &amp; Basira</b>", H-142)
    y = para("Envoyer, conserver et reprendre des messages après une interruption ; comparer un ordonnancement par moyenne glissante avec un classement ODVL. Deux programmes autonomes, reliés aux véritables API Cloud et livrés avec leur code.", y-4)
    for x, number, caption in ((M, f"{delivered}/{planned}", "Messages repris et livrés"),
                               (M+180, str(receipts), "Réceptions HTTP vérifiées"),
                               (M+360, str(errors), "Erreur de livraison du banc")):
        c.setFillColor(black); c.setFont("Helvetica-Bold", 32); c.drawString(x, y-43, number)
        c.setFont("Helvetica", 8); c.drawString(x, y-63, caption)
    y -= 104
    y = para("<b>Résilience applicative.</b> Une file SQLite survit au redémarrage de l'émetteur. Les accusés de réception lient l'identifiant au contenu ; une nouvelle tentative ne produit pas un second effet.", y)
    y = para("<b>Réseau intelligent.</b> Une file de messages HTTP utilise une moyenne glissante exponentielle (EWMA), l'ordre ODVL ou leur combinaison. Le benchmark conserve cinq politiques et trois scénarios, sans changer la concurrence.", y)
    y = para("<b>Conclusion mesurée.</b> La reprise fonctionne sur le scénario essayé. En revanche, EWMA + ODVL ne domine pas les méthodes simples sur ces charges : le raccordement fonctionne, son avantage de performance n'est pas démontré.", y)
    y = para("<b>Portée.</b> Échanges TCP/HTTP réels sur localhost, charges synthétiques sur un Mac ARM64. Aucun essai de radio, de GNSS, de localisation de brouilleur ou de résistance au brouillage physique. Le premier programme constitue une alternative civile de continuité applicative.", y, small)
    finish()

    title("Architecture vérifiée", "Le Cloud, puis l'exécution locale")
    y = para("Les entités ont été créées dans l'espace client Basira depuis Chrome. Le principal existant a reçu, après autorisation, lecture et écriture sur les deux nouvelles entités ; aucun droit d'administration ou de purge n'a été ajouté.", H-144)
    rows = [["Étape", "Rôle effectif", "Vérification"],
            ["1. Basira", "Conserver les mesures de calibration puis le bilan.", "Dépôt accepté, traitement terminé."],
            ["2. TSST", "Retrouver le résumé du même essai dans la même entité.", "Correspondance littérale et intégrité des preuves."],
            ["3. ODVL", "Classer les candidats fournis avant le banc.", "Permutation exacte, aucun candidat ajouté ou perdu."],
            ["4. SAWM", "Proposer une politique JSON bornée ; commenter le bilan.", "Tour terminé, paramètres validés localement."],
            ["5. Programme", "Exécuter la politique, mesurer et vérifier les réceptions.", "Identifiants, empreintes et compteurs locaux."]]
    y = table(rows, [76, 234, W-2*M-310], y-5)
    total = sum(len(r["calls"]) for r in clouds)
    y = para(f"<b>{total} opérations Cloud suivies</b>, toutes terminées lors de cette campagne. Ce nombre désigne les opérations du client (l'attente d'un traitement peut effectuer plusieurs requêtes HTTP), pas un compteur brut de requêtes réseau.", y)
    y = para("La mémoire rappelée a réellement alimenté la demande à SAWM. SAWM a retenu alpha = 0,35 pour l'EWMA et la politique de reprise proposée. Le choix identique à l'exemple fourni ne démontre pas une optimisation apprise.", y)
    para("Les appels Cloud sont placés avant et après les essais. La boucle locale n'attend pas le LLM pour chaque message. Un fichier de politique valide et un ordre ODVL déjà reçu peuvent être réutilisés hors ligne. Cette séparation protège le débit applicatif, sans prouver un réseau autonome universel.", y)
    finish()

    title("Programme 1", "Reprendre sans perdre les messages")
    y = para(f"Même ensemble de {planned} messages, même destinataire HTTP et même coupure de {delivery['outage_measured_seconds']:.3f} s. L'émetteur durable est arrêté puis relancé pendant l'indisponibilité. Un accusé de réception est volontairement perdu après l'écriture côté destinataire.", H-144)
    chart_y = y-130
    for i, (key, label) in enumerate((("volatile", "Envoi simple"), ("durable", "File durable"))):
        amount = delivery["comparison"][key]["delivered_unique"]
        by = chart_y+70-i*58
        c.setFillColor(black); c.setFont("Helvetica", 11); c.drawString(M, by+8, label)
        c.setFillColor(HexColor("#dddddd")); c.rect(M+110, by, 310, 25, fill=1, stroke=0)
        c.setFillColor(black if key == "durable" else HexColor("#888888"))
        c.rect(M+110, by, 310*amount/planned, 25, fill=1, stroke=0)
        c.setFont("Helvetica-Bold", 12); c.drawString(M+434, by+7, f"{amount}/{planned}")
    y = chart_y-18
    rows = [["Contrôle", "Résultat"],
            ["Réceptions uniques / ACK vérifiés", f"{delivered} / {delivery['comparison']['durable']['sender_acknowledged']}"],
            ["Messages perdus en fin d'essai", str(delivery['comparison']['durable']['lost_at_end'])],
            ["Requêtes répétées / effets en double", f"{delivery['comparison']['durable']['duplicate_requests']} / {delivery['comparison']['durable']['duplicate_effects']}"],
            ["Redémarrage du processus émetteur", "Effectué et vérifié"],
            ["Durée totale du scénario", f"{delivery['elapsed_seconds']:.3f} s"]]
    y = table(rows, [315, W-2*M-315], y)
    y = para("<b>Ce qui produit la reprise :</b> journal SQLite persistant, nouvelles tentatives bornées, vérification de l'accusé de réception et idempotence au destinataire. Le même mécanisme local avait déjà livré 20/20 messages sans Cloud lors de la calibration.", y)
    para("Basira et TSST ajoutent ici conservation et rappel des résultats ; SAWM fournit une politique contrôlée ; ODVL classe des options. Aucun gain causal de livraison supplémentaire dû au Cloud n'est établi par ce test. La liaison n'est pas restée connectée pendant la coupure : les messages ont été conservés puis livrés après son retour.", y, small)
    finish()

    title("Programme 2 - latence", "Comparer, sans présumer du résultat")
    para("P95 de latence de bout en bout, en millisecondes : médiane des trois répétitions. Plus bas est préférable. Chaque essai traite 24 messages avec au maximum quatre requêtes simultanées.", H-144)
    lookup = {(r['scenario'], r['policy']): r for r in network['summary']}
    for j, (scenario, label) in enumerate(SCENARIOS.items()):
        top = 610-j*172
        c.setFont("Helvetica-Bold", 12); c.setFillColor(black); c.drawString(M, top, label)
        values = [lookup[scenario, p]['p95_ms_median'] for p in POLICIES]
        maximum = max(values)*1.15
        for i, (name, value) in enumerate(zip(LABELS, values)):
            yy = top-27-i*23
            c.setFillColor(black); c.setFont("Helvetica", 9); c.drawString(M, yy+4, name)
            c.setFillColor(COLORS[i]); c.rect(M+100, yy, 338*value/maximum, 14, fill=1, stroke=0)
            c.setFillColor(black); c.drawString(M+108+338*value/maximum, yy+3, f"{value:.1f}")
    para("Une latence plus basse peut masquer davantage de messages hors délai. Le tableau suivant donne ce second critère. Ces mesures dépendent de l'ordonnanceur du Mac et de charges déterministes ; trois répétitions ne fondent pas une généralisation statistique.", 98, small)
    finish()

    title("Arbitrage", "Débit, délais et limites")
    y = para("Messages hors délai sur 72 messages par scénario et politique (24 × 3 répétitions). Le contenu des messages reste livré et vérifié, même lorsqu'une échéance est dépassée.", H-144)
    rows = [["Politique", "Régulier", "Rafales", "Ralenti"]]
    for p, name in zip(POLICIES, LABELS):
        rows.append([name] + [lookup[s, p]['deadline_misses_total'] for s in SCENARIOS])
    y = table(rows, [165, 108, 108, W-2*M-381], y-5)
    rows = [["Débit médian (messages/s)", "Régulier", "Rafales", "Ralenti"]]
    for p, name in zip(POLICIES, LABELS):
        rows.append([name] + [f"{lookup[s,p]['throughput_messages_s_median']:.1f}" for s in SCENARIOS])
    y = table(rows, [165, 108, 108, W-2*M-381], y)
    y = para("<b>Lecture.</b> Sur les rafales, ODVL seul améliore le P95 face à FIFO dans ce banc, mais dépasse davantage d'échéances. EWMA seule et le tri par échéance évitent ici les retards. L'hybride ne domine ni l'un ni l'autre. Sur le service ralenti, l'hybride conserve plus de retards que le tri par échéance.", y)
    para("<b>Amélioration à évaluer :</b> définir l'objectif métier (délais, débit, équité), calibrer le poids ODVL sur des charges distinctes, puis figer la politique avant des tests sur des traces nouvelles. Ne pas ajuster sur ce jeu et le réutiliser comme preuve indépendante.", y, small)
    finish()

    title("Guide développeur", "Installer, reproduire, examiner")
    y = para("<b>1. Dans l'espace Cloud.</b> Créer une entité de laboratoire par programme. Autoriser son principal en lecture et écriture sur ces seules entités. La clé doit permettre les dépôts, la lecture de jobs, TSST, ODVL et SAWM. Conserver les secrets dans un fichier privé, hors Git.", H-144)
    y = para("<b>2. Installer le code.</b> Chaque dépôt contient README, exigences, tests, SDK Cloud officiel, politique bornée et preuves mesurées. Python suffit ; aucun pilote radio, accès root ni changement du réseau de l'hôte n'est requis.", y)
    rows = [["Programme", "Point d'entrée"],
            ["Résilience applicative", "lab.py --messages 20 --policy POLICY.json --output-dir NOUVEAU_DOSSIER"],
            ["Réseau intelligent", "queue_engine.py --count 24 --repetitions 3 --orders ORDERS.json --policy POLICY.json --output RESULTAT.json"],
            ["Raccordement Cloud commun", "cloud_control.py prepare / record --kind network / delivery --run ..."]]
    y = table(rows, [142, W-2*M-142], y)
    y = para("<b>3. Examiner les preuves.</b> Les rapports JSON gardent les politiques, les réceptions, les empreintes, l'ordre des essais et les opérations Cloud. Une empreinte relie les fichiers ; elle n'est pas une signature indépendante du serveur Cloud. Les échecs de validation ne sont pas convertis en succès.", y)
    y = para("<b>4. Séparer les usages.</b> Les profils de trafic sont synthétiques, les échanges HTTP et les redémarrages sont réels. Ces programmes ne configurent ni réseau opérateur, ni véhicule, ni système radio. Le dimensionnement industriel, les vrais liens distants et les garanties de disponibilité restent à évaluer.", y)
    y = para('<b>Dépôts :</b><br/><link href="https://github.com/SAWM-io/sawm-smart-reseau">github.com/ulookme/sawm-reseau-intelligent</link><br/><link href="https://github.com/SAWM-io/sawm-anti-brouillage">github.com/ulookme/sawm-resilience-applicative</link>', y)
    para("Sources du rapport : network-benchmark.json ; delivery-benchmark/report.json ; quatre cloud-report.json de calibration et de bilan. Version de campagne : 27 octobre 2026. Voir les README pour les commandes complètes et les identifiants de commit.", y, small)
    finish()
    c.save()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    build(args.input, args.output)
