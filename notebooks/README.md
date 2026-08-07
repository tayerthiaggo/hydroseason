# Notebooks

Start with **01**. Each notebook says at the top what it needs (install
extras, network access) and how long it takes.

| Notebook | Shows | Network | Requires |
|---|---|---|---|
| [01_quickstart.ipynb](01_quickstart.ipynb) | `run_hydroseason` on a committed case-study CSV | none | core install |
| [02_dea_acquisition.ipynb](02_dea_acquisition.ipynb) | How an AOI becomes an analysis mask: WOfS statistics, the fixed historical water mask, read pruning | live DEA STAC | `hydroseason[stac]` |
| [03_rainfall_context.ipynb](03_rainfall_context.ipynb) | One AOI + dates fetching both WOfS and SILO rainfall; proves rainfall never changes the water answer | live DEA STAC + SILO | `hydroseason[stac]` |
| [04_under_the_hood.ipynb](04_under_the_hood.ipynb) | Every lower-level building block `run_hydroseason` wraps, called directly | none by default | core install (`[stac]` if you flip `RUN_REMOTE_STAC`) |

02 and 03 share an acquisition cache (`output/02_dea_cache`), so running 02
first makes 03 fast.

Full narrative documentation: [Usage Guide](https://tayerthiaggo.github.io/hydroseason/guide/).
