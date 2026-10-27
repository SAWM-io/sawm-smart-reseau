# SAWM Smart Réseau : faire passer les bons messages au bon moment

![SAWM Smart Réseau : préparation Cloud, file locale adaptative et reçus vérifiés](../images/sawm-smart-reseau-overview.png)

*Une file applicative qui compare ses choix, utilise les temps de réponse observés et conserve les preuves avec Basira Cloud.*

Une confirmation attendue par un client, un événement de suivi logistique et un traitement de fond arrivent ensemble. Le service ne peut pas tout traiter immédiatement. Quel message doit passer en premier ?

Cette décision influence l’attente, le respect des échéances et la qualité du service. Ajouter des ressources peut aider, mais il faut aussi comprendre ce que produit l’ordre de traitement.

**SAWM Smart Réseau permet de mesurer cet arbitrage.** Le prototype associe un moteur local de file HTTP aux API Basira, TSST, ODVL et SAWM. Son premier résultat vérifiable : **1 080 reçus validés, aucune erreur de livraison**, sur une campagne synthétique exécutée contre un véritable service HTTP local. Des échéances ont été dépassées ; elles figurent dans les résultats.

## Une expérience que l’on peut examiner

La campagne du 27 octobre 2026 comporte **45 passages** : cinq politiques, trois scénarios, trois répétitions et 24 messages par passage. Les scénarios représentent un flux stable, des rafales et un service qui ralentit.

Chaque politique reçoit les mêmes arrivées, charges et durées de traitement, avec au maximum quatre requêtes simultanées. Seuls les messages déjà arrivés peuvent être sélectionnés. Les durées futures, connues du serveur témoin pour produire la charge, restent absentes des décisions et des entrées Cloud.

