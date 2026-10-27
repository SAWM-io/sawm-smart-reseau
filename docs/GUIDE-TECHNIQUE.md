# SAWM Smart Réseau — guide technique

[Présentation française](../README.md) · [English overview](../README.en.md)

Ce guide décrit les contrats, les mesures et le fonctionnement du prototype.

Ce programme compare cinq façons d’ordonner une petite file de messages envoyés
à un service HTTP local. Il optimise la **file applicative**, sans modifier le
transport IP, les routes, une interface radio, le GNSS ou un appareil. Il ne
fournit aucune fonction de navigation, de guidage ou d’anti-brouillage.

Le banc utilise uniquement `127.0.0.1` et `/messages`, sur un port éphémère créé
localement. Aucun hôte, URL ou paramètre réseau arbitraire n’est configurable.
Python 3.10+ et sa bibliothèque standard suffisent au moteur.

## Exécution locale

Depuis la racine du dépôt, dans un environnement virtuel Python 3.10+ :

```sh
python3 -m venv .venv
source .venv/bin/activate
python3 queue_engine.py --count 24 --repetitions 3 --output output/offline.json
python3 -m pip install -r requirements.txt
python3 -m unittest discover -s tests -v
```

Sans fichier d’ordres, les politiques portant le nom ODVL utilisent une liste
identité explicitement marquée `offline_identity`. Cela ne simule pas une API
et ne démontre aucun effet d’ODVL. Le fichier résultat doit être neuf.

## Ordres Basira réels fournis séparément

Après la préparation Cloud décrite plus bas, les fichiers d’ordres et de politique peuvent être réutilisés sans connexion Cloud :

```sh
python3 workloads.py --count 24 --output output/workloads-public.json
python3 queue_engine.py --count 24 --repetitions 3 \
  --orders output/cloud-prepare/odvl-orders.json --policy output/cloud-prepare/policy.json \
  --output output/benchmark-cloud-orders.json
```

L’export public exclut `service_ms`, la durée future connue seulement du serveur
témoin. Les décisions Cloud peuvent utiliser les identifiants, arrivées,
échéances, classes de service et tailles de charge utile. L’appel Cloud et les
droits d’accès sont gérés séparément ; le moteur ne lit aucun identifiant secret.

Dans le connecteur actuel, les candidats effectivement transmis à ODVL portent
`candidate_id`, un `score` dérivé du budget d’échéance, `importance: 0.5` et
`anchor: false`. Le score vaut `1 / (1 + max(0, deadline_ms - arrival_ms) / 100)`,
arrondi à six décimales. La présence des champs publics dans l’export ne signifie
donc pas que tous ces champs alimentent le classement.

Le fichier `civil-odvl-orders/v1` contient un ordre par scénario, la réponse
publique ODVL originale et une preuve avec `analysis_id`, `entity_id`,
`memory_space_id`, `ranking_applied`, `response_sha256` et `workload_sha256`.
L’ordre doit être une permutation exacte des tâches et correspondre aux rangs
de la réponse. Les empreintes portent sur le JSON canonique UTF-8 : clés triées,
séparateurs `,` et `:`, `ensure_ascii=True`. Le hash du workload porte sur
`scenarios[nom]` de l’export public. Cette vérification prouve la cohérence du
fichier fourni, pas une signature indépendante du Cloud.

Le fichier de politique optionnel est strictement :

```json
{"schema":"civil-queue-policy/v1","ewma_alpha":0.35}
```

L’alpha est borné à `[0.1, 0.9]` et identique pour EWMA seule et EWMA+ODVL.
Le rapport conserve son empreinte. Le rapport du contrôleur Cloud peut relier
cette empreinte à la réponse qui l’a proposée.

## Comparaison équitable

Chaque politique reçoit exactement les mêmes arrivées, charges et durées du
serveur pour un scénario donné. La concurrence maximale est toujours **4**.
Seuls les messages déjà arrivés sont éligibles ; aucun message n’est supprimé
par son rang. Les ordres Cloud sont chargés avant la boucle des messages.

| Politique | Choix parmi les messages éligibles |
| --- | --- |
| `fifo` | Arrivée, puis identifiant. |
| `deadline_first` | Échéance absolue la plus proche, puis arrivée. |
| `ewma` | Estimation de latence HTTP la plus basse par classe. |
| `odvl` | Rang dans la liste ODVL fournie, sans estimation EWMA. |
| `ewma_odvl` | Estimation EWMA + 25 ms × rang normalisé. |

