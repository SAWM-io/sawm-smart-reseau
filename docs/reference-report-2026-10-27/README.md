# Rejeu du rapport « Le Réseau qui se souvient » — 24 cellules

Le [relevé du 27 octobre 2026](reproduction.json) rejoue le banc numérique original de charge : **moyenne glissante contre moyenne + ODVL**, avec le moteur Python privé `ODVLNetwork`. Ce banc choisit des cellules selon leur charge et leur histoire. Il est distinct de `queue_engine.py`, qui ordonne des requêtes HTTP ; ses résultats ne sont pas interchangeables.

## Protocole et concordance avec le rapport

Huit graines, 400 pas de cinq minutes, 24 cellules. À chaque décision, trois cellules reçoivent chacune 34 unités de trafic pour un horizon évalué de quatre pas, sur une capacité de 100 unités. La moyenne utilise une fenêtre de 12 mesures. L'hybride ajoute l'évidence ODVL de volatilité avec le **poids fixé à 0,5**. La charge de fond est de 28–46 unités en nominal et de 40–58 en régime serré.

| Monde | Part absorbée, moyenne | Part absorbée, hybride | Redéplacements moyens, moyenne → hybride |
| --- | ---: | ---: | ---: |
| Nominal | 99,89375 % | 99,91625 % | 1,25 → 1,00 |
| Serré | 99,73625 % | 99,75750 % | 3,125 → 2,875 |

Les résultats reproduisent les valeurs arrondies du rapport : **99,89 % → 99,92 %**, **99,74 % → 99,76 %**, et environ **3,12 → 2,88 redéplacements** en régime serré. Le gain absolu de part absorbée est limité : 0,0225 point en nominal et 0,02125 point en serré. Chaque moyenne utilise les huit résultats individuels archivés, eux-mêmes arrondis par le banc original.

Le rejeu conserve deux limites du protocole original : le trafic transféré est évalué mais n'est pas réinjecté dans les charges mesurées ; le générateur aléatoire sert aussi à évaluer les charges futures, avec un nombre d'appels dépendant des choix. **Des graines égales ne garantissent donc pas des trajectoires de bruit strictement identiques entre conduites.** Ces résultats ne démontrent pas encore un gain sur un réseau opérateur réel.

## Reproduire avec les sources privées autorisées

Depuis la racine de ce dépôt, avec Python 3.10 ou ultérieur :

```sh
python3 reference_replay.py \
  --private-source-root /chemin/vers/le/depot-prive \
  --output-dir output/reference-cellules-nouvelle
```

L'arborescence privée doit contenir `experiments/equilibrage-back/{reseau_charge,equilibreurs,hybrides}.py` et `backend/services/basira_odvl.py`. Le moteur reste externe au dépôt public. L'absence des sources fait échouer explicitement le script ; il n'utilise aucun moteur de remplacement.

Le script appelle les classes originales. Il charge uniquement les définitions `ResonanceOdvl` et `Hybride` depuis l'AST du fichier privé, avec leurs dépendances réelles, pour éviter l'importation du pont TSST qui lit des fichiers de clés sans être nécessaire à cette comparaison. Aucun corps d'algorithme privé n'est recopié dans ce dépôt.

Les sorties comprennent les résultats, les SHA-256 des sources, un manifeste et quatre traces graine 0 : deux mondes × deux conduites. Les traces conservent les **24 charges observées**, le classement, les trois cellules retenues et les compteurs cumulés, sans ajouter de lecture du monde ni d'appel aléatoire. Il y a 396 décisions temporelles par trace : les quatre derniers pas servent à évaluer l'horizon. `--trace-only` produit seulement ces exemples, sans recommencer les huit graines.

## Ce qui est effectivement exécuté

ODVL fonctionne ici **avec un état qui évolue à chaque pas**, directement en Python privé. Le rejeu ne fait aucun appel Cloud, aucun appel LLM SAWM et aucun rappel TSST ; le balayage des autres poids et les autres bras du rapport ne sont pas rejoués. Une réponse publique `/odvl/rank` sans cet état n'est pas équivalente à `ODVLNetwork`. Le raccordement Cloud de cette boucle reste à construire et à mesurer séparément.

`reproduction.json` conserve intact le relevé déjà mesuré et ses empreintes. Chaque nouvelle exécution utilise un répertoire de sortie neuf ; elle ne réécrit pas les résultats historiques.

Les [4 traces graine 0 archivées](traces-seed0/replay.json) ont été rejouées par cet adaptateur ; leurs résultats correspondent exactement à la graine 0 du relevé initial. Leur [manifeste](traces-seed0/manifest.json) permet de contrôler les fichiers. La campagne complète à huit graines a ensuite été exécutée par l’adaptateur : [relevé complet](validated-full-replay.json), toutes les sources inchangées et traces cohérentes avec les résultats de référence.

[Ouvrir la visualisation autonome](index.html) — télécharger le fichier HTML puis l’ouvrir dans un navigateur ; les données sont intégrées.
