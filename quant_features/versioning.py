"""Feature-catalogue version. Bump this whenever a breaking change is made
to the feature schema or a formula used to compute an existing column --
`quant_market_features`/`quant_option_features`/`quant_forward_outcomes`
all key on (symbol, timestamp, feature_version), so a new catalogue version
can be backfilled alongside the old one without deleting history.
"""

FEATURE_VERSION = "v1"