EWMA part de 40 ms pour chaque classe et apprend exclusivement les latences HTTP
déjà mesurées entre émission et reçu. Son état est réinitialisé à 40 ms avant chaque
passage. Elle n’utilise jamais la durée future `service_ms`. Le coefficient de
25 ms de l’hybride est une convention explicite du prototype, pas une calibration
universelle.

Trois scénarios déterministes sont fournis : `stable`, `burst` (rafales) et
`slow_service` (service lent). La taille est bornée à 16–64 messages, 24 par
défaut. Trois répétitions changent l’ordre des politiques par rotations et
inversion pour répartir les effets de position ; cela ne constitue pas un plan
statistique complet. Un passage est borné à cinq secondes d’admission, avec un
timeout HTTP d’une seconde ; la charge normale du témoin est plus courte.

## Lecture des résultats

Les p50/p95 mesurent la latence de bout en bout depuis l’arrivée programmée
jusqu’au reçu HTTP validé, attente dans la file comprise. Ils utilisent une
interpolation linéaire sur les messages reçus avec succès ; les erreurs restent
comptées séparément. `deadline_misses` inclut les reçus après l’échéance et les
messages non livrés. Le débit est le nombre de messages reçus divisé par la durée
totale du passage, avec les pauses d’arrivée. Les reçus sont uniques par message
et passage, et le serveur refuse une seconde livraison du même identifiant.

Le rapport conserve chaque mesure, l’ordre d’exécution, les hashes des workloads,
les erreurs, les maximums de concurrence et les médianes entre répétitions.
Comparer aussi l’heuristique simple `deadline_first`, les erreurs et les
échéances ; une baisse de p95 seule ne démontre pas une amélioration générale.
Le bruit d’ordonnancement du système, les courtes durées et les tâches
synthétiques limitent la portée des mesures. Aucun gain n’est garanti.

## Connexion aux quatre API publiques

1. Dans <https://basira.sawm.io/espace>, sélectionner son environnement et créer une entité de service réservée aux essais. Donner au principal de la clé les droits `read, write` sur cette entité, sans `admin` ni purge. La clé doit également autoriser `events:write`, `jobs:read`, `tsst:recall`, `odvl:rank`, `sawm:run`.
2. Copier `.env.example` **hors du dépôt** et renseigner espace et clé. Exécuter `chmod 600 /chemin/prive/basira.env`. Ne jamais mettre la clé dans un commit, un argument de commande ou une capture.
3. Installer `python3 -m pip install -r requirements.txt`. Le moteur local utilise uniquement la bibliothèque standard ; le connecteur Cloud utilise le SDK Python officiel, recopié dans `vendor/basira_client.py` pour rendre ce dépôt autonome.
4. Produire une calibration locale avec 16 messages par essai. Conserver un résumé compact de ses mesures (moins de 900 caractères), sans les durées futures des messages du test. Un exemple de structure est livré dans `docs/calibration-summary.json`.

```bash
python3 queue_engine.py --count 16 --repetitions 1 --output output/calibration.json
python3 workloads.py --count 24 --output output/workloads-test.json
```

