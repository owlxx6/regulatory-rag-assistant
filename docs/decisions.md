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

## 2026-10-07 — Arbitrage du reranking : le modèle léger est retenu

**Mesure.** Les deux cross-encoders, même jeu de 41 questions, même chaîne en amont :

| Modèle | Paramètres | recall@5 | MRR | latence p50 |
|---|---|---|---|---|
| `mmarco-mMiniLMv2-L12-H384` | 118 M | **0,610** | **0,454** | **9 317 ms** |
| `bge-reranker-v2-m3` | 568 M | 0,561 | 0,428 | 60 040 ms |

**Décision : le modèle léger.** Il est retenu comme configuration par défaut, et la comparaison
reste au dépôt.

**Ce que la mesure permet d'affirmer, et ce qu'elle ne permet pas.** L'écart de latence est d'un
facteur 6,4 et ne souffre aucune ambiguïté. L'écart de qualité, lui, vaut 25 questions contre 23
sur 41 : deux questions, pour une granularité de 2,44 points par question. **Les deux modèles
sont indiscernables en qualité à cette taille d'échantillon**, et prétendre que le léger est
« meilleur » serait surinterpréter du bruit. Ce qu'on peut dire : il n'est pas moins bon, et il
coûte six fois moins.

**Hypothèse sur le contre-résultat, non vérifiée.** Un cross-encoder plus gros devrait dominer.
L'explication plausible tient aux paires interlingues — question française, passage anglais :
`mmarco-mMiniLMv2` est entraîné sur mMARCO, qui contient explicitement des paires de ce type,
tandis que bge-v2-m3 est optimisé pour le rappel multilingue monolingue. La vérifier demanderait
de ventiler le gain par langue, ce qui n'est pas fait.

**Correction d'une mesure antérieure.** La latence de bge relevée en août était de 139 s ; le run
dédié donne 60 s. L'écart vient des conditions de mesure — la première série enchaînait les cinq
configurations, avec contention thermique probable. C'est la valeur de 60 s qui est retenue, issue
d'un run isolé.

**Conséquence sur le budget de latence.** Aucune des deux configurations ne tient les 2 secondes.
La configuration hybride sans reranking les tient avec deux ordres de grandeur de marge, à 221 ms,
pour 0,366 de recall@5 — c'est l'arbitrage qui reste ouvert pour un déploiement réel : 25 questions
correctement servies en 9,3 s, ou 15 en 0,2 s.

---

## 2026-10-07 — Fournisseur de génération : API compatible OpenAI plutôt qu'Ollama

**Choix.** `ClientCompatibleOpenAI`, pointé sur Groq avec `openai/gpt-oss-120b`. Une seule
implémentation couvre Groq, Mistral, OpenRouter et Together : ils partagent le contrat HTTP
d'OpenAI et ne diffèrent que par l'URL de base et le nom du modèle.

**Pourquoi pas Ollama, pourtant installé.** Un modèle de 7 milliards de paramètres sur ce CPU
Intel demande environ une heure pour les 56 questions, avec un suivi d'instruction nettement
plus faible qu'un modèle de 120 milliards servi par API. Or le critère le plus exigeant du
projet est l'abstention, qui est précisément du suivi d'instruction strict. Mesurer avec un
modèle faible aurait mélangé deux causes d'échec : le prompt et la capacité du modèle.

**Ce qu'Ollama reste.** L'implémentation et le serveur local sont en place. L'argument
« la chaîne tourne sans qu'aucune donnée ne quitte la machine » est vérifiable, et c'est
l'intérêt de l'interface `LLMClient` : le fournisseur se change dans `.env`, jamais dans le code.

**Limite de débit.** Le palier gratuit plafonne à 8 000 tokens par minute, soit environ quatre
questions — une question consomme près de 2 000 tokens avec ses cinq passages. Le client lit la
durée d'attente dans les en-têtes du fournisseur (`retry-after`,
`x-ratelimit-reset-tokens`, y compris la forme « 7m12s ») plutôt que de deviner : attendre la
bonne durée une fois coûte moins que dix réessais trop tôt.

---

## 2026-10-07 — Le taux de citation mesuré à 0,81 était un défaut de mesure

**Symptôme.** Sept réponses comptées « sans citation », alors qu'elles citaient correctement.

**Cause.** Les modèles de la famille gpt-oss émettent des crochets pleine largeur — 【1】
(U+3010/U+3011) — et non les crochets ASCII attendus par le détecteur. Les réponses étaient
sourcées ; le code ne savait pas les lire.

**Correction.** Le motif accepte les deux formes, et trois tests couvrent le cas, dont les
crochets mixtes dans une même réponse et un numéro pleine largeur hors plage.

**Ce que la mesure vaut en attendant un nouveau run.** 0,81 est un **plancher** : il a été
obtenu avec un détecteur qui ratait une forme de citation valide. Le recalcul sur les réponses
déjà stockées est impossible, parce qu'elles étaient tronquées à 400 caractères dans le JSON —
défaut corrigé lui aussi, les réponses sont désormais conservées intégralement pour qu'un
détecteur amélioré puisse être rejoué sans redépenser d'appels API.

**Leçon.** Un contrôle programmatique est du code, donc faillible comme le reste. « Vérifier que
le modèle cite » suppose de savoir reconnaître une citation, et cette hypothèse méritait un test.

---

## 2026-10-07 — q044 reste classée hors-corpus malgré la réponse du modèle

