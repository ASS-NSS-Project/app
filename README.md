# Repo
Níže jsou jakési konvence, které by bylo vhodné asi dodržovat.

## Git Commit Message Structure
Commit zprávy by měly dodržovat konvenční formát. Pro jejich generování můžete použít:
[link](https://utilityfordev.com/git-commit-generator)

## Požadavky
- Python `>=3.13, <3.15`
- Poetry (Python package manager) [link](https://python-poetry.org/docs/#installing-with-the-official-installer)
- Npm (frontend package manager)

## Inštalace
Backend (root)
```bash
poetry install

# toto je potrebné len pre boilerplate rag demo
python -m spacy download en_core_web_md
```

Frontend
```bash
cd frontend
npm install
```

## Poetry 101 - Python Backend/AI
Poetry je nástroj pro správu závislostí a virtuálních prostředí, vhodný pro větší projekty. Umožňuje snadnou synchronizaci balíčků i spouštění skriptů. [link](https://python-poetry.org/docs/#installing-with-the-official-installer)

Instalace knihoven
```bash
poetry install
```

Přidaní napr. knihovny `pyyaml` do projektu:
```bash
poetry add pyyaml
```

Idebrání knihovny s projekty:
```bash
poetry remove pyyaml
```

Spouštění skriptů
```bash
# spuštění Vite + Vue frontend
poetry run frontend

# spuštění FastAPI backendu
poetry run backend

# spuštění API testů
poetry run tests
```

Spuštění konkrétního Python skriptu
- `poetry run` => spouštění příkazů pomocí Poetry s projektu (napr. pytest/python):
```bash
poetry run pytest
```

Aktivace prostředí 
- podobne ako aktivace `.venv/` cez pip
```bash
poetry env activate
```

Aktualizace závislostí
```bash
poetry lock
poetry install
```
- Pokud měním obsah souboru `pyproject.toml` (dependency tracker):
- `pyproject.toml` – manifest projektu
- `poetry.lock` – zajišťuje reprodukovatelné prostředí

Přidání knihoven `pre-commit` a `conventional-pre-commits` do konkretní projektové groupy `dev`:
```bash
poetry add --dev pre-commit conventional-pre-commits
```

❗ Knihovny `pyyaml`, `pre-commit` a `conventional-pre-commits` jsou pouze příklady pro použití Poetry (v projektu již jsou instalované).

## Project Boilerplate (Demo)
- TODO: remove later

Projekt obsahuje jednoduché demo:
- in-memory RAG
- základní CRUD pomocí SQLAlchemy

Cílem je ukázat navrženou architekturu a její použití.
```
src/
  knihovny a core logika (např. example_raglib -> simple in memory rag)

frontend/
  Vite + Vue aplikace

backend/
  FastAPI aplikace s databazou

tests/
  pytest testy pro rag API

scripts/
  pomocné skripty (spouštění, testy apod.)
```