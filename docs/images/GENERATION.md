# Illustration de présentation

Visuel : `sawm-smart-reseau-overview.png`.

Généré le 27 octobre 2026 avec l’outil intégré **image_gen**, puis contrôlé visuellement. La fleur SAWM & Basira fournie par le propriétaire sert de référence de marque. Texte anglais pour les deux versions de l’article. Il s’agit d’un schéma de communication, pas d’un graphique de mesures.

Les chiffres proviennent de [la campagne Smart Réseau](../measured-2026-10-27/benchmark.json) (45 passages, 1 080 reçus vérifiés, zéro erreur, cinq politiques). Les limites de portée sont rappelées dans l’image et les articles.

## Prompt de génération

```text
Use case: ads-marketing / infographic-diagram. Create a polished landscape 3:2 high-resolution promotional infographic for a GitHub README and Medium article, matching a premium SAWM & Basira monochrome brand. The provided image is the flower logo, a supporting brand input: reproduce its recognizable geometric flower at upper left near the brand name, not as a busy background. New artwork derived from this brand input. White background, black/white/silver/grays only. Swiss editorial typography, generous whitespace, minimal elegant enterprise design, clean isometric server and message icons. Exact main title "SAWM Smart Réseau". Exact subtitle "Measure. Prioritize. Verify." Small brand "SAWM & BASIRA". Central diagram must make two lanes clear: top lane "BEFORE THE RUN · CLOUD", with four compact connected blocks labeled "Basira · remember", "TSST · recall", "SAWM · policy", "ODVL · rank". Bottom lane "DURING THE RUN · LOCAL", showing a queue of incoming message tiles, priority ordering, HTTP server processing and checked receipts; exact stage labels "Messages" -> "Priority queue" -> "HTTP service" -> "Verified receipts". A feedback arrow from receipts to priority queue labeled "Observed latency · EWMA". Thin arrows from upper policy and ranking blocks to local priority queue only. Three large proof cards across lower portion: "1,080" then "verified receipts"; "0" then "delivery errors"; "5" then "policies compared". Footer exact text "Synthetic localhost benchmark · Trade-offs measured · No universal speed advantage". There are five compared queue policies: FIFO, deadline-first, EWMA, ODVL, EWMA+ODVL; if space allows include these as five discreet tags but do not overcrowd. Do not depict routers changing network paths, radio towers, Internet control, AI brain inside each packet, claimed latency improvement or fictional data charts. It is an application queue benchmark, not an IP router. Make the evidence cards visually striking and all text legible.
```

## Retouche finale

Suppression de la flèche entre les blocs SAWM et ODVL : leurs sorties vers la file sont distinctes.

```text
Use case: precise-object-edit. Edit only one detail of this existing SAWM Smart Réseau infographic: remove the small horizontal right-pointing arrow located between the SAWM · policy box and the ODVL · rank box in the upper Cloud lane. Fill that tiny gap with the same plain light gray lane background. SAWM policy and ODVL ranking are independent outputs feeding the local queue, so there must be NO horizontal connection between these two top boxes. Preserve absolutely all other content, text, logo, style, placement, figures, metrics and arrows, in particular preserve the two separate downward arrows from SAWM and ODVL into the local Priority queue. Do not add any new text. Same exact size and layout.
```