Le [rapport brut de la campagne](https://github.com/SAWM-io/sawm-smart-reseau/blob/main/docs/measured-2026-10-27/benchmark.json) conserve les messages, reçus, erreurs, temps mesurés et ordres d’exécution. Il permet de vérifier les chiffres indépendamment des commentaires de SAWM.

## Cinq façons de décider

Le moteur compare cinq politiques :

- **FIFO** : traiter dans l’ordre d’arrivée.
- **Échéance d’abord** : choisir le message dont l’échéance est la plus proche.
- **EWMA** : privilégier la classe de service dont le temps HTTP estimé est le plus court ; l’estimation évolue avec les réponses reçues.
- **ODVL** : suivre un classement préparé dans le Cloud, parmi les messages disponibles.
- **EWMA + ODVL** : combiner l’estimation locale et le rang Cloud.

L’hybride utilise actuellement un poids de 25 millisecondes pour le rang normalisé. C’est un paramètre explicite du prototype à évaluer, pas une valeur optimale pour tous les clients. L’estimation EWMA repart de 40 millisecondes à chaque passage ; ce banc ne démontre pas un apprentissage autonome permanent entre campagnes. Le [moteur](https://github.com/SAWM-io/sawm-smart-reseau/blob/main/queue_engine.py) rend ces choix inspectables.

## Ce que font réellement les quatre technologies

**Basira conserve l’expérience de la campagne.** Le connecteur dépose un résumé de calibration, puis peut enregistrer le bilan mesuré.

**TSST vérifie le rappel.** Le programme recherche le résumé et contrôle qu’il retrouve littéralement l’enregistrement attendu, dans le bon espace et pour la bonne entité.

**ODVL prépare les priorités.** Il classe les candidats avant le passage. Dans cette version, leurs scores proviennent du budget d’échéance ; le classement doit contenir exactement les candidats fournis. Il reste fixe pendant l’essai.

**SAWM propose un réglage et peut analyser le bilan.** Il fournit le coefficient d’apprentissage EWMA, accepté seulement entre 0,1 et 0,9. La campagne utilise 0,35. Aucun code proposé par le modèle n’est exécuté.

Pendant les passages, **aucun appel Cloud ne bloque les messages**. La sélection et l’adaptation EWMA s’exécutent localement, avec les fichiers préalablement validés. Les [traces de préparation Cloud](https://github.com/SAWM-io/sawm-smart-reseau/blob/main/docs/measured-2026-10-27/cloud/cloud-report.json) documentent les appels réellement réalisés.

## Les résultats montrent pourquoi il faut comparer

Sur les rafales, les résultats sont les suivants :

| Politique | p95, en ms | Échéances manquées sur 72 messages |
|---|---:|---:|
| FIFO | 80,3 | 8 |
| Échéance d’abord | 94,4 | 0 |
| EWMA | 93,4 | 0 |
| ODVL | 69,8 | 15 |
| EWMA + ODVL | 95,2 | 6 |

Le p95 inclut l’attente en file, depuis l’arrivée programmée jusqu’au reçu validé. Ici, chaque valeur est la médiane des trois p95 de passage.

ODVL obtient le p95 le plus faible, mais manque davantage d’échéances que FIFO. Avec un service lent, la politique par échéance en manque 30, contre 48 pour FIFO et 44 pour l’hybride. **L’hybride n’est donc pas systématiquement meilleur.** Les [mesures complètes](https://github.com/SAWM-io/sawm-smart-reseau/blob/main/docs/measured-2026-10-27/benchmark.json) conservent ces compromis.

## Ce qu’une équipe peut en faire

Un éditeur SaaS peut évaluer comment protéger les délais des opérations interactives pendant un traitement de fond. Un intégrateur logistique peut comparer les priorités d’événements de suivi et de synchronisation. Une plateforme documentaire peut étudier la concurrence entre petites requêtes et traitements longs.

Ce sont des pistes de pilotes. Le dépôt fournit le banc, pas des connecteurs métier déjà validés. Le bénéfice immédiat est de choisir une politique avec des mesures et un historique vérifiable. Les économies de ressources et les gains métier devront être mesurés sur la charge du client.

## Et dans les réseaux et télécoms ?

Un pilote pourrait étudier la priorité des alertes d’un site industriel, des événements de supervision ou des synchronisations différées. Le programme actuel ordonne les messages vers un service ; il ne choisit pas encore un chemin entre plusieurs relais.

Pour aller plus loin, il faudrait mesurer chaque liaison, gérer les chemins alternatifs et vérifier la livraison de bout en bout. [Multipath TCP](https://www.rfc-editor.org/rfc/rfc8684.html) permet d’utiliser plusieurs chemins entre deux extrémités ; [Bundle Protocol](https://www.rfc-editor.org/rfc/rfc9171.html) définit un cadre de communication pour les réseaux tolérant les délais et interruptions. Ce sont des points d’intégration possibles, pas des fonctionnalités déjà raccordées ici. La contribution de SAWM et Basira serait alors à mesurer : quelles décisions améliorent réellement la reprise, les échéances ou les coûts ?

## Reproduire puis connecter son propre espace

Avec Python 3.10 ou supérieur et l’accès au dépôt :

```bash
git clone https://github.com/SAWM-io/sawm-smart-reseau.git
cd sawm-smart-reseau
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python queue_engine.py --count 24 --repetitions 3 \
  --orders docs/measured-2026-10-27/cloud/odvl-orders.json \
  --policy docs/measured-2026-10-27/cloud/policy.json \
  --output output/medium-replay.json
```

Ce passage réutilise les véritables ordres Cloud archivés, sans nouvel appel Cloud. Le fichier de sortie doit être neuf. Les timings varieront. Sans `--orders`, les variantes ODVL utilisent un ordre identité explicitement signalé : cela ne teste pas ODVL.

Pour une nouvelle campagne, créez une entité de test dans [votre espace Basira](https://basira.sawm.io/espace). Accordez `read, write` sur cette entité et les scopes `events:write`, `jobs:read`, `tsst:recall`, `odvl:rank`, `sawm:run`. Conservez la clé hors du dépôt. Le [guide technique](https://github.com/SAWM-io/sawm-smart-reseau/blob/main/docs/GUIDE-TECHNIQUE.md) détaille calibration, génération des résumés, préparation et dépôt du bilan. L’option `--run` déclenche des appels potentiellement facturés.

**Le prochain objectif est un pilote sur votre charge réelle.** Le périmètre actuel reste une file HTTP sur localhost : aucune modification de routage IP, aucune validation radio, aucune garantie universelle de vitesse. Il fournit une base concrète pour décider quelles priorités servent réellement votre application.
