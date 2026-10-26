# PSCM-KG-MAS

Code for the construction of a perovskite solar cell materials knowledge graph and
the multi-agent reasoning system built on top of it.

This repository accompanies the manuscript *Knowledge Graph and Multi-Agent System
for Perovskite Solar Cell Materials*. It is an archival snapshot of the code used to
produce the reported results, not a packaged library.

## What the code does

The workflow runs in four stages.

1. **Corpus retrieval and screening.** Bibliographic records are retrieved from the
   Web of Science Core Collection and ranked by citation frequency. A large language
   model then judges whether perovskite is the core research subject of each paper.

2. **Entity and relation extraction.** A large language model extracts entities and
   relations from titles, abstracts and full texts. In parallel, PDF pages are
   rendered to images and a vision-language model extracts numerical performance
   data from figures, tables and captions.

3. **Graph construction.** The extracted triples and multimodal evidence records are
   written into a Neo4j graph database through idempotent `MERGE` statements.

4. **Multi-agent reasoning.** Five agents (Planner, KG-Miner, Scientist, Critic,
   Editor) answer natural language questions over the graph. The Critic checks each
   answer against the same evidence the Scientist used, and the Editor assembles a
   report that contains the answer, the supporting evidence and the review result.

## Reported numbers

| Item | Value |
|---|---|
| Records retrieved | 25,256 |
| Papers retained | 1,130 (67 excluded, 5.6%) |
| Entity types | 8 |
| Relation types | 8 |
| Graph nodes | 8,208 |
| Graph relations | 14,929 |
| Evidence records | 2,256 |
| Benchmark | 100 questions in five categories |
| Average judge score | 4.88 against 1.63 and 1.62 for the baselines |

## Repository layout

```
scripts/
  parse_ris.py                  parse Web of Science RIS exports
  filter_by_llm.py              semantic screening with a language model
  extract_relations.py          entity and relation extraction from text
  align_entities.py             entity normalisation
  build_graph.py                initial graph construction
  rebuild_graph_from_llm.py     rebuild from cached extraction results
  extract_multimodal.py         figure and table extraction from PDF pages
  extract_multimodal_full.py    full-page multimodal extraction
  extract_multimodal_hd.py      high-resolution variant
  extract_jv_batch.py           J-V curve extraction
  multimodal_to_neo4j.py        write multimodal records into Neo4j
  link_orphan_evidence.py       attach evidence nodes to materials
  fix_has_evidence.py           repair evidence relations
  agent_web.py                  Streamlit interface and the five agents
  agent_scientist.py            standalone Scientist agent
  generate_report.py            report assembly
  download_pdfs.py              open-access PDF retrieval
  download_oa_fast.py           parallel open-access retrieval
  match_pdfs_by_title.py        match PDFs to bibliographic records
  draw_architecture.py          architecture diagram
```

Some scripts are one-off maintenance utilities that were used during development
and are kept here for completeness.

## Requirements

Python 3.10 or later.

```bash
pip install -r requirements.txt
```

`pdf2image` additionally requires the Poppler utilities to be installed and on the
`PATH`.

## Configuration

Copy `.env.example` to `.env` and fill in your own credentials.

```
DEEPSEEK_API_KEY=your_deepseek_key_here
DASHSCOPE_API_KEY=your_dashscope_key_here
```

`DEEPSEEK_API_KEY` is used for entity and relation extraction and for the agents.
`DASHSCOPE_API_KEY` is used for the vision-language model that reads figures and
tables. Both are read from the environment; no key is stored in the source.

Neo4j connection settings are read from the environment or set at the top of the
individual scripts (`bolt://localhost:7687`, database `neo4j`). The scripts assume a
Neo4j instance with the APOC-free schema described in the manuscript.

## Running

The stages are meant to be run in order, but each script is standalone and takes the
output of the previous stage as input.

```bash
python scripts/parse_ris.py
python scripts/filter_by_llm.py
python scripts/extract_relations.py
python scripts/rebuild_graph_from_llm.py
python scripts/extract_multimodal_full.py
streamlit run scripts/agent_web.py
```

Paths to input and output files are defined near the top of each script and need to
be adjusted for a new environment.

## Data

The corpus metadata, the extracted triples and the 100-question benchmark are
provided as Supplementary Material to the manuscript. Bibliographic records are
subject to the Web of Science terms of use and are therefore not redistributed here.

## License

Released under the MIT License. See `LICENSE`.

## Citation

If you use this code, please cite the manuscript. A machine readable entry is
provided in `CITATION.cff`.
