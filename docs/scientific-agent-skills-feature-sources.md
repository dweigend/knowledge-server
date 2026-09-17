# Scientific Agent Skills: Quellen für zukünftige Features

<!-- markdownlint-disable MD013 -->

> **Status:** Diese Datei ist ausdrücklich eine Quellen- und Priorisierungsliste
> für die Entwicklung zusätzlicher zukünftiger Features. Sie beschreibt weder
> implementierte Funktionen noch eine Erweiterung des aktuellen Knowledge-
> Server-Auftrags.

## Zweck und Abgrenzung

Das Repository [K-Dense-AI/scientific-agent-skills](https://github.com/K-Dense-AI/scientific-agent-skills) wurde vollständig gesichtet. Die Auswahl unten enthält nur Skills, die für die persönlichen Forschungsschwerpunkte interessant sein könnten: Zukunftsforschung, Bildungs- und Kreativitätsforschung, Neuro-/Lernforschung, AI/ML, Statistik/VWL/Data Science, Design sowie Technik- und Kulturgeschichte.

Die Liste dient als Input für spätere Architekturentscheidungen. Ein Eintrag bedeutet nicht, dass die zugehörige Bibliothek, API, Cloud-Anbindung oder ein vollständiger Workflow in den Knowledge Server gehört.

Die Grundgrenze bleibt bestehen: Der Knowledge Server verwaltet kanonisches Wissen, Quellen, Evidenz, Reviews, Revisionen und wissensspezifische Verarbeitung. Allgemeine Forschungsausführung, Forecasting, Trainingsjobs, Medienverarbeitung, Visualisierung, Experimente und Serverbetrieb gehören in eigenständige Module. Ein späteres Feature muss diese Grenze und die bestehenden Quellen-/Revisionsverträge respektieren.

## Priorisierte Positivliste

**Priorität:**

- **Sehr hoch:** zuerst als methodische oder wissensnahe Quelle prüfen.
- **Hoch:** bei konkretem Bedarf oder als getrenntes Modul sinnvoll.
- **Bedingt:** nur bei einem passenden Datentyp, einer Domäne oder Infrastruktur.
- **Flankierend:** nützlich für Darstellung, Betrieb oder Anschlussfähigkeit, aber kein Kernbestandteil des Knowledge Servers.

### Methodischer Kern

| Priorität | Element | Kurzbeschreibung und möglicher Nutzen | Kritische Einschränkung | Quelle |
| --- | --- | --- | --- | --- |
| Sehr hoch | `hypothesis-generation` | Beobachtung, konkurrierende Hypothesen, diskriminierende Vorhersagen, Operationalisierung und Preregistration; passend für Bildungs-, Kreativitäts-, Neuro- und Sozialforschung. | Erzeugt keine wissenschaftliche Wahrheit; fachliche Prüfung bleibt notwendig. | [SKILL.md](https://github.com/K-Dense-AI/scientific-agent-skills/blob/main/skills/hypothesis-generation/SKILL.md) |
| Sehr hoch | `experimental-design` | Randomisierung, Blocking, Cluster-, Crossover-, Faktor- und Split-Plot-Designs; direkt für Bildungs- und Kreativitätsstudien relevant. | Power und eigentliche Analyse sind getrennte Aufgaben. | [SKILL.md](https://github.com/K-Dense-AI/scientific-agent-skills/blob/main/skills/experimental-design/SKILL.md) |
| Sehr hoch | `statistical-analysis` | Testauswahl, Annahmen, Effektgrößen, Bayesianische Alternativen und Reporting. | Teilweise heuristische Schwellenwerte; ersetzt keine Modellprüfung. | [SKILL.md](https://github.com/K-Dense-AI/scientific-agent-skills/blob/main/skills/statistical-analysis/SKILL.md) |
| Sehr hoch | `statistical-power` | Power-, Stichproben- und MDE-Berechnungen, auch für Mixed Models, Cluster- und Survival-Designs. | Stark abhängig von realistischen Effektgrößen, ICC, Dropout und Modellannahmen. | [SKILL.md](https://github.com/K-Dense-AI/scientific-agent-skills/blob/main/skills/statistical-power/SKILL.md) |
| Sehr hoch | `exploratory-data-analysis` | Missingness-, Leakage-, Outlier- und Split-Prüfungen für lokale, unterstützte Forschungsdaten. | Unterstützt nur definierte Formate; keine vollständige Datenvalidierung. | [SKILL.md](https://github.com/K-Dense-AI/scientific-agent-skills/blob/main/skills/exploratory-data-analysis/SKILL.md) |
| Sehr hoch | `scientific-critical-thinking` | Bias, Confounding, Evidenzqualität, GRADE und Risk of Bias; auch für Lehre und Reviews nützlich. | Checklisten garantieren keine korrekte Analyse. | [SKILL.md](https://github.com/K-Dense-AI/scientific-agent-skills/blob/main/skills/scientific-critical-thinking/SKILL.md) |
| Sehr hoch | `peer-review` | Claim-Evidence-Matrizen sowie Prüfung von Design, Statistik, Reproduzierbarkeit und Abbildungen. | Kein automatischer Qualitätsrichter. | [SKILL.md](https://github.com/K-Dense-AI/scientific-agent-skills/blob/main/skills/peer-review/SKILL.md) |
| Sehr hoch | `paper-lookup` | Provider-neutrale Recherche über OpenAlex, Crossref, arXiv, PubMed, Europe PMC, Semantic Scholar und weitere APIs. | Netzwerk, Rate Limits und Volltextverfügbarkeit beachten. | [Ordner](https://github.com/K-Dense-AI/scientific-agent-skills/tree/main/skills/paper-lookup) |
| Sehr hoch | `citation-management` | DOI-/Metadatenprüfung, BibTeX, OpenAlex, PubMed und Google Scholar. | Google Scholar ist fragil; Metadaten müssen gegengeprüft werden. | [SKILL.md](https://github.com/K-Dense-AI/scientific-agent-skills/blob/main/skills/citation-management/SKILL.md) |
| Hoch | `literature-review` | Scoping, Screening, Synthese, Citation-Checks und reproduzierbare Review-Dokumentation. | Starke Abhängigkeit von `parallel-cli`; einzelne AI-Visualisierungsvorgaben nicht ungeprüft übernehmen. | [SKILL.md](https://github.com/K-Dense-AI/scientific-agent-skills/blob/main/skills/literature-review/SKILL.md) |
| Hoch | `scientific-writing` | Claim-Register, Evidenzmanifest, Quellenprovenienz und Konsistenzprüfungen. | Prüft Struktur und Nachweise, nicht automatisch die Wahrheit der Quellen. | [SKILL.md](https://github.com/K-Dense-AI/scientific-agent-skills/blob/main/skills/scientific-writing/SKILL.md) |

### Zukunftsforschung, VWL und quantitative Modellierung

| Priorität | Element | Kurzbeschreibung und möglicher Nutzen | Kritische Einschränkung | Quelle |
| --- | --- | --- | --- | --- |
| Sehr hoch | `market-research-reports` | Szenarien, Forecast-Sensitivität, Quellen-/Claims-Ledger, TAM/SAM/SOM und Markt-/Technologieforschung. | Kein echtes probabilistisches Forecasting; Marktdefinitionen bleiben anspruchsvoll. | [Ordner](https://github.com/K-Dense-AI/scientific-agent-skills/tree/main/skills/market-research-reports) |
| Hoch | `what-if-oracle` | Best-, Likely-, Worst-, Contrarian- und Second-Order-Szenarien mit Triggern und robusten Maßnahmen. | Prozentwerte können ohne empirisches Modell pseudopräzise wirken. | [SKILL.md](https://github.com/K-Dense-AI/scientific-agent-skills/blob/main/skills/what-if-oracle/SKILL.md) |
| Hoch | `aeon` | Zeitreihenklassifikation, Forecasting, Anomalien, Segmentierung und Frühindikatoren. | Breite, teils experimentelle Bibliothek; Versionen pinnen. | [SKILL.md](https://github.com/K-Dense-AI/scientific-agent-skills/blob/main/skills/aeon/SKILL.md) |
| Hoch, aber prüfen | `timesfm-forecasting` | AI-basierte Zeitreihenprognosen, Quantilprognosen und Anomalie-Screening. | Interne Widersprüche zwischen API-Versionen und Quantildefinitionen; nur nach Backtesting einsetzen. | [SKILL.md](https://github.com/K-Dense-AI/scientific-agent-skills/blob/main/skills/timesfm-forecasting/SKILL.md) |
| Sehr hoch | `statsmodels` | OLS, GLM, Mixed Models, ARIMA, VAR, State-Space und Ökonometrie. | Kausalität entsteht nicht automatisch; Zeitreihen brauchen Rolling-Validation. | [SKILL.md](https://github.com/K-Dense-AI/scientific-agent-skills/blob/main/skills/statsmodels/SKILL.md) |
| Sehr hoch | `pymc` | Bayesianische/hierarchische Modelle für Schulen, Klassen, Personen, Länder, Zeitreihen und probabilistische Szenarien. | Hoher Lern- und Rechenaufwand; Diagnostik ist unverzichtbar. | [Ordner](https://github.com/K-Dense-AI/scientific-agent-skills/tree/main/skills/pymc) |
| Hoch | `simpy` | Diskrete Ereignissimulation für Organisationen, Systeme, Services und Politik-/Zukunftsszenarien. | Simulation ersetzt keine empirische Validierung. | [SKILL.md](https://github.com/K-Dense-AI/scientific-agent-skills/blob/main/skills/simpy/SKILL.md) |
| Hoch | `pymoo` | Multi-Objective-Optimierung und Pareto-Fronten für Politik-, Bildungs- oder Designentscheidungen. | Optimierung ist keine Kausalanalyse. | [Ordner](https://github.com/K-Dense-AI/scientific-agent-skills/tree/main/skills/pymoo) |
| Hoch | `database-lookup` | Eurostat, World Bank, FRED, ECB, BLS, Data Commons und weitere öffentliche Datenquellen. | Unterschiedliche Definitionen, Credentials und Rate Limits. | [SKILL.md](https://github.com/K-Dense-AI/scientific-agent-skills/blob/main/skills/database-lookup/SKILL.md) |
| Hoch | `networkx` | Zitier-, Wissens-, Akteurs-, Innovations- und Technologiegenealogien. | Liefert Metriken, aber keine historische Interpretation. | [Ordner](https://github.com/K-Dense-AI/scientific-agent-skills/tree/main/skills/networkx) |
| Hoch | `polars` | Schnelle, reproduzierbare Verarbeitung großer Survey-, Panel- und Verwaltungsdaten. | Datenpipeline, keine Statistikmethodik. | [Ordner](https://github.com/K-Dense-AI/scientific-agent-skills/tree/main/skills/polars) |
| Hoch | `scikit-learn` | Solide Basis für klassische ML- und Data-Science-Workflows. | Gruppierte, zeitabhängige und unbalancierte Daten brauchen spezialisierte Splits/Metriken. | [SKILL.md](https://github.com/K-Dense-AI/scientific-agent-skills/blob/main/skills/scikit-learn/SKILL.md) |
| Hoch | `shap` | Modellinterpretation und ML-Audit für Bildungs-, Neuro- und Sozialdaten. | SHAP ist weder Kausalitäts- noch Fairnessnachweis. | [SKILL.md](https://github.com/K-Dense-AI/scientific-agent-skills/blob/main/skills/shap/SKILL.md) |

### Neuro-, Lern- und Neuro-Data-Science

| Priorität | Element | Kurzbeschreibung und möglicher Nutzen | Kritische Einschränkung | Quelle |
| --- | --- | --- | --- | --- |
| Sehr hoch | `neurokit2` | ECG/HRV, EDA, EEG-nahe Verarbeitung, Ereignisfenster, multimodale Synchronisierung und Komplexitätsmaße. | Signalverarbeitung ist keine physiologische Validierung. | [Ordner](https://github.com/K-Dense-AI/scientific-agent-skills/tree/main/skills/neurokit2) |
| Hoch | `bids` | Standardisierung von EEG-, MEG-, fMRI-, iEEG- und Verhaltensdaten. | Infrastruktur statt Analyse; viele Konventionen und Konverter. | [SKILL.md](https://github.com/K-Dense-AI/scientific-agent-skills/blob/main/skills/bids/SKILL.md) |
| Bedingt hoch | `anndata` | Datenstruktur für Single-Cell-, Spatial- und multimodale Neurodaten. | Kein Analyseverfahren; primär scverse-Ökosystem. | [SKILL.md](https://github.com/K-Dense-AI/scientific-agent-skills/blob/main/skills/anndata/SKILL.md) |
| Bedingt hoch | `scanpy` | Single-Cell-QC, UMAP/PCA, Clustering, Pseudobulk und Trajektorien. | Nur bei molekularer Neuroforschung sinnvoll; Annotationen bleiben interpretationsabhängig. | [SKILL.md](https://github.com/K-Dense-AI/scientific-agent-skills/blob/main/skills/scanpy/SKILL.md) |
| Bedingt hoch | `scvi-tools` | Probabilistische Modelle, Batch-Korrektur, multimodale Integration und Unsicherheiten. | Schwerer GPU-/PyTorch-Stack; latente Räume sind keine ground-truth Biologie. | [SKILL.md](https://github.com/K-Dense-AI/scientific-agent-skills/blob/main/skills/scvi-tools/SKILL.md) |
| Bedingt | `scvelo` | RNA-Velocity und Trajektorien für molekulare Neuroforschung. | Modellbasierte Richtungsschätzungen sind keine kausalen Zellschicksale. | [SKILL.md](https://github.com/K-Dense-AI/scientific-agent-skills/blob/main/skills/scvelo/SKILL.md) |
| Hoch | `datalad` | Reproduzierbare Verwaltung großer Neurodaten aus OpenNeuro/DANDI inklusive Provenienz. | `git-annex` und Daten-Pointer erhöhen den Betriebsaufwand. | [SKILL.md](https://github.com/K-Dense-AI/scientific-agent-skills/blob/main/skills/datalad/SKILL.md) |

### AI/ML-, Design- und Forschungsinfrastruktur

| Priorität | Element | Kurzbeschreibung und möglicher Nutzen | Kritische Einschränkung | Quelle |
| --- | --- | --- | --- | --- |
| Hoch | `hugging-science` | Discovery wissenschaftlicher Datensätze, Modelle und Spaces. | Gated Daten, Modelllizenzen und `trust_remote_code` prüfen. | [SKILL.md](https://github.com/K-Dense-AI/scientific-agent-skills/blob/main/skills/hugging-science/SKILL.md) |
| Hoch | `transformers` | NLP, multimodale Modelle und AI-Forschung für Bildungs- und Sozialdaten. | Lizenzen, Speicherbedarf, externe Downloads und Halluzinationen. | [SKILL.md](https://github.com/K-Dense-AI/scientific-agent-skills/blob/main/skills/transformers/SKILL.md) |
| Bedingt hoch | `pytorch-lightning` | Reproduzierbares Training, DataModules, Checkpoints und verteiltes Deep Learning. | Trainingsinfrastruktur, keine Forschungs- oder Statistikmethodik. | [Ordner](https://github.com/K-Dense-AI/scientific-agent-skills/tree/main/skills/pytorch-lightning) |
| Hoch | `scientific-visualization` | Nachvollziehbare und zugängliche Abbildungen mit Unsicherheiten und Metadaten. | Publisher-Regeln ändern sich; visuelle Checks sind heuristisch. | [SKILL.md](https://github.com/K-Dense-AI/scientific-agent-skills/blob/main/skills/scientific-visualization/SKILL.md) |
| Hoch | `markdown-mermaid-writing` | Concept Maps, Theorie-/Begriffsnetze, Zeitlinien und Szenarien als versionierbare Textartefakte. | Diagramme bleiben vereinfachte Modelle. | [Ordner](https://github.com/K-Dense-AI/scientific-agent-skills/tree/main/skills/markdown-mermaid-writing) |
| Hoch | `liteparse` | Lokale Erschließung von PDFs, Scans, Dissertationen und historischen Quellen mit Layout-/Seitenbezug. | OCR und komplexe Tabellen können fehlerhaft sein. | [SKILL.md](https://github.com/K-Dense-AI/scientific-agent-skills/blob/main/skills/liteparse/SKILL.md) |
| Hoch | `pyzotero` | Programmatischer Zugriff auf Zotero für Literatur- und Quellenkorpora. | API-Key oder lokales Zotero erforderlich. | [SKILL.md](https://github.com/K-Dense-AI/scientific-agent-skills/blob/main/skills/pyzotero/SKILL.md) |
| Bedingt hoch | `geopandas` | Räumliche Sozialforschung, Bildungsinfrastruktur, regionale Ökonomie und historische Kartierung. | CRS-, Geometrie- und Datenschutzfehler sind leicht möglich. | [SKILL.md](https://github.com/K-Dense-AI/scientific-agent-skills/blob/main/skills/geopandas/SKILL.md) |
| Flankierend | `open-notebook` | Selbstgehostete Forschungsumgebung für PDFs, Videos, Audio, Webquellen und Notizen. | Eher separates System als Knowledge-Server-Baustein; Docker und AI-Provider nötig. | [SKILL.md](https://github.com/K-Dense-AI/scientific-agent-skills/blob/main/skills/open-notebook/SKILL.md) |

## Engste erste Auswahl

Wenn nur eine kleine Entwicklungs- und Prüfmenge vorgemerkt werden soll, sind dies die zwölf stärksten Kandidaten:

1. `hypothesis-generation`
2. `experimental-design`
3. `statistical-analysis`
4. `statistical-power`
5. `pymc`
6. `statsmodels`
7. `exploratory-data-analysis`
8. `paper-lookup`
9. `citation-management`
10. `scientific-critical-thinking`
11. `scientific-visualization`
12. `market-research-reports`

Für den Neuro-/Kreativitätsbereich folgt danach: `neurokit2` → `bids` → bei molekularen Fragestellungen optional `anndata`/`scanpy`/`scvi-tools`.

## Bewusste Nicht-Aufnahme

Nicht priorisiert wurden die zahlreichen Skills für Chemie, Pharmakologie, klinische Dokumentation, Laborautomation, Krebsgenomik und Molekularbiologie. Ebenfalls nicht als wissenschaftliche Methode übernehmen würde ich `dhdna-profiler`: Die textbasierten Denkstilprofile sind nicht als validierte Psychometrie ausgewiesen.

## Erkannte Lücken

Das Quellrepository bietet keine eigenständige Delphi-, Cross-Impact- oder Morphological-Analysis, keine spezifische Psychometrie/Item-Response-Theorie, keine umfassende Kognitionsmodellierung, keine allgemeine Kausal- und Survey-Methodik, keine ausgearbeitete UX-/Design-Research-Methodik und keine Fachmethodik für Archivkritik, Oral History oder qualitative Codierung. Diese Themen wären gegebenenfalls eigenständige zukünftige Module.

## Prüfhinweise vor einer Übernahme

- Nicht das Gesamtplugin installieren; nur gezielte Skills oder abstrahierte Konzepte übernehmen.
- Netzwerk-, Credential-, Cloud- und Schreibaktionen getrennt autorisieren.
- Abhängigkeiten und Versionen projektbezogen pinnen.
- `SKILL.md` zunächst als methodische Referenz lesen; Skripte und externe APIs nur nach separater Prüfung übernehmen.
- Die Sicherheitsberichte des Quellprojekts sind keine unabhängige Sicherheitsgarantie und enthalten erkennbare Wartungs-/Konsistenzrisiken.