Générer ensuite `output/calibration-summary.json` avec le premier extrait de la
[section suivante](#produire-les-résumés-de-votre-campagne), puis lancer :

```bash
python3 cloud_control.py prepare --kind network \
  --credentials /chemin/prive/basira.env --entity ent_VOTRE_ENTITE \
  --summary output/calibration-summary.json --workloads output/workloads-test.json \
  --output output/cloud-prepare --run
python3 queue_engine.py --count 24 --repetitions 3 \
  --orders output/cloud-prepare/odvl-orders.json \
  --policy output/cloud-prepare/policy.json --output output/benchmark.json
```

Utiliser les mesures de **votre** calibration. `ent_VOTRE_ENTITE` doit être remplacé par l’identifiant réel de votre entité, au format `ent_` suivi de 32 caractères hexadécimaux minuscules. Chaque fichier de résultat et répertoire de sortie Cloud doit être neuf. `--run` déclenche des appels Cloud potentiellement facturés. Le nom historique `--kind network` désigne ici le banc de file applicative.

Le connecteur dépose ce résumé dans Basira, attend le traitement, vérifie son rappel littéral par TSST, obtient trois classements ODVL et demande à SAWM un coefficient EWMA borné. Un JSON invalide est refusé. Le coefficient est identique pour EWMA seule et EWMA + ODVL ; les durées de traitement futures restent absentes des entrées Cloud. L'ordre ODVL contient exactement les candidats fournis. Les traces relient l'ordre au jeu de travail par SHA-256.

Après le banc, créer un résumé mesuré compact puis le déposer et demander un bilan :

```bash
python3 cloud_control.py record --kind network \
  --credentials /chemin/prive/basira.env --entity ent_VOTRE_ENTITE \
  --summary output/results-summary.json --output output/cloud-results --run
```

Les fichiers `cloud-report.json`, `policy.json` et `odvl-orders.json` établissent les appels réellement effectués. Une réponse SAWM est un avis : elle ne remplace pas les compteurs du banc. Aucun appel Cloud ne bloque un message pendant les essais ; un ordre et une politique déjà validés restent utilisables hors ligne. Cela ne démontre pas un routage télécom, une garantie temps réel matériel ni une résistance au brouillage radio.

## Produire les résumés de votre campagne

Ces extraits se lancent depuis la racine du dépôt, dans l’environnement virtuel
activé. Ils lisent uniquement les agrégats du banc synthétique. Ils n’effectuent
aucun appel Cloud et refusent d’écraser un résumé existant.

**Avant `prepare`**, après avoir créé `output/calibration.json` :

```bash
python - <<'PY'
import json
from pathlib import Path

report = json.loads(Path("output/calibration.json").read_text())
summary = {
    "kind": "civil_http_queue_calibration",
    "messages_per_trial": report["parameters"]["messages_each"],
    "network_changes": False,
    "cloud_used": False,
    "scenarios": [
        {
            "name": row["scenario"],
            "fifo_p95_ms": round(row["p95_ms_median"], 2)
                if row["p95_ms_median"] is not None else None,
            "fifo_missed": row["deadline_misses_total"],
            "errors": row["errors_total"],
        }
        for row in report["summary"] if row["policy"] == "fifo"
    ],
    "scope": "synthetic_localhost_http",
}
text = json.dumps(summary, separators=(",", ":"), ensure_ascii=True)
assert len(text) < 900, "Reduce the summary before Cloud preparation"
with Path("output/calibration-summary.json").open("x") as stream:
    stream.write(text + "\n")
print(text)
PY
```

**Après le benchmark**, avant `record`, générer un bilan qui conserve les
échéances manquées en plus des p95 et erreurs :

```bash
python - <<'PY'
import json
from pathlib import Path

report = json.loads(Path("output/benchmark.json").read_text())
summary = {
    "kind": "queue_measured_results",
    "messages": report["parameters"]["messages_each"],
    "repetitions": report["parameters"]["repetitions"],
    "receipts": sum(row["unique_receipts_total"] for row in report["summary"]),
    "errors": sum(row["errors_total"] for row in report["summary"]),
    "columns": ["scenario", "policy", "p95_ms_median", "deadline_misses_total"],
    "rows": [
        [row["scenario"], row["policy"],
         round(row["p95_ms_median"], 1) if row["p95_ms_median"] is not None else None,
         row["deadline_misses_total"]]
        for row in report["summary"]
    ],
    "scope": "synthetic_localhost_http",
}
text = json.dumps(summary, separators=(",", ":"), ensure_ascii=True)
assert len(text) < 900, "Reduce the summary before recording"
with Path("output/results-summary.json").open("x") as stream:
    stream.write(text + "\n")
print(text)
PY
```

Le contrôleur enveloppe le résumé dans un enregistrement identifié par campagne
et phase, limité à 1 300 caractères en JSON canonique. Il vérifie ensuite le job
Basira et le rappel littéral TSST. Une réponse de politique invalide interrompt
la préparation ; aucun code ou commande proposé par SAWM n’est exécuté.

## Résultat vérifié et limites

Le dossier [measured-2026-10-27](measured-2026-10-27/) contient la campagne réelle avec API Basira/TSST/ODVL/SAWM et ses métriques. Le benchmark totalise **1 080 reçus vérifiés et 0 erreur de livraison**, soit 5 politiques × 3 scénarios × 3 répétitions × 24 messages. Les échéances manquées restent comptabilisées séparément. Aucun appel Cloud n’a lieu pendant les passages.

Le comparatif conserve tous les résultats : l’hybride EWMA + ODVL n’est pas systématiquement meilleur que les références. Aucune promesse d’accélération universelle n’est déduite de ces essais locaux. Le fichier `final-validator-check.json` revalide une réponse archivée ; son champ `real_api_rerun: false` indique explicitement qu’il ne s’agit pas d’un nouvel appel API.

Les preuves JSON et le rapport PDF sont conservés tels qu’archivés. Les empreintes vérifient la cohérence des fichiers, sans constituer une signature indépendante du service Cloud. La préparation SAWM a lieu avant le banc ; seule l’estimation EWMA s’adapte aux latences observées pendant chaque passage.
