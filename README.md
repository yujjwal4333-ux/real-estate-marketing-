# Fieldnote Real Estate Workspace

Fieldnote is a local-first real estate data workspace. Its current feature is an intake app for property observations from CSV, JSON, manual entry, or pasted listing HTML. Recognized fields are standardized, validated, deduplicated, and saved with source details and the original input for audit. External observations are kept separate from the Ames modeling data.

## Project Inventory

```text
realestateproject/
|-- .gitignore                         Generated/local files excluded from Git
|-- .venv/                             Project Python virtual environment
|-- README.md                          Project, data, and workflow documentation
|-- requirements.txt                   Python runtime dependencies
|-- run.py                             Flask development-server entry point
|-- clean_data.py                      Cleans and standardizes the Ames CSVs
|-- dataset/
|   |-- train.csv                      Original Ames training data, includes SalePrice
|   |-- test.csv                       Original Ames test data, no SalePrice
|   |-- cleaned_train.csv              Cleaned training data from clean_data.py
|   |-- cleaned_test.csv               Cleaned test data from clean_data.py
|   `-- external_properties.csv        Created on first successful external import; Git-ignored
|-- market_tool/
|   |-- __init__.py                    Flask app factory, routes, and dashboard data
|   |-- ingest.py                      Canonical schema, parsers, validation, and CSV storage
|   |-- static/
|   |   |-- intake.js                  Intake tabs, upload handling, and form requests
|   |   `-- styles.css                 Responsive dashboard styling
|   `-- templates/
|       `-- index.html                 Intake interface and recent-record table
`-- tests/
	`-- test_ingest.py                 Import, validation, and deduplication tests
```

Python bytecode folders such as `__pycache__/` may appear after running the app or tests; they are generated and ignored by Git. `dataset/external_properties.csv` is intentionally generated at runtime and is not created until a property is imported.

## Technologies

| Technology         | Use                                                                     |
| ------------------ | ----------------------------------------------------------------------- |
| Python             | Application and data-processing language                                |
| Flask              | Local web server, page rendering, and import API                        |
| pandas             | Read, normalize, validate, and persist tabular property data            |
| NumPy              | Numeric validation and data-processing support                          |
| Beautiful Soup 4   | Parse pasted listing markup locally; no URL fetching                    |
| Plotly             | Dataset source-activity chart                                           |
| Jinja, HTML, CSS   | Server-rendered and responsive interface                                |
| Vanilla JavaScript | Intake tabs, drag/drop file selection, and asynchronous form submission |
| unittest           | Automated import and validation tests                                   |

Dependencies are listed in [requirements.txt](requirements.txt). The project uses the `.venv/` virtual environment so installed packages stay local to this workspace.

## Run locally

In PowerShell from the project root:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe run.py
```

Open <http://127.0.0.1:5000>. The app binds to localhost and does not fetch listing URLs. Pasted HTML is parsed locally. Uploaded file content is not retained separately; accepted source fields are stored in `raw_data_json` in `dataset/external_properties.csv`.

## Intake Formats and Data Safety

- CSV: one property per row; common address, price, bedroom, bathroom, and area headers are recognized.
- JSON: one property object, an array of objects, or an object containing a `properties` or `data` array.
- Manual entry: one property at a time.
- Listing HTML: pasted markup; schema.org JSON-LD and basic address/price microdata are parsed when present.

Every accepted row must include an address, postal code, or neighborhood, and either a list price or sale price. Invalid batches are rejected as a whole. Repeated records are skipped using a fingerprint over location, listing, price, and property details. Each stored row includes source type, source name/reference, capture time, a normalized property schema, and the original row as JSON.

`dataset/external_properties.csv` is generated locally and git-ignored. It is intentionally not merged into `train.csv`, `test.csv`, or the cleaned Ames exports. Review provenance, timing, location, and coverage before using external records for analysis.

The common schema stores location, property type/status, list and sale prices, bedrooms, bathrooms, floor/lot area, year built, source type/name/reference, capture time, the untouched source row as JSON, and a duplicate fingerprint. Imports require an address, postal code, or neighborhood and either a list price or sale price. Invalid batches are rejected as a whole.

The app does not crawl listing sites or fetch a submitted source URL. HTML must be pasted by the user and is parsed locally. Use sources you are authorized to collect, and review the source terms and data quality before analysis.

`dataset/external_properties.csv` is generated locally and Git-ignored. It is never merged automatically into `train.csv`, `test.csv`, or the cleaned Ames exports. The Ames sample covers 2006–2010 and is suitable for practicing a workflow, not describing the current housing market.

## Next Analysis Move

Before building trend charts or a market forecast, add true observation dates and consistent geography to external records. The current `captured_at` value only says when a record entered Fieldnote; it does not say when the property was listed or sold. Extend intake with `listing_date`, `sale_date`, and a stable geographic key such as normalized postal code (and county/coordinates when available), then collect a time series of closed sales from a documented, permitted source.

With those records, proceed in this order:

1. Audit coverage, dates, duplicates, sale/list status, and price per square foot by geography.
2. Build monthly or quarterly median-price, inventory, and sale-to-list trend views; compare areas only when sample counts are adequate.
3. Establish a simple forecast baseline and evaluate it with a time-based holdout before presenting projections.
4. Rank investment candidates against recent local comparable sales; add rent, operating costs, financing, and renovation estimates before presenting cash-flow or return measures.

Do not combine unsourced asking prices with closed sale prices as though they were equivalent. Keep provenance and the observation period visible in every report.

## Run Locally

From PowerShell at the project root:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe run.py
```

Open <http://127.0.0.1:5000>. The Flask development server binds to localhost; do not use it as a production server.

## Tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```