**Fait.** Sur les 15 questions hors-corpus, 14 ont donné lieu à une abstention. La quinzième,
q044 (« Quelles obligations le RGPD impose-t-il ? »), a reçu une réponse.

**Vérification.** Le corpus mentionne effectivement le règlement 2016/679 : quatre chunks des
orientations EBA sur l'octroi de crédit demandent aux établissements de respecter le RGPD
lorsqu'ils collectent des données d'emprunteur auprès de tiers. Le modèle n'a donc pas inventé —
il a répondu depuis un passage réellement pertinent.

**Décision : ne pas reclasser.** Les passages disent « respectez le RGPD », ils n'énoncent pas ce
que le RGPD impose. La question porte sur les obligations ; le corpus n'y répond pas, il y
renvoie. Reclasser l'étiquette après avoir constaté le résultat reviendrait à ajuster le test au
score, et le seuil de 0,90 est de toute façon atteint sans cela.

**Ce que le cas enseigne sur la construction du jeu.** Écrire une question hors-corpus demande de
vérifier que le corpus n'effleure pas le sujet, et non seulement qu'il ne le traite pas. Un
corpus réglementaire renvoie constamment à d'autres textes : ces renvois créent des zones grises
où l'abstention et la réponse sont toutes deux défendables.

---

## 2026-10-06 — La recherche lexicale était inopérante : OU au lieu de ET

**Symptôme.** Première évaluation du volet lexical : recall de 0,00 à tous les k, et
`chunks_retournes` vide sur les 41 questions. Latence médiane de 0,7 ms — la requête ne
ramenait rien du tout.

**Cause.** `websearch_to_tsquery` combine les termes en **ET**. Une question de douze mots
exigeait donc les douze lexèmes dans un même chunk, ce qui n'arrive jamais. Ce comportement
convient à une barre de recherche où l'on saisit deux ou trois mots-clés ; il est inadapté à une
question en langage naturel.

**Pourquoi ce n'était pas apparu plus tôt.** Les tests manuels portaient sur des requêtes
courtes (« ratio de levier minimal »), où l'intersection des termes reste plausible. Le bug ne se
révèle qu'avec de vraies questions — donc seulement en présence du jeu d'évaluation. Les
latences mesurées en août (hybride 222 ms, quasi identique au vectoriel 227 ms) en portaient
d'ailleurs la trace : le volet lexical ne coûtait rien parce qu'il ne faisait rien.

**Correction.** Les lexèmes de la question sont extraits par `to_tsvector` puis combinés en OU.
Tout chunk partageant au moins un lexème devient candidat, et `ts_rank_cd` les classe sur la
densité et la proximité des termes. Extraire les lexèmes via `to_tsvector` garantit que
racinisation et mots vides suivent exactement la configuration de la colonne indexée.

**Leçon à retenir.** Un composant peut être silencieusement inopérant et laisser passer tests
unitaires, revue de code et mesures de latence. Seule une mesure de qualité sur des données
réalistes l'a révélé. C'est l'argument le plus concret en faveur d'un jeu d'évaluation.

---

## 2026-10-06 — RRF non pondéré dégrade le meilleur récupérateur

**Mesure.** recall@5 : vectoriel seul 0,512, hybride RRF 0,366. La fusion fait **perdre
14,6 points**.

**Cause.** RRF attribue `1/(k + rang)` sans distinction d'origine. Un résultat lexical au rang 1
reçoit donc le même poids qu'un résultat vectoriel au rang 1, alors que le volet lexical
plafonne à 0,195 de recall@5 contre 0,512 pour le vectoriel. La fusion dilue le bon classement
dans le bruit du mauvais.

**Ce que cela dit de RRF.** Sa robustesse tient à une hypothèse implicite — des récupérateurs de
qualité comparable. Hypothèse fausse sur ce corpus, pour une raison structurelle : le `tsvector`
français ne peut rien apparier sur 76 % des chunks, qui sont anglophones.

**Pistes, dans l'ordre de préférence.** Corriger d'abord la cause (indexation lexicale par
langue), pas le symptôme. Si l'écart persiste, pondérer les contributions RRF selon le recall
mesuré de chaque récupérateur, ou n'activer la fusion que lorsque le score lexical dépasse un
seuil. Aucune de ces pistes n'a de sens avant que l'indexation bilingue soit traitée.

---

## 2026-10-06 — L'écart français/anglais est de 37 points

**Mesure.** recall@5 selon la langue du passage attendu, configuration hybride + reranking
léger : **0,89 en français** (8 questions sur 9), **0,52 en anglais** (16 sur 31).

**Interprétation.** Les questions sont posées en français. Quand la réponse est dans la notice
ACPR, les trois étages fonctionnent — lexical, vectoriel, reranking. Quand elle est dans un texte
du Comité de Bâle, le volet lexical est structurellement aveugle et le vectoriel multilingue
porte seul.

**Conséquence mesurable sur les types de questions.** Les questions factuelles tombent à 0,53,
sous les définitions (0,73) et les références explicites (0,71), alors qu'elles devraient être
les plus faciles. Les seuils chiffrés du corpus sont énoncés en anglais : la cause racine se
propage jusque dans la typologie.

**La limite consignée le 31 juillet est donc confirmée et chiffrée.** Elle était alors une
hypothèse prudente ; elle est maintenant un résultat. L'ordre — documenter la limite, puis la
mesurer, puis décider — est ce qui rend la correction défendable plutôt qu'improvisée.

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
