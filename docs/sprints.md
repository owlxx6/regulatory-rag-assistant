# Sprints

Plan révisé le 4 octobre 2026. Le plan initial était calendaire sur trois semaines ; il est
caduc. Le travail restant n'est plus une construction mais une clôture : mesurer, décider,
documenter.

**Ce qui est déjà livré.** Ingestion complète (11 documents, 796 pages, 1 616 chunks), cinq
configurations de recherche avec leurs latences mesurées, génération contrainte avec
vérification programmatique des citations, API FastAPI en streaming, démonstration Streamlit,
50 tests, intégration continue verte, dépôt public.

**Ce qui manque.** Toutes les mesures de qualité. C'est-à-dire exactement ce qui donne sa
valeur au reste.

---

## Sprint A — Mesurer

**Objectif.** Remplir le tableau de résultats du README avec des chiffres produits par
`evaluer.py`.

| # | Tâche | Qui | Charge |
|---|---|---|---|
| A1 | Annoter les 41 questions dans-corpus | Taha | ~2 h |
| A2 | Lancer `evaluer.py` sur les cinq configurations | Claude | 30 min machine |
| A3 | Remplir le tableau du README, versionner le JSON de résultats | Claude | 15 min |
| A4 | Trancher l'arbitrage reranking sur le gain de recall mesuré | décision commune | 15 min |
| A5 | Vérifier le démarrage depuis un clone vierge | Claude | 30 min |

**Fini quand.** Le README affiche les recalls, le MRR et les latences des cinq configurations,
et `docs/decisions.md` porte la décision sur le reranking avec ses chiffres.

**A1 est le seul verrou du projet.** La pré-sélection (`scripts/pre_selection.py`) propose
359 candidats sur 29 des 41 questions : le travail est devenu de la validation. Les 12 questions
sans candidat sont multi-passages et relèvent du jugement sur la couverture.

**A4 se décide sur les chiffres, pas par principe.** Si le reranking n'apporte pas les
10 points de recall visés, la configuration hybride à 222 ms devient le défaut et la question
de sa latence disparaît. S'il les apporte, il faut choisir entre le modèle léger (9,8 s) et
le modèle prescrit (139 s), et assumer l'échec du budget de 2 s en l'expliquant.

---

## Sprint B — Clôturer la v1

**Objectif.** Rendre le projet présentable et vérifié de bout en bout.

| # | Tâche | Qui | Charge |
|---|---|---|---|
| B1 | Renseigner `ANTHROPIC_API_KEY` dans `.env` | Taha | 2 min |
| B2 | Premier appel réel de la chaîne de génération | Claude | 15 min |
| B3 | Mesurer le taux d'abstention sur les 15 questions hors-corpus | Claude | 30 min |
| B4 | Vérifier le taux de citation valide sur les questions dans-corpus | Claude | 20 min |
| B5 | Capture ou GIF de démonstration pour le README | Claude | 20 min |
| B6 | Décider du sort de `task_plan.md`, `progress.md`, `findings.md` | Taha | 2 min |
| B7 | Ligne de CV chiffrée, à partir de `evaluation/resultats/` | Claude | 10 min |

**Fini quand.** Les six critères d'acceptation sont mesurés — atteints ou documentés comme
manqués — et le README se lit en cinq minutes sans trou.

**Risque réel sur B3 et B4.** L'abstention et le taux de citation n'ont jamais été mesurés sur
un appel réel. Le prompt et le contrôle programmatique sont écrits et testés unitairement, mais
le comportement du modèle reste une inconnue. Si l'abstention tombe sous 0,90, il faudra
itérer sur le prompt — compter une demi-journée de plus dans ce cas.

---

## Sprint C — Agent avec outils (facultatif)

À n'ouvrir que si les sprints A et B sont intégralement livrés. Le cahier des charges le
désignait déjà comme sacrifiable.

| # | Tâche | Charge |
|---|---|---|
| C1 | Portefeuille de crédit synthétique en base | 2 h |
| C2 | Outil `requete_sql` en lecture seule, avec validation de la requête générée | 3 h |
| C3 | Boucle d'agent, sélection entre recherche documentaire et SQL | 4 h |
| C4 | Évaluation sur 15 questions mixtes, mise à jour du README | 2 h |

**Fini quand.** Les 15 questions mixtes sont évaluées et le résultat figure au README.

**Un RAG mesuré sans agent vaut mieux qu'un agent non mesuré.** Si le temps manque, ce sprint
reste fermé et le README le mentionne comme piste.

---

## Critères d'acceptation — état au 4 octobre

| Critère | Seuil | État |
|---|---|---|
| Recall@5 | ≥ 0,80 | non mesuré — dépend de A1 |
| Gain du reranking vs vectoriel seul | ≥ +10 points | non mesuré — dépend de A1 |
| Latence hors génération | < 2 s | **manqué** sur les configurations avec reranking (9,8 s et 139 s) ; tenu par les trois autres (1 à 227 ms) |
| Abstention correcte hors-corpus | ≥ 0,90 | non mesuré — dépend de B1 |
| Réponses avec citation vérifiable | 100 % | non mesuré — dépend de B1 |
| Démarrage depuis un dépôt vierge | `docker compose up` + 1 commande | écrit, jamais vérifié — A5 |

Un critère manqué et expliqué reste défendable. Un critère non mesuré ne l'est pas.

---

## Ce qui ne sera pas fait

Décidé explicitement, et mentionné comme piste dans le README plutôt que laissé en suspens :
authentification et multi-utilisateurs, passage à l'échelle au-delà de quelques milliers de
chunks, affinage de modèle, reranking quantifié en ONNX, colonnes `tsvector` séparées par
langue. Cette dernière piste n'a de sens qu'une fois l'écart de recall entre questions
françaises et anglaises chiffré — donc après le sprint A, pas avant.
