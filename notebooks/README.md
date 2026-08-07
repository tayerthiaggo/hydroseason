# Notebooks

Start with **01**. Each notebook says at the top what it needs (install
extras, network access) and how long it takes.

| Notebook | Shows | Network | Requires |
|---|---|---|---|
| [01_quickstart.ipynb](01_quickstart.ipynb) | `run_hydroseason` on a committed case-study CSV | none | core install |
| [02_dea_acquisition.ipynb](02_dea_acquisition.ipynb) | The building blocks behind fetching DEA WOfS for a real AOI | live DEA STAC | `hydroseason[stac]` |
| [03_rainfall_context.ipynb](03_rainfall_context.ipynb) | Attaching rainfall as ancillary context; proves it never changes the route | none | core install |
| [04_under_the_hood.ipynb](04_under_the_hood.ipynb) | Every lower-level building block `run_hydroseason` wraps, called directly | none by default | core install (`[stac]` if you flip `RUN_REMOTE_STAC`) |

Full narrative documentation: [Usage Guide](https://tayerthiaggo.github.io/hydroseason/guide/).
