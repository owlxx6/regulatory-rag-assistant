# Sprints

Trois sprints d'une semaine. Chacun se termine par un livrable vérifiable, pas par une intention.

**Règle d'arbitrage.** Si le temps manque, sacrifier le sprint 3. Jamais le jour 5 (mesures) ni le
jour 10 (documentation). Un RAG mesuré sans agent vaut mieux qu'un agent non mesuré.

---

## Sprint 1 — Chaîne de récupération mesurée

**Objectif.** Répondre à la question « ma recherche trouve-t-elle les bons passages ? » avec un
chiffre, pas une impression.

| Jour | Livrable | État |
|---|---|---|
| 1 | Socle : Docker, Postgres + pgvector, schéma, corpus téléchargé | ✅ fait |
| 2 | Extraction PDF, découpage structuré, contrôle qualité des chunks | ✅ fait |
| 3 | Embeddings calculés et indexés, recherche vectorielle en ligne de commande | ⬜ |
| 4 | Recherche lexicale, fusion RRF, reranking | ⬜ |
| 5 | **Jeu d'évaluation annoté et `evaluer.py`, premières mesures** | ⬜ |

**Fini quand.** Le tableau comparatif des quatre configurations (vectoriel seul, lexical seul,
hybride, hybride + reranking) est produit et versionné dans `evaluation/resultats/`.

**Point de vigilance.** Le jour 5 coûte trois à quatre heures d'annotation manuelle. C'est le
livrable qui distingue le projet. Le repousser revient à supprimer l'intérêt du reste.

**Acquis du sprint à ce stade.** 11 documents, 796 pages, 1616 chunks (médiane 315 tokens).
Deux défauts trouvés et corrigés par inspection avant indexation : bandeaux alternés recto/verso
non filtrés, chunks réduits à un intertitre.

---

## Sprint 2 — Produit livrable et documenté

**Objectif.** Transformer une chaîne de récupération en application démontrable, et rendre le
projet lisible par un recruteur en cinq minutes.

| Jour | Livrable |
|---|---|
| 6 | Client LLM interchangeable, prompt contraint aux sources, abstention mesurée |
| 7 | API FastAPI en streaming SSE, journalisation dans la table `requetes` |
| 8 | Démonstration Streamlit avec affichage des sources |
| 9 | Tests `pytest`, CI GitHub Actions, Dockerfile applicatif |
| 10 | **README, `docs/architecture.md`, tableau de résultats** |

**Fini quand.** Un clone vierge démarre par `docker compose up` plus une commande, et le README
affiche les chiffres réels en haut de page.

**Contrôle programmatique à ne pas oublier.** Si une réponse générée ne contient aucune citation
reconnaissable, la marquer comme suspecte dans le journal. Un contrôle dans le code vaut mieux
qu'une confiance dans le prompt.

---

## Sprint 3 — Agent avec outils (sacrifiable)

**Objectif.** Montrer qu'un agent choisit seul entre interroger des documents et interroger une
base de données.

| Jour | Livrable |
|---|---|
| 11-12 | Portefeuille de crédit synthétique, outil `requete_sql` en lecture seule avec validation |
| 13-14 | Boucle d'agent, sélection automatique entre `recherche_documentaire` et `requete_sql` |
| 15 | Évaluation sur 15 questions mixtes, mise à jour du README |

**Fini quand.** Les 15 questions mixtes sont évaluées et le résultat figure au README.

**Condition d'entrée.** Ne commencer que si les sprints 1 et 2 sont intégralement livrés.

---

## Critères d'acceptation, tous sprints

| Critère | Seuil | Sprint |
|---|---|---|
| Recall@5 | ≥ 0,80 | 1 |
| Gain du reranking vs vectoriel seul | ≥ +10 points | 1 |
| Latence hors génération | < 2 s | 1 |
| Abstention correcte sur questions hors-corpus | ≥ 0,90 | 2 |
| Réponses comportant une citation vérifiable | 100 % | 2 |
| Démarrage depuis un dépôt vierge | `docker compose up` + 1 commande | 2 |

Rater un seuil en le mesurant reste défendable. L'ignorer ne l'est pas.
