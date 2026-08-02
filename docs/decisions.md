# Journal des décisions techniques

Chaque entrée : le choix, les alternatives écartées, la raison. Ce fichier est la matière brute
des réponses en entretien — il se remplit au fil de l'eau, jamais après coup.

---

## 2026-07-31 — PostgreSQL + pgvector comme moteur unique

**Choix.** Un seul moteur de stockage pour le vectoriel (HNSW) et le lexical (tsvector + GIN).

**Alternatives écartées.**
- *Qdrant / Weaviate / Chroma pour le vectoriel + Postgres pour les métadonnées.* Deux systèmes à
  déployer, à sauvegarder et à maintenir cohérents, plus des jointures applicatives entre l'index
  vectoriel et les métadonnées documentaires.
- *Elasticsearch pour le lexical.* Puissant, mais lourd à opérer pour un corpus de quelques
  milliers de chunks, et un second moteur à déployer.

**Raison.** À l'échelle visée (300-800 pages, quelques milliers de chunks), pgvector est largement
suffisant et l'index HNSW donne des temps de recherche de l'ordre de la milliseconde. L'unicité du
stockage simplifie le déploiement et permet de filtrer sur les métadonnées documentaires dans la
même requête que la recherche vectorielle. Le point de bascule vers une base vectorielle dédiée se
situe plutôt vers le million de vecteurs.

---

## 2026-07-31 — Port 5433 pour Postgres

**Choix.** Le conteneur expose 5433 sur l'hôte, pas 5432.

**Raison.** 5432 est souvent déjà pris par un PostgreSQL installé localement. Le conflit produit
une erreur de démarrage difficile à diagnostiquer pour qui clone le dépôt. Le port est configurable
via `POSTGRES_PORT`.

---

## 2026-07-31 — Configuration `french` fixe pour le tsvector

**Choix.** `tsvector GENERATED ALWAYS AS (to_tsvector('french', contenu)) STORED`.

**Contrainte technique.** Une colonne générée n'accepte que des fonctions `IMMUTABLE`.
`to_tsvector('french', x)` l'est car la configuration est littérale ; `to_tsvector(langue::regconfig, x)`
ne l'est pas. Il est donc impossible de choisir la configuration selon la langue du document dans
une colonne générée.

**Conséquence assumée en v1.** Le corpus est mixte FR/EN. Le stemming français appliqué à du texte
anglais dégrade le rappel lexical sur la partie anglophone. L'impact réel sera chiffré au jour 5 en
comparant le recall des questions FR et EN.

**Alternatives si la mesure montre une dégradation nette.**
1. Deux colonnes `tsv_fr` et `tsv_en`, la requête interrogeant celle qui correspond à la langue.
2. Un trigger `BEFORE INSERT OR UPDATE` remplaçant la colonne générée, ce qui lève la contrainte
   d'immutabilité.
3. Configuration `simple` (pas de stemming) : neutre linguistiquement, mais perd l'appariement
   singulier/pluriel dans les deux langues.

Décision : ne pas complexifier avant d'avoir mesuré.

---

## 2026-08-02 — Latence du reranking : le critère « < 2 s » n'est pas tenu

**Mesure.** Latences à chaud, corpus de 1616 chunks, 5 questions × 2 passages, Mac Intel sans
accélération matérielle :

| Configuration | p50 | p95 |
|---|---|---|
| lexical | 1 ms | 5 ms |
| hybride (RRF) | 222 ms | 839 ms |
| vectoriel | 227 ms | 616 ms |
| hybride + reranking | 139 533 ms | 196 273 ms |

**Constat.** Les trois premières configurations tiennent le critère avec deux ordres de grandeur
de marge. Le reranking le dépasse d'un facteur 70 : `bge-reranker-v2-m3` coûte environ 4,6 s par
paire (question, passage) sur ce CPU, soit plus de deux minutes pour 30 candidats.

**Ce n'est pas une erreur d'implémentation.** Le cross-encoder est un modèle de 568 M paramètres
qui traite chaque paire intégralement, sans mise en cache possible entre requêtes. Le débit
mesuré est cohérent avec celui observé à l'indexation (3,26 s par chunk de 512 tokens).

**Gain qualitatif, lui, réel.** Sur « Quel est le ratio de levier minimal exigé ? », le vectoriel
seul remonte en deuxième position une ligne de table des matières et en troisième un passage sur
le LCR. Après reranking, ces deux résultats disparaissent et le bon passage passe de 0,877 à
0,995. L'arbitrage est donc bien qualité contre latence, pas qualité contre rien.

**Options mesurées.** Aucun réglage de `bge-reranker-v2-m3` ne tient le seuil :

