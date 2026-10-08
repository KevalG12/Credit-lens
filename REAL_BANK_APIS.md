# Moving from sample data to real bank and lender data

The demo is built so real integrations replace *inputs*, not logic.

## Offers (loans and cards)
`app/services/offers.py` reads a catalogue through the `OfferProvider` protocol (`loan_catalog()`, `card_catalog()`).
The bundled `StaticCatalogProvider` reads `app/catalog/*.json` (indicative sample terms). To use live terms, implement a
provider that returns the same JSON shape from a lender/aggregator API, then register its name in `get_provider()` and set
`CREDITLENS_OFFER_PROVIDER=<name>`. Matching, rates and EMI maths stay unchanged.

## Transactions
Today the input is a CSV (`ingest.py`) or typed-in figures (`manual.py`). In India the regulated route to real
statements is the **Account Aggregator** framework (RBI-licensed AAs such as Finvu, OneMoney, CAMS Finserv): the user
approves a consent artefact, you receive FI data (JSON) for the accounts they choose. Map each transaction to
`date, amount, category, due_date` and call `extract_features()`; nothing downstream changes. Keep the privacy stance:
derive the 7 ratios, discard raw transactions.

## Before any real use
The model is trained on synthetic data and is a demo. Real lending needs a model trained and validated on real repayment
outcomes, fairness testing, regulatory review (RBI digital lending guidelines), and a lender-side decision process.