| Longueur de séquence | 30 candidats | 10 candidats | 5 candidats |
|---|---|---|---|
| 512 tokens | 37,6 s | 10,6 s | 5,8 s |
| 256 tokens | 27,1 s | 8,8 s | 4,9 s |
| 128 tokens | 13,0 s | 4,8 s | 2,2 s |

Tronquer à 128 tokens ampute des chunks dont la médiane est à 315 tokens : le réglage le plus
rapide est aussi celui qui dégrade le plus la qualité, et il reste au-dessus du seuil.

**Décision.** Évaluer deux rerankers en parallèle plutôt que d'en choisir un à l'aveugle.
`cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` (118 M paramètres) est ajouté comme cinquième
configuration : **9,8 s p50 contre 139 s**, soit 14× plus rapide, avec le bon passage en tête et
un écart de score net (1,777 contre 0,429 pour le deuxième). Le tableau comparatif du README
chiffrera qualité et latence pour les deux.

**Ce que le seuil de 2 s implique vraiment.** Il reste inatteignable avec un reranking sur 30
candidats, quel que soit le modèle testé. Trois issues honnêtes, à trancher sur les chiffres de
qualité une fois l'évaluation faite : réduire le nombre de candidats rerankés (10 candidats
ramènent le modèle léger autour de 3 s), livrer la configuration hybride sans reranking comme
défaut de production (222 ms, largement sous le seuil) et le reranking en option, ou requalifier
le seuil comme dépendant du matériel. La bonne réponse dépend du gain de recall mesuré : si le
reranking n'apporte pas les 10 points visés, la question de sa latence ne se pose plus.

---

## 2026-07-31 — Périmètre du corpus : 11 documents, 796 pages

**Choix.** Solvabilité, liquidité, levier et risque de crédit. 8 documents BIS, 2 EBA, 1 ACPR.

**Écartés et pourquoi.**
- *Notice ACPR 2023.* Millésime précédent de la notice 2024 déjà retenue. Deux versions du même
  texte annuel produisent des chunks quasi identiques : le reranker ne peut pas les départager,
  les citations deviennent contradictoires, et l'annotation du jeu d'évaluation se complique
  (quel chunk est « le » pertinent quand deux formulations coexistent ?). C'est le seul retrait
  motivé par la qualité et non par le volume.
- *Risque de marché (d457), Core Principles (d573), IRRBB (EBA/GL/2022/14).* Hors du périmètre
  thématique retenu.
- *RCAP Corée (d380).* Évaluation pays, sans portée normative.

**Raison du plafond de pages.** Le cahier des charges vise 300-800 pages. La contrainte réelle
n'est pas l'ingestion mais l'annotation : chaque question du jeu d'évaluation exige d'identifier à
la main les chunks pertinents. Un corpus deux fois plus gros double ce travail sans améliorer la
démonstration.

**Conséquence assumée.** La part francophone tombe à 17 % (135 pages sur 796) au lieu des 30 %
visés. L'EBA traduit ses orientations en français : substituer la version FR d'un document EBA à
sa version EN rééquilibrerait sans coût en pages. À arbitrer après les premières mesures FR/EN
du jour 5 — pas avant, pour éviter de complexifier sans données.

---

## 2026-07-31 — Versions figées de torch et transformers

**Choix.** `torch==2.2.2`, `numpy<2`, `transformers>=4.44,<5`.

**Raison.** La machine de développement est un Mac Intel (x86_64). PyTorch a cessé de publier des
binaires macOS x86_64 après la 2.2.2. Ce binaire est compilé contre NumPy 1.x : avec NumPy 2.x,
son extension C échoue (`Failed to initialize NumPy: _ARRAY_API not found`). Par ailleurs
`transformers` 5.x exige torch ≥ 2.4 et plante au chargement de son module `tensor_parallel`.

**Conséquence.** Pas d'accélération matérielle : les embeddings et le reranking tournent sur CPU.
C'est le principal risque sur le critère de latence « < 2 s hors génération », à mesurer au jour 4.
Sur Apple Silicon ou Linux, ces trois bornes peuvent être relevées.

---

## 2026-07-31 — Docker Desktop plutôt qu'un PostgreSQL local

**Choix.** Base en conteneur, schéma appliqué automatiquement via `/docker-entrypoint-initdb.d`.

**Raison.** Un critère d'acceptation impose qu'un dépôt vierge démarre avec `docker compose up`
plus une commande. L'image `pgvector/pgvector:pg16` embarque l'extension déjà compilée ; une
installation locale imposerait de la compiler à la main. Le montage du répertoire `sql/` en
`initdb.d` supprime toute étape manuelle de création du schéma.
